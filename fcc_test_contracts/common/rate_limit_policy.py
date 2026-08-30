"""Inbound HTTP rate-limit policy — pure domain SSOT (2026-07-19).

The three web surfaces (Session / Headless / Platform) had **no** request
throttling of any kind: no 429 path, no per-principal budget, no gateway
``limit_req``. The most exposed surface is the worst case — ``/session/metrics``,
``/headless/metrics`` and ``/platform/metrics`` are *deliberately auth-exempt*
(Prometheus scrapers cannot carry an OIDC token), so anyone who can reach the
port could scrape them without bound, and every authenticated endpoint could be
hammered by a single principal until the central DB pool starved.

This module owns the **decision** half of the fix as a pure value object, the
same split the repository already uses for
:mod:`domain.services.outbox_retry_policy` (decision here / persistence in the
store) and :mod:`domain.services.analyzer_reset_policy` (predicates here /
env + clock in the application layer):

- :class:`RateLimitRule` — a fixed-window budget (how many requests, over how
  long a window) plus the two pure arithmetic answers a limiter needs:
  "is this request within budget?" and "how long until the window resets?".
- :class:`RateLimitPolicy` — which rule applies to a request path, plus the
  enable flag (kill-switch) and the ``from_raw`` env-string parser.
- :func:`resolve_client_key` / :func:`resolve_peer_key` — the *keying* decision:
  which identity a budget is charged to.
- :meth:`RateLimitPolicy.charges` — the **two-tier** decision that makes the
  keying safe (see below).

Why two tiers (the header-spoofing hole this closes)
----------------------------------------------------

Rate limiting must run *before* authentication — shedding an invalid-token flood
cheaply is the whole point — so at decision time the only identity available is
whatever the request *claims*. A single-tier limiter keyed on a claimed identity
is worthless: the attacker rotates ``X-FCC-Subject`` (or the bearer token) on
every request, mints a fresh bucket each time, and the budget never engages.
That is not a hypothetical — it is the trivial bypass of a naive implementation,
and it hits the auth-exempt ``/metrics`` endpoints hardest because the attacker
does not even need a plausible credential.

So every request is charged against TWO buckets and denied if *either* is over:

1. **peer tier** — keyed on the transport source address, which no header can
   change. This is the hard bound; it is ``PEER_BUDGET_MULTIPLIER`` times looser
   so shared-NAT operators never meet it first.
2. **identity tier** — keyed on the claimed identity (a *verified* trusted-header
   subject when the surface runs in ``trusted_headers`` mode, else the bearer
   token digest). Spoofable, and that is fine: its job is *fairness* between
   distinct callers behind one address, not containment. Containment is tier 1.

The caller decides what counts as verified: the middleware only passes a subject
when the auth config says that header is trusted, so an OIDC-mode surface keys
identity on the token digest alone.

Everything here is stdlib-only and side-effect free: no ``os`` access (the
application layer reads env and passes raw strings), no clock (the caller
passes ``now``), no counters (the limiter owns state). That keeps the whole
policy trivially unit-testable and keeps ``domain/`` purity — AST-sealed by
``TestDomainPurity``.

Why a **fixed window** and not a sliding log / token bucket:

- a fixed window is O(1) memory per key (two numbers) — a sliding log keeps a
  timestamp per request, which is itself a memory-amplification vector for the
  exact flood we are defending against;
- the worst case of a fixed window is a 2× burst across a window boundary,
  which is acceptable for an abuse brake (this is not a billing quota);
- it needs no background sweeper thread — expiry is implied by the stored
  window start, so an idle process costs nothing.

The residual 2×-boundary burst is documented in ``docs/security/threat-model.md``
rather than hidden.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Optional

from fcc_test_contracts.common.health_probe_policy import PROBE_PATH_SUFFIXES
from fcc_test_contracts.common.identity_budget_envelope import refresh_rotation_budget
from fcc_test_contracts.common.login_throttle_policy import LOCKOUT_MAX_ATTEMPTS


__all__ = [
    'ACCOUNT_KEY_PREFIX',
    'ANONYMOUS_CLIENT_HOST',
    'BUCKET_CREDENTIAL',
    'BUCKET_REFRESH',
    'BUCKET_DEFAULT',
    'BUCKET_KEY_SEPARATOR',
    'BUCKET_METRICS',
    'BUCKET_PROBE',
    'CREDENTIAL_ACCOUNT_MAX_ATTEMPTS',
    'REFRESH_KEY_PREFIX',
    'REFRESH_ROTATION_MAX_PER_WINDOW',
    'DEFAULT_MAX_REQUESTS',
    'DEFAULT_METRICS_MAX_REQUESTS',
    'DEFAULT_METRICS_WINDOW_SECONDS',
    'DEFAULT_PROBE_MAX_REQUESTS',
    'DEFAULT_PROBE_WINDOW_SECONDS',
    'DEFAULT_RATE_LIMIT_POLICY',
    'DEFAULT_WINDOW_SECONDS',
    'IP_KEY_PREFIX',
    'METRICS_PATH_SUFFIX',
    'MIN_RETRY_AFTER_SECONDS',
    'PRINCIPAL_KEY_PREFIX',
    'RATE_LIMIT_DETAIL',
    'TOKEN_KEY_DIGEST_CHARS',
    'TOKEN_KEY_PREFIX',
    'PEER_BUCKET_SUFFIX',
    'PEER_BUDGET_MULTIPLIER',
    'RateLimitCharge',
    'RateLimitPolicy',
    'RateLimitRule',
    'resolve_account_key',
    'resolve_client_key',
    'resolve_peer_key',
    'resolve_refresh_key',
    'scoped_key',
]


#: Default budget for a normal API caller: 120 requests per 60 s window.
#: Sized from the actual client, not from a round number — the SPA's heaviest
#: screen (progress dashboard) issues well under 20 requests per interaction and
#: React Query refetches on a 30 s cadence, so 2 req/s sustained leaves an order
#: of magnitude of headroom for a human operator while still capping a runaway
#: script at a rate the central Postgres pool absorbs.
DEFAULT_MAX_REQUESTS = 120

#: Window length (seconds) the budget above is measured over.
DEFAULT_WINDOW_SECONDS = 60.0

#: Budget for the auth-exempt ``/metrics`` endpoints. Prometheus scrapes on a
#: 15 s interval by default (4/min); 30/min tolerates several scrapers plus a
#: manual curl while making an unauthenticated scrape loop useless as an
#: amplification primitive.
DEFAULT_METRICS_MAX_REQUESTS = 30

#: Window length (seconds) for the ``/metrics`` budget.
DEFAULT_METRICS_WINDOW_SECONDS = 60.0

#: Budget for the auth-exempt liveness/readiness probes (2026-07-20).
#:
#: Probes MUST NOT be throttled into failure: an orchestrator reads a 429 as
#: "unhealthy" exactly like a 503, so a throttled liveness probe restarts a
#: perfectly healthy container — the throttle would manufacture the outage it
#: exists to prevent. The answer is a dedicated, deliberately generous budget
#: rather than a blanket exemption, because keying makes an exemption
#: unnecessary: every bucket is scoped to the *peer address*, and the compose /
#: k8s probe runs against the loopback (or the node) — an attacker flooding
#: ``/platform/health`` from another address exhausts only its OWN bucket and can
#: never consume the prober's. So the probe path keeps a real DoS bound while the
#: real prober is unreachable from that flood.
#:
#: 240/min = 4 req/s. The compose probe polls at 15 s (4/min) and a k8s
#: liveness+readiness pair at 10 s adds 12/min, so this leaves ~15x headroom for
#: extra pollers, retry storms and manual curls before the budget engages.
#: Deliberately NOT env-tunable: a knob here would let a deployment quietly set
#: the probe budget low enough to reintroduce probe-induced restarts.
DEFAULT_PROBE_MAX_REQUESTS = 240

#: Window length (seconds) for the probe budget.
DEFAULT_PROBE_WINDOW_SECONDS = 60.0

#: Path suffix that selects the metrics budget. All three surfaces expose their
#: scrape endpoint as ``/{surface}/metrics``; matching on the suffix keeps this
#: policy free of per-surface path literals.
METRICS_PATH_SUFFIX = '/metrics'

#: ``Retry-After`` is expressed in whole seconds (RFC 9110 §10.2.3) and a value
#: of 0 would invite an immediate retry, so the hint is floored at 1.
MIN_RETRY_AFTER_SECONDS = 1

#: Key namespaces. The prefix keeps the three identity kinds from colliding
#: (an IP literal can never be mistaken for a subject) and makes a limiter dump
#: readable during incident response.
PRINCIPAL_KEY_PREFIX = 'sub:'
TOKEN_KEY_PREFIX = 'tok:'
IP_KEY_PREFIX = 'ip:'

#: Namespace of the *account* tier (2026-08-22). One prefix per identity kind
#: keeps an incident dump readable — an account digest and a trusted-header subject
#: are different things and should not read alike.
#:
#: ⚠️ It is a **legibility** convention, not a safety mechanism, and an earlier
#: draft of this comment overstated it. Collisions are already impossible twice
#: over: :func:`scoped_key` prepends the bucket name (``credential|acct:…`` versus
#: ``default|sub:…``), and since 2026-08-22 the account tier does not even share a
#: limiter with the others. Adversarial review demonstrated the overstatement by
#: setting this prefix to ``'sub:'`` and finding nothing broke.
#:
#: ⚠️ What follows this prefix is an HMAC digest, never the identifier. The value
#: reaches a limiter key and can reach a diagnostic dump; a plaintext e-mail there
#: would turn the defence into a disclosure.
ACCOUNT_KEY_PREFIX = 'acct:'

#: Number of hex characters of the bearer-token SHA-256 digest used as a key.
#: The raw token is NEVER stored or logged — 64 bits of digest is far beyond
#: what is needed to separate callers, and is one-way.
TOKEN_KEY_DIGEST_CHARS = 16

#: Bucket names. A caller's ``/metrics`` traffic and its regular API traffic are
#: governed by different rules, so they must not share one counter — the bucket
#: name is folded into the limiter key (see :func:`scoped_key`).
BUCKET_DEFAULT = 'default'
BUCKET_METRICS = 'metrics'
#: Probe traffic is high-frequency and unauthenticated; sharing a counter with
#: either of the others would let a scrape flood throttle the liveness probe.
BUCKET_PROBE = 'probe'
#: Credential-verification traffic (2026-08-22). A separate bucket because its
#: budget is two orders of magnitude tighter than the default: sharing a counter
#: would let ordinary API traffic consume the login allowance, and — far worse —
#: let login attempts consume the operator's working budget.
BUCKET_CREDENTIAL = 'credential'
#: Refresh-rotation traffic (2026-08-23). A separate bucket for the same reason the
#: credential tier has one: its budget answers a different question (*how many
#: sessions may one tester rotate at once*), and sharing a counter would let
#: ordinary API traffic consume the allowance that keeps a tester signed in.
BUCKET_REFRESH = 'refresh'

#: Separator between bucket and client key. A character that cannot appear in a
#: bucket name, so ``bucket|client`` is unambiguous.
BUCKET_KEY_SEPARATOR = '|'

#: Suffix that names the peer-address tier of a bucket. Every request is charged
#: to BOTH an identity bucket and a peer bucket (see :meth:`RateLimitPolicy.charges`),
#: and the two must not share a counter.
PEER_BUCKET_SUFFIX = ':peer'

#: How much larger the peer-address budget is than the per-identity budget.
#: The peer tier is the *unspoofable* bound (an attacker can rotate any header,
#: but not the TCP source address), so it must be loose enough that a shared
#: office NAT of legitimate operators never meets it first, while still capping
#: the total a single source can extract. 10x the per-identity budget means a
#: NAT would need ~10 operators saturating their personal budgets simultaneously
#: before the peer tier engages.
PEER_BUDGET_MULTIPLIER = 10

#: Per-*account* budget on a credential path, per :data:`DEFAULT_WINDOW_SECONDS`.
#:
#: ⚠️ **The ``+ 1`` is the whole constant.** If the account budget were
#: ``LOCKOUT_MAX_ATTEMPTS`` or less, the very attempt that trips the database
#: lockout would be cut off with a 429 first — the lock would become structurally
#: unreachable and the whole ``RECORD_FAILED_LOGIN_SQL`` path would be dead code
#: that every test still passes. One slot of headroom is what keeps the two layers
#: separate. EMS derives its account budget with the identical expression, for the
#: identical reason (``CREDENTIAL_ACCOUNT_BUDGET`` in ``throttle-policy.ts``).
#:
#: The two layers are not redundant: the lockout counts **failures only** for a
#: *resolved* account, resets on success and lasts 15 minutes; this throttle counts
#: **every attempted identifier string** (non-existent ones included) regardless of
#: outcome and lasts one window. The asymmetric layer has to sit *below* the
#: symmetric one, because a throttle cannot know the handler's verdict.
CREDENTIAL_ACCOUNT_MAX_ATTEMPTS = LOCKOUT_MAX_ATTEMPTS + 1

#: Namespace of the *refresh-rotation* tier. What follows is an HMAC digest of the
#: verified ``sub`` — never the identifier (the value reaches a limiter key and can
#: reach a diagnostic dump).
REFRESH_KEY_PREFIX = 'rot:'

#: Per-**subject** refresh rotations per :data:`DEFAULT_WINDOW_SECONDS`.
#:
#: ⚠️ **Derived, not chosen.** The population fact (*how many sessions one tester
#: runs at once*) lives in :mod:`domain.services.identity_budget_envelope`, and a
#: future *source* ceiling must come from the same fact — ADR-0021 ``R-10`` records
#: what it costs when two waves each invent their own envelope for one population.
#: Writing the number here instead would be exactly that second invention.
#:
#: ⚠️ **Until this landed the ceiling on this path was infinite** (measured: 380
#: rotations/second through a ``public`` route with no bcrypt). So the direction is
#: only ever *narrowing from unbounded*; the envelope module explains why the value
#: is generous and makes that generosity measurable rather than asserted.
#:
#: Deliberately NOT exposed to ``from_raw``, for the same reason as ``probe_rule``
#: and ``credential_rule``: an env knob here lets a deployment quietly restore the
#: unbounded state, and the symptom of that is nothing at all.
REFRESH_ROTATION_MAX_PER_WINDOW = refresh_rotation_budget()


#: Used when the ASGI server cannot report a peer address (e.g. a unix socket
#: transport). All such callers share one bucket, which is the conservative
#: direction: unknown peers cannot get an unlimited private budget each.
ANONYMOUS_CLIENT_HOST = 'unknown'

#: RFC 9457 ``detail`` for a throttled request. Deliberately says nothing about
#: the caller's own budget state beyond the header hint — an attacker should not
#: be able to map limits precisely from the body.
RATE_LIMIT_DETAIL = 'Too many requests. Retry after the interval in the Retry-After header.'


def _coerce_positive_int(raw: object, default: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _coerce_positive_float(raw: object, default: float) -> float:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _coerce_bool(raw: object, default: bool) -> bool:
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if not text:
        return default
    if text in {'1', 'true', 'yes', 'on'}:
        return True
    if text in {'0', 'false', 'no', 'off'}:
        return False
    return default


@dataclass(frozen=True)
class RateLimitRule:
    """A fixed-window request budget.

    ``max_requests`` requests are permitted per ``window_seconds``. Both
    predicates take the caller's already-observed window state, so the rule
    holds no counters and is safe to share across threads.
    """

    max_requests: int = DEFAULT_MAX_REQUESTS
    window_seconds: float = DEFAULT_WINDOW_SECONDS
    bucket: str = BUCKET_DEFAULT

    def __post_init__(self) -> None:
        # Fail loud rather than silently producing a rule that admits
        # everything (max<=0 would either block all traffic or, if read as
        # "unlimited", quietly disable the protection this module exists for).
        if self.max_requests <= 0:
            raise ValueError('max_requests must be positive')
        if self.window_seconds <= 0:
            raise ValueError('window_seconds must be positive')

    def is_allowed(self, *, count_in_window: int) -> bool:
        """True when a request that would make the count ``count_in_window`` fits.

        ``count_in_window`` is the post-increment count (1 for the first request
        of a window), mirroring ``OutboxRetryPolicy.is_exhausted``'s
        post-increment convention.
        """
        return int(count_in_window) <= self.max_requests

    def retry_after_seconds(self, *, window_start: float, now: float) -> int:
        """Whole seconds until the current window resets (floored at 1)."""
        remaining = (float(window_start) + self.window_seconds) - float(now)
        return max(MIN_RETRY_AFTER_SECONDS, int(math.ceil(remaining)))

    def is_window_expired(self, *, window_start: float, now: float) -> bool:
        """True when ``now`` has moved past the window that began at ``window_start``."""
        return (float(now) - float(window_start)) >= self.window_seconds


@dataclass(frozen=True)
class RateLimitCharge:
    """One (bucket key, rule) pair a request must be charged against."""

    key: str
    rule: RateLimitRule


@dataclass(frozen=True)
class RateLimitPolicy:
    """Which budget applies to a request, plus the kill-switch.

    ``enabled=False`` is the documented kill-switch: the middleware becomes a
    pass-through and behaviour is byte-identical to the pre-2026-07-19 surfaces.
    """

    enabled: bool = True
    default_rule: RateLimitRule = RateLimitRule()
    metrics_rule: RateLimitRule = RateLimitRule(
        max_requests=DEFAULT_METRICS_MAX_REQUESTS,
        window_seconds=DEFAULT_METRICS_WINDOW_SECONDS,
        bucket=BUCKET_METRICS,
    )
    #: Liveness/readiness budget (2026-07-20). Not exposed to ``from_raw`` — see
    #: ``DEFAULT_PROBE_MAX_REQUESTS`` for why it is deliberately not tunable.
    probe_rule: RateLimitRule = RateLimitRule(
        max_requests=DEFAULT_PROBE_MAX_REQUESTS,
        window_seconds=DEFAULT_PROBE_WINDOW_SECONDS,
        bucket=BUCKET_PROBE,
    )
    #: Per-account budget for a credential attempt (2026-08-22). Charged by the
    #: route boundary, which is the first place the attempted identifier exists —
    #: the middleware sees only headers and a path.
    #:
    #: ⚠️ **This tier is purely additive: no existing budget was tightened, and
    #: that restraint was measured, not assumed.** A first draft of this wave also
    #: gave credential paths their own *source* ceiling (60/min in place of the
    #: inherited 1200/min). Adversarial review reproduced the result end to end:
    #: 30 testers logging in from one origin produced 60×200 and 30×429, i.e. the
    #: 2026-08-11 EMS outage in the opposite direction. The reason is that on this
    #: deployment "per source" does not mean "per tester" — uvicorn's
    #: ``forwarded_allow_ips`` defaults to ``127.0.0.1`` while nginx proxies from a
    #: different container address, so ``resolve_peer_key`` collapses the whole
    #: deployment into ONE bucket (the pre-existing docstring on
    #: :func:`resolve_peer_key` already says this in general terms).
    #:
    #: ⚠️ **The first of those two prerequisites landed on 2026-08-22**
    #: (``peer-axis-trusted-hop``): the shipped compose now names the reverse
    #: proxy's static address in ``FORWARDED_ALLOW_IPS``, so a deployment that
    #: uses it charges the peer tier per source. That does **not** license
    #: re-deriving a source ceiling from this constant — the second prerequisite
    #: (a measured concurrent-tester envelope) is still missing, and the axis
    #: argument below is unchanged: this budget answers "how fast may one
    #: password be guessed", not "how many people sign in at 9am".
    #:
    #: A deployment-wide ceiling must be sized from a deployment-wide capacity
    #: figure, and this repository does not own one. Tightening it therefore needs
    #: two things this wave does not have — the real peer address restored at the
    #: server, and a measured concurrent-tester envelope — and both are ledger
    #: items. **Do not re-derive a source ceiling from this constant**: the account
    #: budget answers "how fast may one password be guessed", not "how many people
    #: sign in at 9am", and coupling them makes a security knob move a capacity
    #: limit (EMS recorded the same mistake as its own F3).
    #:
    #: Deliberately NOT exposed to ``from_raw``, for the same reason as
    #: ``probe_rule``: an env knob here lets a deployment quietly widen the one
    #: budget that stands between a password and an offline-speed guessing loop.
    credential_rule: RateLimitRule = RateLimitRule(
        max_requests=CREDENTIAL_ACCOUNT_MAX_ATTEMPTS,
        window_seconds=DEFAULT_WINDOW_SECONDS,
        bucket=BUCKET_CREDENTIAL,
    )
    #: Per-subject refresh-rotation budget (2026-08-23). Charged by the auth
    #: service **after** the refresh token has been verified — the first point at
    #: which the subject is a fact rather than a claim.
    #:
    #: ⚠️ **This is the tier that could not exist before.** The sibling system keys
    #: authenticated traffic on its verified user id inside a guard that runs
    #: before the throttle; FCC's throttle middleware runs *before* JWT validation
    #: on purpose (shedding an invalid-token flood cheaply is its whole job), so
    #: copying that shape would re-open header-rotation bypass. The answer is not
    #: to move the middleware but to add a charging point where the identity is
    #: already verified — the same split ``account_charge`` already uses.
    refresh_rule: RateLimitRule = RateLimitRule(
        max_requests=REFRESH_ROTATION_MAX_PER_WINDOW,
        window_seconds=DEFAULT_WINDOW_SECONDS,
        bucket=BUCKET_REFRESH,
    )

    def __post_init__(self) -> None:
        # Two rules that share a bucket name would share one counter, silently
        # merging one budget into another (a caller's scrapes would consume its
        # API allowance; a scrape flood would consume the liveness probe's).
        # Fail loud instead — the bucket is what makes the budgets independent.
        buckets = (
            self.default_rule.bucket,
            self.metrics_rule.bucket,
            self.probe_rule.bucket,
            self.credential_rule.bucket,
            self.refresh_rule.bucket,
        )
        if len(set(buckets)) != len(buckets):
            raise ValueError(
                'default_rule, metrics_rule, probe_rule, credential_rule and '
                f'refresh_rule must use distinct buckets (got {buckets!r}) — '
                'otherwise two budgets share one counter.'
            )
        # The account tier is worthless if it denies before the database lockout
        # can trip: the lock would be unreachable code and the only surviving
        # defence would be a counter that resets every window. Enforced on the
        # constructed value, not just on the module default, because a caller may
        # build its own policy.
        if self.credential_rule.max_requests <= LOCKOUT_MAX_ATTEMPTS:
            raise ValueError(
                f'credential_rule.max_requests ({self.credential_rule.max_requests}) '
                f'must exceed LOCKOUT_MAX_ATTEMPTS ({LOCKOUT_MAX_ATTEMPTS}) — '
                'otherwise the attempt that trips the account lockout is throttled '
                'first and the lockout becomes structurally unreachable.'
            )

    def peer_rule_for(self, path: str) -> RateLimitRule:
        """The unspoofable peer-address budget governing ``path``.

        Derived from the same rule as the identity tier (one source of truth for
        the window length) and widened by :data:`PEER_BUDGET_MULTIPLIER`.

        """
        rule = self.rule_for(path)
        return RateLimitRule(
            max_requests=rule.max_requests * PEER_BUDGET_MULTIPLIER,
            window_seconds=rule.window_seconds,
            bucket=f'{rule.bucket}{PEER_BUCKET_SUFFIX}',
        )

    def peer_key_for(self, client_host: Optional[str] = None) -> str:
        """The peer-tier identity this request will be charged to, **unscoped**.

        ⚠️ **Why this accessor exists rather than a second call to**
        :func:`resolve_peer_key`. The peer-axis observation
        (:mod:`application.common.peer_axis_observer`) must count *the same
        identity the limiter charges* — if it derived its own, the two could
        drift and the gauge would answer about a source axis nobody enforces.
        Routing it through the policy keeps one owner, and a behavioural seal
        asserts the observed value equals the peer component of the charged key.

        ⚠️ **Unscoped on purpose.** :func:`scoped_key` folds the *bucket* into the
        key, and the bucket varies by path (``default`` / ``metrics`` / ``probe``).
        Counting scoped keys would report one caller hitting three paths as three
        distinct sources — i.e. it would manufacture exactly the diversity the
        observation exists to detect the absence of.
        """
        return resolve_peer_key(client_host)

    def charges(
        self,
        path: str,
        *,
        verified_subject: Optional[str] = None,
        authorization: Optional[str] = None,
        client_host: Optional[str] = None,
    ) -> tuple['RateLimitCharge', ...]:
        """Every bucket this request must fit into, most-specific last.

        Always includes the peer tier, so no combination of request headers can
        mint an unbounded number of buckets. Adds the identity tier only when the
        request carries an identity claim the caller told us to honour
        (``verified_subject``) or a bearer token — an anonymous request is fully
        governed by the peer tier alone.

        ⚠️ The **account tier is deliberately not here** — see
        :meth:`account_charge`.
        """
        rule = self.rule_for(path)
        peer_rule = self.peer_rule_for(path)
        charges = [
            RateLimitCharge(
                # ⚠️ Goes through :meth:`peer_key_for`, not straight to
                # ``resolve_peer_key``, so the observation axis and the charged
                # key are the SAME derivation rather than two that agree today.
                key=scoped_key(peer_rule, self.peer_key_for(client_host)),
                rule=peer_rule,
            )
        ]
        identity = resolve_client_key(
            subject=verified_subject, authorization=authorization,
        )
        if identity is not None:
            charges.append(RateLimitCharge(key=scoped_key(rule, identity), rule=rule))
        return tuple(charges)

    def account_charge(
        self, account_digest: Optional[str] = None,
    ) -> Optional['RateLimitCharge']:
        """The **account tier** for a credential attempt, or ``None``.

        ⚠️ **Why this is not folded into** :meth:`charges`. The two tiers are
        charged at different points in the request lifecycle — the peer/identity
        tiers by the pre-auth middleware (headers and path are all it can see) and
        this one by the route boundary (the first place the attempted identifier
        exists, because it is in the request body). If :meth:`charges` also
        returned the account tier, the route would have to call it a second time
        and would **re-charge the peer tier**, silently halving the source ceiling
        that method exists to enforce. One tier, one charging point.

        ``None`` means the caller could not determine which account is being
        attempted. That is not an open door: the peer tier was already charged by
        the middleware, so an unreadable body falls back to the source ceiling.

        ⚠️ ``account_digest`` is already one-way. This pure policy never sees the
        identifier and never holds the HMAC secret.
        """
        account = resolve_account_key(account_digest)
        if account is None:
            return None
        return RateLimitCharge(
            key=scoped_key(self.credential_rule, account),
            rule=self.credential_rule,
        )

    def refresh_charge(
        self, subject_digest: Optional[str] = None,
    ) -> Optional['RateLimitCharge']:
        """The **refresh-rotation tier** for one rotation, or ``None``.

        ⚠️ **Charged after verification, and that is the security property.** The
        subject only exists once the refresh token's signature, type and
        ``session_version`` have been checked; charging on a *claimed* subject
        would let anyone exhaust a victim's rotation budget and sign them out by
        presenting garbage tokens that name them.

        ⚠️ **Not folded into** :meth:`charges` — for the same reason
        :meth:`account_charge` is not: that method is called by the pre-auth
        middleware, and a second call from the service would **re-charge the peer
        tier**, silently halving the source ceiling. One tier, one charging point.

        ⚠️ ``subject_digest`` is already one-way. This pure policy never sees the
        identifier and never holds the HMAC secret.
        """
        key = resolve_refresh_key(subject_digest)
        if key is None:
            return None
        return RateLimitCharge(
            key=scoped_key(self.refresh_rule, key),
            rule=self.refresh_rule,
        )

    def is_caller_traffic(self, path: str) -> bool:
        """Is a request to ``path`` something a *tester* did?

        ⚠️ **The peer-axis observation must not count the deployment's own
        traffic** (adversarial review, 2026-08-23). Two infrastructure sources
        exist and neither is a caller: the container healthcheck, which probes
        the API on loopback every 15 s **bypassing the reverse proxy**, and the
        operator's own ``/metrics`` scrape — which is the very command the runbook
        tells them to run, so *asking the question changed the answer*.

        The two exclusions are the two buckets that already exist for exactly
        those two kinds of traffic, so this predicate invents no path vocabulary:
        a probe path is what ``health_probe_policy`` says it is, and a metrics
        path is what :data:`METRICS_PATH_SUFFIX` says it is. Adding a probe there
        automatically removes it from the observation too.

        ⚠️ The credential bucket is deliberately **not** excluded: signing in is
        the most tester-ish thing there is. It is also charged at the route, so
        ``rule_for`` never returns it here.
        """
        return self.rule_for(path).bucket == self.default_rule.bucket

    def rule_for(self, path: str) -> RateLimitRule:
        """Return the rule governing ``path``.

        The auth-exempt scrape endpoints (``/session/metrics``,
        ``/headless/metrics``, ``/platform/metrics``) get the dedicated metrics
        budget; the auth-exempt liveness/readiness probes (``/session/health``,
        ``/platform/health``, ``/platform/ready``) get the probe budget;
        everything else gets the default budget. Matching is on the suffix so no
        surface-specific literal lives here, and a trailing slash cannot be used
        to escape a rule.
        """
        normalized = str(path or '').split('?', 1)[0].rstrip('/')
        if normalized.endswith(METRICS_PATH_SUFFIX):
            return self.metrics_rule
        # Probe suffixes come from the health-probe policy SSOT, so adding a
        # probe path there cannot leave the throttle governing it with the
        # ordinary API budget.
        if any(normalized.endswith(suffix) for suffix in PROBE_PATH_SUFFIXES):
            return self.probe_rule
        return self.default_rule

    @classmethod
    def from_raw(
        cls,
        *,
        enabled: object = None,
        max_requests: object = None,
        window_seconds: object = None,
        metrics_max_requests: object = None,
        metrics_window_seconds: object = None,
        default_enabled: bool = True,
    ) -> 'RateLimitPolicy':
        """Build a policy from raw (env-string / ``None``) values.

        Pure — never reads ``os``. ``None`` / garbage / non-positive falls back
        to the SSOT default for that field, so a half-configured deployment
        never ends up with a zero-budget (all traffic blocked) or an
        accidentally-unlimited policy. ``default_enabled`` lets a caller choose
        the meaning of "unset" (composition roots pass ``True`` = secure by
        default; a programmatic embedder can pass ``False``).
        """
        return cls(
            enabled=_coerce_bool(enabled, default_enabled),
            default_rule=RateLimitRule(
                max_requests=_coerce_positive_int(max_requests, DEFAULT_MAX_REQUESTS),
                window_seconds=_coerce_positive_float(
                    window_seconds, DEFAULT_WINDOW_SECONDS
                ),
            ),
            metrics_rule=RateLimitRule(
                max_requests=_coerce_positive_int(
                    metrics_max_requests, DEFAULT_METRICS_MAX_REQUESTS
                ),
                window_seconds=_coerce_positive_float(
                    metrics_window_seconds, DEFAULT_METRICS_WINDOW_SECONDS
                ),
                bucket=BUCKET_METRICS,
            ),
        )


def scoped_key(rule: RateLimitRule, client_key: str) -> str:
    """Compose the limiter key for ``client_key`` under ``rule``'s bucket.

    Formed here (not in the middleware) so every part of the key — namespace
    prefixes, bucket, separator — has exactly one owner.
    """
    return f'{rule.bucket}{BUCKET_KEY_SEPARATOR}{client_key}'


def resolve_client_key(
    *,
    subject: Optional[str] = None,
    authorization: Optional[str] = None,
) -> Optional[str]:
    """Return the *identity-tier* bucket key, or ``None`` when there is no claim.

    Precedence — most specific first:

    1. ``subject`` — a trusted-header principal the caller has already decided to
       honour (the middleware passes it only when the surface runs in
       ``trusted_headers`` mode; in any other mode the header carries no weight,
       exactly as :mod:`application.common.principal_resolver` treats it).
    2. ``authorization`` — a bearer token. Throttling runs before JWT validation,
       so the token is NOT trusted; hashing it merely gives a stable per-caller
       bucket without ever holding the secret and without paying JWKS
       verification for traffic we may be about to drop. A rotating-garbage
       token still cannot escape the peer tier.

    ``None`` means "no identity claim" — the request is governed by the peer
    tier alone (this is the normal case for the auth-exempt scrapers).
    """
    subject_text = str(subject or '').strip()
    if subject_text:
        return f'{PRINCIPAL_KEY_PREFIX}{subject_text}'

    auth_text = str(authorization or '').strip()
    if auth_text:
        digest = hashlib.sha256(auth_text.encode('utf-8')).hexdigest()
        return f'{TOKEN_KEY_PREFIX}{digest[:TOKEN_KEY_DIGEST_CHARS]}'

    return None


def resolve_account_key(account_digest: Optional[str] = None) -> Optional[str]:
    """Return the *account-tier* bucket key, or ``None`` when there is no account.

    ``None`` means the caller could not determine which account is being
    attempted. That is **not** an open door: the peer tier is charged regardless
    (see :meth:`RateLimitPolicy.charges`), so an unreadable body falls back to the
    source ceiling rather than to no limit at all.

    ⚠️ The argument is already a digest. This function deliberately cannot hash —
    keeping the HMAC secret out of the pure policy means no code path here can be
    made to emit a value derived from it, and the digest function already has one
    owner in ``login_throttle_policy.fingerprint_digest``.
    """
    digest = str(account_digest or '').strip()
    if not digest:
        return None
    return f'{ACCOUNT_KEY_PREFIX}{digest}'


def resolve_refresh_key(subject_digest: Optional[str] = None) -> Optional[str]:
    """Return the *refresh-rotation* bucket key, or ``None`` when there is none.

    ``None`` means the caller could not resolve a verified subject. That is not an
    open door: the peer tier was already charged by the middleware, so an
    unresolvable rotation falls back to the source ceiling rather than to no limit.

    ⚠️ The argument is already a digest — this function deliberately cannot hash,
    so no code path here can be made to emit a value derived from the signing
    secret. The digest function has one owner in
    ``login_throttle_policy.fingerprint_digest``.
    """
    digest = str(subject_digest or '').strip()
    if not digest:
        return None
    return f'{REFRESH_KEY_PREFIX}{digest}'


def resolve_peer_key(client_host: Optional[str] = None) -> str:
    """Return the *peer-tier* bucket key for a transport source address.

    ``client_host`` is the ASGI transport source — i.e. **already** whatever the
    trusted-hop resolution at the server boundary decided. This function still
    does not read ``X-Forwarded-For``, and that is the point: the header is
    attacker-settable, so the decision of how far to believe it must have exactly
    one owner. That owner is uvicorn's ``ProxyHeadersMiddleware``, gated by
    ``FORWARDED_ALLOW_IPS`` and policed by
    :mod:`domain.services.proxy_trust_policy` at boot. A second reader here would
    become the loosest of the two, which is the same as being the only one.

    ⚠️ **What this key means is a deployment property, not a code property.**

    * trusted hop configured → the address is the real caller's, and the peer
      budget is charged *per source*;
    * not configured, behind a reverse proxy → every caller presents the proxy's
      one address and the budget is charged *per deployment*.

    The second state is not a bug in this function, but it is the reason a source
    ceiling must not be tightened on inspection alone: ADR-0021 ``D-11`` records a
    tightening that was withdrawn before landing because 30 testers with correct
    passwords reproduced a shared-bucket outage. ``proxy_trust_policy.peer_axis_mode``
    answers which state a deployment is in, and boot logs it — so the question is
    observable rather than assumed.

    The gateway ``limit_req`` in ``infra/central/nginx.conf`` remains a second,
    independent layer that always sees real peers (different blind spots by design).
    """
    host_text = str(client_host or '').strip() or ANONYMOUS_CLIENT_HOST
    return f'{IP_KEY_PREFIX}{host_text}'


#: SSOT singleton — the enabled default policy. Composition roots start from
#: this (env overrides individual fields); ``None`` at the app factory means
#: "no rate limiting at all", which is the byte-identical legacy path.
DEFAULT_RATE_LIMIT_POLICY = RateLimitPolicy()
