"""OIDC bearer-token principal resolution for the headless API runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import threading
import time
from typing import Callable, Mapping
from urllib.request import Request, urlopen

from fcc_test_contracts.common.access_policy import ApiPrincipal
from fcc_test_contracts.common.outbound_http import build_outbound_traceparent_headers
from fcc_test_contracts.common.principal_resolver import record_validated_bearer


__all__ = [
    'BearerTokenPrincipalResolver',
    'JwksKeyProvider',
    'OIDC_CLOCK_TOLERANCE_SECONDS',
    'OIDC_REFRESH_MARGIN_SECONDS',
    'OidcJwtConfig',
]


#: Sprint S2-δ γ-P0-1 + γ-P1-1 — backend ↔ frontend cross-tech SSOT for
#: **clock skew tolerance** on JWT ``exp``/``iat``/``nbf`` validation.
#:
#: This is the value PyJWT's ``decode(leeway=N)`` and jose's
#: ``jwtVerify({ clockTolerance: N })`` both consume — they are the SAME
#: concept (acceptable clock skew between RP and IdP). The frontend
#: mirrors this constant as ``apps/web/src/auth/session.ts::OIDC_CLOCK_TOLERANCE_SECONDS``;
#: enforced by ``TestBackendFrontendClockToleranceSsot``.
#:
#: Distinct from ``OIDC_REFRESH_MARGIN_SECONDS`` below (which is a
#: client-side silent-refresh schedule margin, not a server validation
#: tolerance). Pre-S2-δ collapsed these into one constant — S2-γ's audit
#: caught the conceptual conflation.
#:
#: Rationale: NIST SP 800-63B § 7.2 + Auth0 (default 60s) / Microsoft
#: Identity / Keycloak / Curity 30-60s industry standard. 60s is the
#: Auth0 default — chosen here (S2-ε δ-P1-1) so the value is genuinely
#: independent from ``OIDC_REFRESH_MARGIN_SECONDS`` (30s). Pre-S2-ε
#: collapsed both to 30 — the cross-check invariant trivially passed
#: but the *concept separation* was decorative. Distinct values force
#: a future tuner to consider the two concerns separately.
OIDC_CLOCK_TOLERANCE_SECONDS = 60


#: Sprint S2-β α-10 + S2-γ β-P0-3 — backend ↔ frontend cross-tech SSOT
#: for **silent-refresh schedule margin** (frontend-only concept).
#:
#: Mirrors ``apps/web/src/auth/session.ts::MIN_REFRESH_MARGIN_SECONDS``.
#: This is the *client-side* scheduling budget — how many seconds before
#: the access-token's ``exp`` the SPA fires its silent-refresh fetch.
#: It is NOT used in backend JWT decode (that's ``OIDC_CLOCK_TOLERANCE_SECONDS``
#: above). Backend keeps this constant so a cross-check invariant can
#: still verify the two sides agree on the operational value (even
#: though the backend doesn't directly *use* this number in PyJWT decode).
#:
#: Rationale: RFC 6749 § 5.1 + industry 15-60s SPA guidance. See the
#: tuning runbook in
#: ``docs/architecture/frontend/cross-tech-token-policy.md``.
OIDC_REFRESH_MARGIN_SECONDS = 30


#: Sprint S2-δ γ-P2-9 — owner-sprint coordination note. This module is
#: under F-2-D4 (HttpAuthConfig) and P0-3 (W3C outbound traceparent
#: integration) ownership. S2-γ/S2-δ additions are constants + a
#: ``leeway=`` kwarg on ``jwt.decode`` — neither touches the
#: ``BearerTokenPrincipalResolver`` resolve flow nor the JwksKeyProvider
#: outbound HTTP path. Constant-add + decode-kwarg are additive and do
#: not affect the F-2-D4 dataclass shape or the P0-3 traceparent header
#: build. Regression verified by ``tests/test_apps_web_auth_scaffold.py``
#: + ``tests/test_architecture_conformance.py`` (511 + 2 skip baseline).


@dataclass(frozen=True)
class OidcJwtConfig:
    issuer: str
    audience: str
    jwks_uri: str
    subject_claim: str = 'sub'
    name_claim: str = 'name'
    email_claim: str = 'email'
    permissions_claim: str = 'permissions'
    scope_claim: str = 'scope'
    role_claim: str = 'roles'
    #: 멀티챔버(2026-06-20) — chamber machine 토큰을 한 chamber 에 묶는 claim 이름.
    #: 존재 시 ApiPrincipal.chamber_id 로 전파돼 heartbeat 엔드포인트가 토큰↔body
    #: chamber_id 일치를 강제(per-chamber 바인딩). 일반 토큰엔 없음(빈 값).
    chamber_claim: str = 'chamber_id'
    role_permission_map: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


class JwksKeyProvider:
    #: OIDC IdP signing-key ROTATION robustness (2026-06-20). When a bearer token
    #: carries a ``kid`` absent from the cached JWKS, the IdP most likely rotated
    #: its signing keys. The provider refetches JWKS ONCE and retries before
    #: failing — so a key rotation (or a Keycloak restart that regenerates keys)
    #: does NOT require an API process restart to recover. The refetch is
    #: throttled to at most one per ``JWKS_MIN_REFRESH_INTERVAL_SECONDS`` so a
    #: flood of tokens carrying random/unknown ``kid`` values cannot turn into one
    #: outbound JWKS fetch per request (DoS guard). Industry standard: refresh
    #: signing keys on cache-miss with a bounded refresh rate.
    JWKS_MIN_REFRESH_INTERVAL_SECONDS = 60.0

    def __init__(
        self,
        jwks_uri: str,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._jwks_uri = jwks_uri
        self._keys_by_kid: dict[str, object] = {}
        self._clock = clock
        self._last_load_at: float | None = None
        # single-flight: serialize JWKS (re)loads so a burst of concurrent
        # requests carrying the same just-rotated/unknown kid triggers exactly
        # ONE outbound JWKS fetch (thundering-herd guard), not one per thread.
        self._load_lock = threading.Lock()

    def get_key(self, kid: str):
        # Fast path — no lock when the key is already cached (the common case).
        key = self._lookup(kid)
        if key is not None:
            return key
        # Slow path — cold cache or unknown kid (IdP may have rotated keys).
        # Serialize so concurrent misses collapse into a single fetch, and
        # double-check after acquiring (another thread may have just loaded).
        with self._load_lock:
            key = self._lookup(kid)
            if key is not None:
                return key
            if not self._keys_by_kid or self._can_refresh():
                self._load()
                key = self._lookup(kid)
                if key is not None:
                    return key
        raise PermissionError('JWT signing key was not found in JWKS')

    def _lookup(self, kid: str):
        if kid and kid in self._keys_by_kid:
            return self._keys_by_kid[kid]
        if not kid and len(self._keys_by_kid) == 1:
            return next(iter(self._keys_by_kid.values()))
        return None

    def _can_refresh(self) -> bool:
        if self._last_load_at is None:
            return True
        return (self._clock() - self._last_load_at) >= self.JWKS_MIN_REFRESH_INTERVAL_SECONDS

    def _load(self) -> None:
        try:
            import jwt
        except ImportError as exc:
            raise RuntimeError('PyJWT[crypto] is required for OIDC JWT validation') from exc
        headers = build_outbound_traceparent_headers(
            existing={'Accept': 'application/json'},
        )
        request = Request(self._jwks_uri, headers=headers)
        with urlopen(request, timeout=5.0) as response:
            payload = json.loads(response.read().decode('utf-8'))
        keys = payload.get('keys')
        if not isinstance(keys, list) or not keys:
            raise PermissionError('JWKS did not contain signing keys')
        loaded: dict[str, object] = {}
        for key in keys:
            if not isinstance(key, Mapping):
                continue
            kid = str(key.get('kid') or '').strip()
            if kid:
                loaded[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
        # Replace (not merge) so keys rotated OUT at the IdP stop being trusted.
        self._keys_by_kid = loaded
        self._last_load_at = self._clock()


class BearerTokenPrincipalResolver:
    def __init__(
        self,
        config: OidcJwtConfig,
        *,
        key_provider: JwksKeyProvider | None = None,
    ) -> None:
        self._config = config
        self._key_provider = key_provider or JwksKeyProvider(config.jwks_uri)

    def resolve(self, request) -> ApiPrincipal:
        token = _bearer_token(request)
        if not token:
            return ApiPrincipal.anonymous()
        claims = self._decode(token)
        subject = str(claims.get(self._config.subject_claim) or '').strip()
        if not subject:
            raise PermissionError('JWT subject claim is required')
        permissions = _claim_values(claims.get(self._config.permissions_claim))
        permissions.extend(_claim_values(claims.get(self._config.scope_claim)))
        permissions.extend(self._role_permissions(claims.get(self._config.role_claim)))
        chamber_id = str(claims.get(self._config.chamber_claim) or '').strip()
        display_name = str(claims.get(self._config.name_claim) or '').strip()
        email = str(claims.get(self._config.email_claim) or '').strip()
        record_validated_bearer(request, token)
        return ApiPrincipal.from_permissions(
            subject, permissions, chamber_id=chamber_id, issuer=self._config.issuer,
            display_name=display_name, email=email,
        )

    def _decode(self, token: str) -> Mapping:
        try:
            import jwt
        except ImportError as exc:
            raise RuntimeError('PyJWT[crypto] is required for OIDC JWT validation') from exc
        try:
            header = jwt.get_unverified_header(token)
            key = self._key_provider.get_key(str(header.get('kid') or '').strip())
            return jwt.decode(
                token,
                key=key,
                algorithms=['RS256'],
                audience=self._config.audience,
                issuer=self._config.issuer,
                # Sprint S2-δ γ-P0-1 — clock skew tolerance for exp/iat/nbf
                # validation. Mirrors frontend jose ``clockTolerance``
                # (same concept, same SSOT value).
                leeway=OIDC_CLOCK_TOLERANCE_SECONDS,
            )
        except PermissionError:
            raise
        except Exception as exc:
            raise PermissionError('JWT validation failed') from exc

    def _role_permissions(self, value) -> list[str]:
        permissions: list[str] = []
        for role in _claim_values(value):
            permissions.extend(self._config.role_permission_map.get(role, ()))
        return permissions


def _bearer_token(request) -> str:
    headers = getattr(request, 'headers', {}) if request is not None else {}
    getter = getattr(headers, 'get', None)
    value = str(getter('authorization', '') if callable(getter) else '').strip()
    if not value.lower().startswith('bearer '):
        return ''
    return value[7:].strip()


def _claim_values(value) -> list[str]:
    if value in (None, ''):
        return []
    if isinstance(value, str):
        normalized = value.replace(',', ' ')
        return [part.strip() for part in normalized.split() if part.strip()]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]
