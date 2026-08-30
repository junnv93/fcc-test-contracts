"""Account-axis throttle for credential endpoints — the *charging* half (2026-08-22).

:mod:`domain.services.rate_limit_policy` owns every decision (how large the
account budget is, how the bucket key is formed) and
:mod:`application.common.rate_limit` owns the counters. This module owns the
one thing neither of them can: turning *"here is the request body a login
attempt arrived with"* into a charge against the right bucket.

Why the account axis exists at all
----------------------------------

The inbound middleware charges two tiers, peer and identity, and neither one can
bound password guessing on this deployment:

- the **identity** tier is keyed on a trusted-header subject (only in
  ``trusted_headers`` mode) or a bearer token. A login request carries neither, so
  ``resolve_client_key`` answers ``None`` and the tier is simply absent;
- the **peer** tier is keyed on the transport source address, and *what that means*
  is a deployment property. When this module landed it was **one value for
  everybody**: uvicorn's ``forwarded_allow_ips`` defaulted to ``127.0.0.1`` while
  nginx proxied from a different container address, so ``resolve_peer_key`` saw
  the gateway rather than the tester. **That was closed the same day**
  (``peer-axis-trusted-hop``, ADR-0021 ``D-14``): the shipped compose now names the
  reverse proxy's static address in ``FORWARDED_ALLOW_IPS``, and a deployment that
  uses it charges the peer tier per caller
  (:func:`domain.services.proxy_trust_policy.peer_axis_mode` answers which state a
  process is in, and boot logs it).

  ⚠️ **The axis argument below does not move with it.** A per-caller peer ceiling
  is still the wrong instrument for *"how fast may one password be guessed"*: a
  source ceiling answers *"how many people sign in at 9am"*, and the two questions
  have different populations. Do not re-derive one from the other in either
  direction — ADR-0021 ``D-11`` records what that cost.

OWASP's Authentication Cheat Sheet settles the axis question directly:

    "The counter of failed logins should be associated with the account itself,
    rather than the source IP address, in order to prevent an attacker from making
    login attempts from a large number of different IP addresses."

So a source-only axis is below standard *regardless of NAT*. EMS reached the same
conclusion from a production incident (2026-08-11, ~30 concurrent logins mostly
429) and recorded it as an **axis correction**, not an environment workaround.
This module is FCC's half of that correction.

Why the route boundary and not the middleware
---------------------------------------------

The identifier lives in the request body, and the middleware is deliberately
body-blind: it is keyed on headers and a path so it can shed a flood before any
parsing happens.

⚠️ An earlier draft justified this with *"reading the body in a Starlette
``BaseHTTPMiddleware`` consumes the receive channel, so the handler sees an empty
body"*. **That is false on the Starlette this repository installs** (1.3.1 —
measured: middleware and handler both read the full body). It was true of much
older Starlette, and stating it in the present tense would have left the next
reader with a wrong belief about their own framework.

The real reasons are two, and neither depends on framework internals: the route
boundary already holds the parsed ``dict`` the handler will use, so no second
parse is needed; and it knows *which operation* this is, which is what selects the
identifier field. The middleware knows neither.

⚠️ That split is also what makes the *field* question safe. EMS's guard runs
before validation and therefore had to carry a per-route field whitelist, because
a request could carry a field the handler ignores but the tracker reads (one
throwaway field per request = one fresh bucket per request = no account axis).
Here the throttle reads the same ``dict`` the handler reads, so the property holds
by construction — and is sealed anyway, because "by construction" is a property of
today's code, not of the type system.

The four things a credential tracker must not get wrong
-------------------------------------------------------

1. **Total function.** The body is arbitrary at this point. A raise here turns a
   login into a 500.
2. **Fail-closed.** Failing to read an identifier must not open the throttle. It
   falls back to no account charge — and the peer tier, already charged by the
   middleware, is what remains.
3. **No plaintext.** The tracker string reaches a limiter key and can reach a
   diagnostic dump.
4. **Deterministic.** A random component would mean the account axis does not
   exist.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

from fcc_test_contracts.common.identity import normalize_email
from fcc_test_contracts.common.rate_limit import FixedWindowRateLimiter, RateLimitOutcome
from fcc_test_contracts.common.login_throttle_policy import fingerprint_digest
from fcc_test_contracts.common.rate_limit_policy import RateLimitPolicy


__all__ = [
    'CREDENTIAL_IDENTIFIER_FIELDS',
    'CredentialThrottle',
    'extract_credential_identifier',
]


#: Body fields the account axis may read, per operation, in precedence order.
#:
#: ⚠️ **A whitelist, not "whatever the body has".** The rule is *"a field the
#: handler does not read, the tracker does not read either"* — see the module
#: docstring for the bypass this closes. The sets are sealed against both the
#: request schema in ``api_contracts`` and the keys the adapter method actually
#: reads, so widening one without the other is red.
#:
#: ``local_auth_change_password`` is absent on purpose, and the reason is in the
#: route module: that surface is bounded by the account **lockout** (five wrong
#: current-passwords, fifteen minutes), which is far tighter than this tier, and
#: putting it here made a 400 "your new password is too weak" cost the same budget
#: as a guess on the one screen every new operator must pass through.
CREDENTIAL_IDENTIFIER_FIELDS: Mapping[str, tuple] = {
    'local_auth_login': ('email',),
}



def extract_credential_identifier(
    body: object, fields: Iterable[str],
) -> Optional[str]:
    """First non-empty whitelisted field of ``body``, normalised. Total function.

    Normalisation is :func:`application.common.identity.normalize_email` — the
    **same call** the login path uses to resolve the stored identity. Sharing the
    function rather than re-expressing the rule is what makes "change the case and
    get a fresh bucket" impossible: two normalisers would drift, and the drift is
    the bypass.

    Returns ``None`` when no whitelisted field carries a usable string. Never
    raises, for any ``body`` — including non-mappings, non-string field values and
    values whose ``__getitem__`` misbehaves.
    """
    if not isinstance(body, Mapping):
        return None
    for field in fields:
        try:
            raw = body.get(field)
        except Exception:  # noqa: BLE001 — a hostile Mapping must not 500 a login
            continue
        normalized = normalize_email(raw)
        if normalized:
            return normalized
    return None


class CredentialThrottle:
    """Charges the account tier for one credential attempt.

    ⚠️ **Takes its own limiter, and must not be handed the middleware's.** The
    limiter caps tracked keys and evicts least-recently-seen, and the middleware
    mints a key per presented ``Authorization`` header — so a shared pool lets an
    unauthenticated attacker churn junk bearer tokens until a victim's account
    bucket is evicted and their spent budget is **reset to full** (demonstrated by
    adversarial review, 2026-08-22). Eviction "only forgives", which is harmless
    for a fairness limiter and is the whole attack against a credential budget.
    """

    def __init__(
        self,
        *,
        policy: Optional[RateLimitPolicy],
        limiter: FixedWindowRateLimiter,
        secret: object,
    ) -> None:
        self._policy = policy
        self._limiter = limiter
        # ⚠️ The local JWT signing secret, for the same reason
        # ``LoginSprayingDetector`` uses it: the digests must survive a restart (a
        # fresh random salt would hand every deploy a clean budget) and it is the
        # one value this process holds that an attacker does not. Nothing derived
        # from it is ever emitted — only bucket keys, which are already digests.
        self._secret = secret

    @property
    def enabled(self) -> bool:
        """Whether this throttle charges anything.

        Mirrors the middleware's kill-switch semantics exactly: ``None`` policy or
        ``enabled=False`` means the deployment turned throttling off, and the
        account axis must not be the one tier that ignores that. An absent signing
        secret also answers ``False`` — see below.
        """
        if self._policy is None or not self._policy.enabled:
            return False
        # ⚠️ **No secret means no keyed digest, so this tier does not run.**
        # ``fingerprint_digest`` does ``str(secret or '')``, so an absent secret
        # silently produces an UNKEYED HMAC that anyone can recompute — and the
        # comment above would then be false. That is the state in every non-
        # ``local_jwt`` mode, where ``credential_secret`` is ``None``… and where
        # there is no local password login to throttle in the first place. So the
        # honest answer is "off", not "on with a public key" (adversarial review
        # round 2, L3).
        return bool(str(self._secret or '').strip())

    def check(self, operation: object, body: object = None) -> Optional[RateLimitOutcome]:
        """Would this attempt exceed the account budget? Returns the denial, or ``None``.

        ⚠️ **Asks without charging.** The charge happens in :meth:`record_failure`,
        after the handler has produced a verdict. Charging here instead — the
        obvious design, and the one this wave shipped first — makes a *successful*
        login observable: an unauthenticated prober counts attempts-to-429 against
        a target and reads whether that account has been used, and ``Retry-After``
        tells them when. Adversarial review measured the channel twice, in both
        directions: charging successes made the count go **down** with recent
        activity; clearing the budget on success made it go **up**, at higher
        resolution. Only *not counting successes at all* closes it, and that
        requires knowing the verdict.

        Enforcement still happens **before** the expensive work — the caller denies
        on this answer, so a throttled attempt costs no bcrypt verify and no
        database round-trip.

        ``None`` covers three cases the caller need not tell apart: throttling is
        off, this operation has no account axis, or the attempt is within budget.

        ⚠️ Total function. Any ``operation`` / ``body`` is answerable.
        """
        charge = self._charge_for(operation, body)
        if charge is None:
            # Fail-closed: no account charge, but the middleware already charged
            # the peer tier, so this is a fallback to the source ceiling — never to
            # "no limit".
            return None
        outcome = self._limiter.peek(charge.key, charge.rule)
        return None if outcome.allowed else outcome

    def record_failure(self, operation: object, body: object = None) -> None:
        """Spend one slot of this account's budget. Call only on a **failed** attempt.

        The counter therefore means the same thing as the database lockout's
        ``failed_login_attempts``: failures only, nothing else. A successful login
        leaves no trace for a prober to read, and a tester who mistypes twice and
        then succeeds is not one step closer to a 429 on their next visit.

        ⚠️ Total function — an observation layer must not be able to fail a request
        that has already been answered.
        """
        charge = self._charge_for(operation, body)
        if charge is not None:
            self._limiter.check(charge.key, charge.rule)

    def _charge_for(self, operation: object, body: object):
        if not self.enabled:
            return None
        fields = CREDENTIAL_IDENTIFIER_FIELDS.get(str(operation), ())
        if not fields:
            return None
        identifier = extract_credential_identifier(body, fields)
        if identifier is None:
            return None
        return self._policy.account_charge(
            fingerprint_digest(self._secret, identifier),
        )
