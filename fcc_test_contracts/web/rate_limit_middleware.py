"""Inbound rate-limit middleware for the three web surfaces (2026-07-19).

Wiring layer only. The budget lives in the pure policy
(:mod:`domain.services.rate_limit_policy`), the counters live in the shared
limiter (:mod:`application.common.rate_limit`); this module does the two things
that require knowing about HTTP:

1. pull the keying inputs off the request (configured subject header, bearer
   token, peer address) and pick the rule from the request path;
2. render a denial as the repository's existing RFC 9457 problem body —
   ``ErrorCode.RATE_LIMITED`` → 429 via the ``ERROR_CODE_STATUS`` SSOT — plus the
   standard ``Retry-After`` header (RFC 9110 §10.2.3).

Why a direct ``JSONResponse`` instead of raising ``HTTPException`` and letting
``install_problem_details_handler`` render it: exceptions raised inside a
Starlette ``BaseHTTPMiddleware`` do not pass through the app's
``HTTPException`` handler chain, and the Session surface does not install that
handler at all. Building the response here makes the 429 body identical on all
three surfaces regardless of their handler wiring — and it still consumes the
same ``ProblemDetails`` value object, so there is no second error format.

**This module imports no web framework.** The JSON response constructor is a
required parameter, supplied by the three ``create_*_app`` factories — the
composition edge that already resolves FastAPI inside a guarded ``try``. That is
what lets the dependency-free contracts lane own it (2026-08-15,
platform-provider-crossing-closure), which is the honest home for a module all
three surfaces read: provider ownership forced the platform route boundary
across the lane boundary, and platform ownership would only have reversed the
crossing. See ``problem_response`` for the measurement that rejected the third
option (declaring ``fastapi`` an optional extra of the contracts lane).

Registration order: this middleware is installed **first**, i.e. innermost.
Starlette runs the last-registered middleware outermost, so registering the
throttle first means a 429 still flows back out through the correlation
middleware (``X-Request-Id`` / ``traceparent`` echoed) and the metrics
middleware (the throttle itself is observable as ``client_error`` latency).
Protection is unaffected — the route handler is never reached either way, and
the two middlewares it sits inside cost microseconds.
"""
from __future__ import annotations

from typing import Optional

from fcc_test_contracts.common.api_error_codes import (
    ERROR_CODE_TITLES,
    PROBLEM_JSON_MEDIA_TYPE,
    ErrorCode,
    ProblemDetails,
    status_for_code,
)
from fcc_test_contracts.common.auth_config import HttpAuthConfig
from fcc_test_contracts.common.rate_limit import FixedWindowRateLimiter
from fcc_test_contracts.common.peer_axis_observation import (
    arrived_through_trusted_hop,
)
from fcc_test_contracts.common.rate_limit_policy import (
    RATE_LIMIT_DETAIL,
    RateLimitPolicy,
)


__all__ = [
    'AUTHORIZATION_HEADER',
    'RATE_LIMIT_LIMIT_HEADER',
    'RATE_LIMIT_REMAINING_HEADER',
    'RETRY_AFTER_HEADER',
    'create_rate_limit_middleware',
    'install_rate_limit_middleware',
]


#: RFC 9110 §10.2.3 — the standard "come back later" hint, in whole seconds.
RETRY_AFTER_HEADER = 'Retry-After'

#: IETF ``draft-ietf-httpapi-ratelimit-headers`` field names. Emitted only on a
#: denial: a client that is being throttled needs to know the shape of the
#: budget, while advertising it on every 200 would hand an attacker a precise
#: map of the limits for free.
RATE_LIMIT_LIMIT_HEADER = 'RateLimit-Limit'
RATE_LIMIT_REMAINING_HEADER = 'RateLimit-Remaining'

#: Bearer-token carrier. Read (and immediately hashed) purely for keying —
#: never validated here; validation stays in the principal resolver. Because the
#: value is unverified at this point, it can only ever *narrow* a budget: the
#: unspoofable peer tier is charged on every request regardless (see
#: ``RateLimitPolicy.charges``).
AUTHORIZATION_HEADER = 'authorization'


def _client_host(request) -> Optional[str]:
    client = getattr(request, 'client', None)
    return getattr(client, 'host', None) if client is not None else None


def _client_port(request):
    """The peer's source port, or ``None``.

    Read for one reason only: a restored address carries port ``0`` while a
    direct connection keeps its real ephemeral port, so this is how the process
    can tell *"this request came through the trusted hop"* from *"this request
    reached the published port directly"* — see
    ``peer_axis_observation.arrived_through_trusted_hop``.
    """
    client = getattr(request, 'client', None)
    return getattr(client, 'port', None) if client is not None else None


def rate_limiting_is_active(policy: Optional[RateLimitPolicy]) -> bool:
    """Will a middleware actually be installed for this policy?

    ⚠️ **Extracted because a second consumer needs the same answer** (adversarial
    review 3R). The peer-axis observation is driven *by* this middleware, so when
    the kill-switch turns the middleware off nothing ever calls the recorder —
    but the gauge family was still declared and still published ``unobserved``.
    Measured on a live stack: three distinct testers arrived through the gateway,
    the access log proved all three origins were preserved, and the gauge said
    *"the normal state just after a restart"*. Forever.

    An **absent** series and a **zero** series mean different things on a
    dashboard — this module's sibling says so in its own docstring — and a
    disabled observer must produce the first, not the second.
    """
    return policy is not None and bool(policy.enabled)


def create_rate_limit_middleware(
    *,
    policy: Optional[RateLimitPolicy],
    json_response,
    limiter: Optional[FixedWindowRateLimiter] = None,
    subject_header: Optional[str] = None,
    peer_axis_recorder=None,
):
    """Build the ASGI middleware callable, or ``None`` when limiting is off.

    ``json_response`` is the web framework's JSON response constructor, passed
    in rather than imported (see the module docstring). It is required even when
    ``policy`` is ``None``: making it optional would let a caller wire a live
    throttle that raises ``TypeError`` on the first denial — i.e. exactly under
    load, and never in a test that only checks the allow path.

    ``policy=None`` (the app-factory default) and ``policy.enabled=False`` (the
    env kill-switch) both return ``None`` — the caller then registers nothing at
    all, so a disabled deployment carries not just the same behaviour but the
    same middleware stack as before this change.

    ``subject_header`` is the *trusted* subject carrier, i.e. what
    :meth:`HttpAuthConfig.trusted_subject_header` returns — a non-empty name only
    in ``trusted_headers`` mode. Empty/``None`` means "this surface has no
    header-borne identity a pre-auth component may believe", and the middleware
    then keys identity on the bearer-token digest alone. Passing a header name
    here does NOT weaken the throttle either way: the peer tier is always charged
    (see the module docstring of ``rate_limit_policy``).

    ``peer_axis_recorder`` is the optional observation seam (2026-08-23): a
    ``recorder(peer_key)`` callable built by
    :func:`application.common.peer_axis_observer.build_peer_axis_recorder`. It
    answers a question this middleware cannot — whether the peer key is really
    *per caller* on this deployment or whether a relay collapsed every tester
    into one address (``FORWARDED_ALLOW_IPS`` says the server is ready to restore
    the real address; it cannot say that different addresses arrive).

    ⚠️ **The recorder is fed the policy's own peer key**, not a value derived
    here — see :meth:`RateLimitPolicy.peer_key_for`. Two derivations would let
    the gauge answer about a source axis nobody enforces.

    ⚠️ **``None`` means no observation, not a degraded one.** A surface that does
    not wire it exports no peer-axis gauge at all, which reads as "this build
    cannot answer" rather than as a silent zero.
    """
    if not rate_limiting_is_active(policy):
        return None

    active_limiter = limiter or FixedWindowRateLimiter()
    header_name = subject_header or ''

    async def middleware(request, call_next):  # type: ignore[no-untyped-def]
        headers = request.headers
        client_host = _client_host(request)
        # ⚠️ **Infrastructure traffic is not an observation.** The container
        # healthcheck probes this process on loopback every 15 s, bypassing the
        # reverse proxy, and the operator's own ``/metrics`` scrape arrives from
        # a third address — so without this gate the verdict reads
        # ``observed-distinct`` on a deployment where every tester is collapsed
        # into one bucket, which is the exact state the axis exists to detect
        # (measured by adversarial review, 2026-08-23). The path half is the
        # policy's decision, the source half is the pure domain's.
        # ⚠️ **여기서 거르지 않는다 — 사실을 넘긴다.** 복원 여부는 판정의 입력이지
        # 관측의 자격 조건이 아니다. 3R 은 이것을 게이트로 만들었고, 그래서 복원되지
        # 않은 요청이 관측기에 **도달조차 하지 않아** 아무 흔적도 남기지 않았다 —
        # 붕괴가 다시 «아직 아무것도 안 왔다» 로 읽혔다(적대 평가 4R 실측: 두 시험원이
        # 같은 버킷을 공유해 한쪽이 다른 쪽을 첫 요청에서 429 시키는 것이 그 자리에서
        # 증명됐는데도 게이지는 `unobserved` 였다). 세 갈래 분류는 도메인이 한 곳에서
        # 소유한다.
        if peer_axis_recorder is not None and policy.is_caller_traffic(
            request.url.path
        ):
            # Total by contract (the builder documents it): an observability
            # helper must never turn a served request into a 500.
            peer_axis_recorder(
                policy.peer_key_for(client_host),
                arrived_through_trusted_hop(_client_port(request)),
            )
        # A trusted subject is read ONLY when the surface declared one; in
        # oidc_jwt / none / disabled mode the header is attacker-controlled and
        # must not mint a bucket (mirror of principal_resolver's mode gate).
        verified_subject = headers.get(header_name) if header_name else None
        charges = policy.charges(
            request.url.path,
            verified_subject=verified_subject,
            authorization=headers.get(AUTHORIZATION_HEADER),
            client_host=client_host,
        )
        # Charge EVERY tier (a denied request still consumes, so a flood keeps
        # its window pinned) and deny if any tier is over budget.
        outcomes = [active_limiter.check(charge.key, charge.rule) for charge in charges]
        denied = [outcome for outcome in outcomes if not outcome.allowed]
        if not denied:
            return await call_next(request)
        # The caller must wait for the longest window still holding it back.
        outcome = max(denied, key=lambda item: item.retry_after_seconds)

        code = ErrorCode.RATE_LIMITED
        problem = ProblemDetails(
            status=status_for_code(code),
            title=ERROR_CODE_TITLES[code],
            code=code,
            detail=RATE_LIMIT_DETAIL,
            # ``retry_after`` is on PROBLEM_PARAM_ALLOWLIST (non-PII, structured).
            params={'retry_after': outcome.retry_after_seconds},
        )
        return json_response(
            status_code=problem.status,
            content=problem.as_dict(),
            media_type=PROBLEM_JSON_MEDIA_TYPE,
            headers={
                RETRY_AFTER_HEADER: str(outcome.retry_after_seconds),
                RATE_LIMIT_LIMIT_HEADER: str(outcome.limit),
                RATE_LIMIT_REMAINING_HEADER: str(outcome.remaining),
            },
        )

    return middleware


def install_rate_limit_middleware(
    app,
    *,
    policy: Optional[RateLimitPolicy],
    json_response,
    limiter: Optional[FixedWindowRateLimiter] = None,
    subject_header: Optional[str] = None,
    peer_axis_recorder=None,
) -> bool:
    """Register the throttle on ``app``; return whether anything was installed.

    Mirror of ``install_problem_details_handler`` — the three ``create_*_app``
    factories call exactly this one line, so the wiring cannot drift between
    surfaces, and both helpers take their framework objects the same way.
    """
    middleware = create_rate_limit_middleware(
        policy=policy,
        json_response=json_response,
        limiter=limiter,
        subject_header=subject_header,
        peer_axis_recorder=peer_axis_recorder,
    )
    if middleware is None:
        return False
    app.middleware('http')(middleware)
    return True
