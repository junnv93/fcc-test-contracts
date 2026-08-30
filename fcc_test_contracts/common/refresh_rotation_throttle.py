"""Refresh-rotation throttle — the *charging* half of the subject tier (2026-08-23).

:mod:`domain.services.rate_limit_policy` owns the budget and the key shape,
:mod:`domain.services.identity_budget_envelope` owns the population fact the budget
derives from, and :mod:`application.common.rate_limit` owns the counters. This
module owns the one thing none of them can: turning *"a refresh token just
verified as belonging to this subject"* into a charge against the right bucket.

Why this tier could not exist before
------------------------------------

``POST /platform/auth/refresh`` is ``public`` (it must be — requiring an access
token would make refresh useless the moment the access token expires) and it pays
no bcrypt, so it was the cheapest authenticated-effect endpoint in the deployment:
**380 rotations/second, measured**. The revocation-custody wave closed the
*effect* of that flood (one custodian could no longer evict another's entries) but
not the flood itself.

The sibling system keys authenticated traffic on ``req.user.userId``, and that is
right **there** because its guard runs before its throttler. Copying it here would
be a security regression: FCC's throttle middleware runs **before** JWT validation
on purpose — shedding an invalid-token flood cheaply is its entire job — so a tier
keyed on a *claimed* subject at that point is trivially rotated (threat model
A-19). The answer is not to move the middleware; it is to add a charging point
where the identity is already a fact.

That point exists and has a precedent: the credential account tier is charged by
the route boundary, "the first place the attempted identifier exists". For a
rotation the first such place is *inside* the auth service, after the signature,
the token type and ``session_version`` have all been checked.

Why this one charges directly instead of peek-then-charge
---------------------------------------------------------

:class:`application.common.credential_throttle.CredentialThrottle` deliberately
splits ``check`` (peek) from ``record_failure`` (charge), because charging a
*successful* login turns attempts-to-429 into an oracle for whether an account
exists and when it last authenticated.

⚠️ **That oracle does not exist here, and the split would be harmful.** To reach
this charging point a caller must already hold a *valid, unrevoked, current-
version* refresh token for that subject — i.e. they are that subject. There is
nothing left to disclose. And the thing being bounded IS the successful rotation,
so a tier that only counted failures would count nothing at all.
"""
from __future__ import annotations

from typing import Optional

from fcc_test_contracts.common.rate_limit import FixedWindowRateLimiter, RateLimitOutcome
from fcc_test_contracts.common.login_throttle_policy import fingerprint_digest
from fcc_test_contracts.common.rate_limit_policy import RateLimitPolicy


__all__ = ['RefreshRotationThrottle']


class RefreshRotationThrottle:
    """Charges the refresh-rotation tier for one verified subject.

    ⚠️ **Takes its own limiter, and must not be handed the middleware's.** The
    limiter caps tracked keys and evicts least-recently-seen, and the middleware
    mints one key per presented ``Authorization`` header — so a shared pool lets
    an unauthenticated attacker churn junk bearers until a victim's rotation
    bucket is evicted and their spent budget is reset to full. Eviction "only
    forgives", which is harmless for a fairness limiter and is the whole attack
    against a security budget. The credential tier reached this conclusion first,
    the hard way; this tier inherits it rather than rediscovering it.
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
        # ⚠️ The local JWT signing secret, for the same reason the spraying
        # detector and the credential throttle use it: digests must survive a
        # restart (a fresh random salt hands every deploy a clean budget) and it
        # is the one value this process holds that an attacker does not. Nothing
        # derived from it is ever emitted — only bucket keys, already digests.
        self._secret = secret

    @property
    def enabled(self) -> bool:
        """Whether this throttle charges anything.

        Mirrors the middleware kill-switch exactly (``None`` policy or
        ``enabled=False`` means the deployment turned throttling off, and this
        tier must not be the one that ignores that), plus the same
        absent-secret rule the credential tier uses: ``fingerprint_digest`` does
        ``str(secret or '')``, so an absent secret would silently produce an
        **unkeyed** HMAC anyone can recompute. The honest answer there is "off",
        not "on with a public key".
        """
        if self._policy is None or not self._policy.enabled:
            return False
        return bool(str(self._secret or '').strip())

    def charge(self, subject: object) -> Optional[RateLimitOutcome]:
        """Spend one rotation slot for ``subject``; return the denial, or ``None``.

        ``None`` covers three cases the caller need not tell apart: throttling is
        off, the subject could not be resolved, or the rotation is within budget.

        ⚠️ **Total function.** This runs inside the refresh path, which already
        holds a claimed revocation entry; a raise here would turn a legitimate
        rotation into a 500 *and* strand that entry. Any ``subject`` is answerable.
        """
        charge = self._charge_for(subject)
        if charge is None:
            # Fail-closed: no subject charge, but the middleware already charged
            # the peer tier, so this is a fallback to the source ceiling — never
            # to "no limit".
            return None
        outcome = self._limiter.check(charge.key, charge.rule)
        return None if outcome.allowed else outcome

    def _charge_for(self, subject: object):
        if not self.enabled:
            return None
        text = str(subject or '').strip()
        if not text:
            return None
        return self._policy.refresh_charge(fingerprint_digest(self._secret, text))
