"""HTTP principal resolver SSOT for Session API + Headless API (F-2-D4).

Consolidates the previously duplicated ``TrustedHeaderPrincipalResolver`` /
``_header_value`` / ``_split_permissions`` definitions in
``infrastructure/adapters/driving/api/session_router.py`` and
``infrastructure/adapters/driving/api/headless_routes.py``. Both driving
adapters now re-export from here so the implementation lives in exactly one
place.

The OIDC path is reached via a lazy import of the existing
``application/headless/oidc_principal_resolver`` module — moving it under
``application/common/`` is out of scope (tracked as SHOULD S3 in the contract).

dependency-free: no FastAPI / PySide6 / openpyxl / pandas / sqlalchemy imports.
"""
from __future__ import annotations

from typing import Any, Mapping

from fcc_test_contracts.common.auth_config import (
    AUTH_MODE_DISABLED,
    AUTH_MODE_LOCAL_JWT,
    AUTH_MODE_NONE,
    AUTH_MODE_OIDC_JWT,
    AUTH_MODE_TRUSTED_HEADERS,
    HttpAuthConfig,
)
from fcc_test_contracts.common.access_policy import ApiPrincipal
# ⚠️ MODULE-LEVEL, not lazy. Both modules are in this same (contracts) lane, so
# there is no cycle and no cost — and the extraction stager only rewrites
# module-level import statements. A lazy `from application.common.X import ...`
# survives verbatim into the staged box, where `application.common` no longer
# exists, and the box fails to import itself.
from fcc_test_contracts.common.identity import LOCAL_IDENTITY_ISSUER
from fcc_test_contracts.common.local_identity import (
    CLAIM_EMAIL,
    CLAIM_FORCE_PASSWORD_CHANGE,
    CLAIM_NAME,
    CLAIM_PERMISSIONS,
    DEFAULT_LOCAL_JWT_ACCESS_TTL_SECONDS,
    DEFAULT_LOCAL_JWT_REFRESH_TTL_SECONDS,
    TOKEN_TYPE_ACCESS,
    LocalJwtConfig,
    verify_token,
)


__all__ = [
    'LocalJwtPrincipalResolver',
    'TrustedHeaderPrincipalResolver',
    'build_local_jwt_config',
    'create_principal_resolver',
    'header_value',
    'record_validated_bearer',
    'split_permissions',
    'validated_bearer_authorization',
]


class TrustedHeaderPrincipalResolver:
    """Resolve principals from headers supplied by a trusted proxy/runtime."""

    def __init__(
        self,
        *,
        subject_header: str = 'X-FCC-Subject',
        permissions_header: str = 'X-FCC-Permissions',
    ) -> None:
        self.subject_header = subject_header
        self.permissions_header = permissions_header

    def resolve(self, request) -> ApiPrincipal:
        headers = getattr(request, 'headers', {}) if request is not None else {}
        subject = header_value(headers, self.subject_header) or 'anonymous'
        permissions = split_permissions(header_value(headers, self.permissions_header))
        return ApiPrincipal.from_permissions(subject, permissions)


def header_value(headers: Any, name: str) -> str:
    """Best-effort header lookup that works with Starlette/FastAPI request headers
    (case-insensitive ``.get``) and plain dicts."""
    getter = getattr(headers, 'get', None)
    if callable(getter):
        return str(getter(name, '') or '').strip()
    if isinstance(headers, Mapping):
        return str(headers.get(name, '') or '').strip()
    return ''


def split_permissions(value: str) -> list[str]:
    """Split a header value on ``,`` or ``;`` into a stripped permission list."""
    if not value:
        return []
    normalized = value.replace(';', ',')
    return [part.strip() for part in normalized.split(',') if part.strip()]


_VALIDATED_BEARER_STATE_ATTR = 'validated_bearer_authorization'


def record_validated_bearer(request, token: str) -> None:
    """Attach a successfully validated bearer credential to request state.

    Downstream service-boundary calls may forward this value, but must never
    fall back to the raw request header: trusted-header mode and failed token
    validation must not turn an unverified string into an authorization
    credential.
    """
    if request is None or not token:
        return
    state = getattr(request, 'state', None)
    if state is not None:
        setattr(state, _VALIDATED_BEARER_STATE_ATTR, f'Bearer {token}')


def validated_bearer_authorization(request) -> str:
    """Return only the bearer value recorded after auth validation."""
    state = getattr(request, 'state', None) if request is not None else None
    return str(getattr(state, _VALIDATED_BEARER_STATE_ATTR, '') or '').strip()


def create_principal_resolver(auth: HttpAuthConfig, *, revocation_list=None):
    """Single factory for Session + Headless + Platform principal resolution.

    Returns ``None`` when auth is disabled so the FastAPI app skips wiring an
    AuthZ dependency. Raises ``ValueError`` on misconfigured OIDC fields or
    unsupported modes.

    ``revocation_list`` is consumed by ``local_jwt`` only and is keyword-only with
    a ``None`` default, so every existing single-argument call site keeps its
    exact behaviour. The other four modes ignore it — ``trusted_headers`` has no
    token to revoke, and OIDC token revocation belongs to the IdP.
    """
    mode = (auth.auth_mode or AUTH_MODE_DISABLED).strip().lower()
    if mode in {'', AUTH_MODE_DISABLED, AUTH_MODE_NONE}:
        return None
    if mode == AUTH_MODE_TRUSTED_HEADERS:
        return TrustedHeaderPrincipalResolver(
            subject_header=auth.auth_subject_header,
            permissions_header=auth.auth_permissions_header,
        )
    if mode == AUTH_MODE_OIDC_JWT:
        if not (auth.oidc_issuer and auth.oidc_audience and auth.oidc_jwks_uri):
            raise ValueError(
                'oidc_jwt auth requires issuer, audience, and jwks_uri'
            )
        if _is_entra_issuer(auth.oidc_issuer) and auth.oidc_subject_claim != 'oid':
            raise ValueError(
                'oidc_jwt auth with Microsoft Entra issuer requires '
                "oidc_subject_claim='oid' for stable issuer+subject identity"
            )
        from fcc_test_contracts.common.oidc_principal_resolver import (
            BearerTokenPrincipalResolver,
            OidcJwtConfig,
        )
        return BearerTokenPrincipalResolver(
            OidcJwtConfig(
                issuer=auth.oidc_issuer,
                audience=auth.oidc_audience,
                jwks_uri=auth.oidc_jwks_uri,
                subject_claim=auth.oidc_subject_claim,
                name_claim=auth.oidc_name_claim,
                email_claim=auth.oidc_email_claim,
                permissions_claim=auth.oidc_permissions_claim,
                scope_claim=auth.oidc_scope_claim,
                role_claim=auth.oidc_role_claim,
            )
        )
    if mode == AUTH_MODE_LOCAL_JWT:
        return LocalJwtPrincipalResolver(
            build_local_jwt_config(auth), revocation_list=revocation_list,
        )
    raise ValueError(f'unsupported auth mode: {auth.auth_mode!r}')


def build_local_jwt_config(auth: HttpAuthConfig):
    """``HttpAuthConfig`` (all-text, env-shaped) → validated ``LocalJwtConfig``.

    Separate from the resolver so the composition root and the login service can
    build the SAME config object from the SAME fields. Two constructions would be
    two parsers, and the day they disagree the API issues tokens it then refuses.
    """
    config = LocalJwtConfig(
        secret=auth.local_jwt_secret,
        issuer=auth.local_jwt_issuer,
        audience=auth.local_jwt_audience,
        access_ttl_seconds=_positive_int(
            auth.local_jwt_ttl_seconds,
            DEFAULT_LOCAL_JWT_ACCESS_TTL_SECONDS,
            'local_jwt_ttl_seconds',
        ),
        refresh_ttl_seconds=_positive_int(
            auth.local_jwt_refresh_ttl_seconds,
            DEFAULT_LOCAL_JWT_REFRESH_TTL_SECONDS,
            'local_jwt_refresh_ttl_seconds',
        ),
    )
    config.validate()
    return config


def _positive_int(raw: str, default: int, field: str) -> int:
    """Empty → default. Present-but-unparseable → ``ValueError``, never default.

    ⚠️ Falling back to the default on garbage is the failure mode this guards:
    an operator who writes ``LOCAL_JWT_TTL_SECONDS=15m`` would silently get 900
    seconds by coincidence of the default, and would get whatever the default
    later becomes. "Unset" and "set to something I could not read" are different
    statements and only the first one has a safe answer.
    """
    text = str(raw or '').strip()
    if not text:
        return default
    try:
        value = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'{field} must be an integer number of seconds, got {raw!r}'
        ) from exc
    if value <= 0:
        raise ValueError(f'{field} must be positive, got {value}')
    return value


class LocalJwtPrincipalResolver:
    """Resolve a principal from a token this API itself signed.

    Semantics are byte-for-byte those of the OIDC resolver so the two modes are
    interchangeable to everything downstream: **no bearer token → anonymous**
    (so ``public`` operations like login still work), **invalid token →
    ``PermissionError``** (403 via the route boundary).

    ⚠️ ``issuer=LOCAL_IDENTITY_ISSUER`` and NOT ``config.issuer``. Those are two
    different axes that only OIDC lets you conflate: ``config.issuer`` is the
    ``iss`` claim (who signed this TOKEN, a deployment setting), while the
    principal's issuer is the identity half of the ``users`` primary key (who
    minted this IDENTITY). Passing the setting here would mean that changing
    ``LOCAL_JWT_ISSUER`` silently detaches every principal from its ``users`` row
    — login would still succeed while every permission and membership lookup
    quietly missed.
    """

    def __init__(self, config, *, revocation_list=None) -> None:
        self._config = config
        self._revocations = revocation_list

    def resolve(self, request) -> ApiPrincipal:
        token = _bearer_token(request)
        if not token:
            return ApiPrincipal.anonymous()
        # ⚠️ expected_type=ACCESS — a refresh token must not authorise a request.
        # Its signature, issuer and audience are all valid, so nothing but this
        # check stands between a 7-day credential and a 15-minute seat.
        claims = verify_token(self._config, token, expected_type=TOKEN_TYPE_ACCESS)
        # ⚠️ Revocation is checked HERE, not in the login service: this is the only
        # place every authenticated request passes through. A logout that only the
        # login service knew about would revoke nothing.
        if self._revocations is not None and self._revocations.is_revoked(
            claims.get('jti')
        ):
            raise PermissionError('local token has been revoked')
        subject = str(claims.get('sub') or '').strip()
        if not subject:
            raise PermissionError('local token subject claim is required')
        permissions = [
            str(item).strip()
            for item in (claims.get(CLAIM_PERMISSIONS) or [])
            if str(item).strip()
        ]
        record_validated_bearer(request, token)
        return ApiPrincipal.from_permissions(
            subject,
            permissions,
            issuer=LOCAL_IDENTITY_ISSUER,
            display_name=str(claims.get(CLAIM_NAME) or '').strip(),
            email=str(claims.get(CLAIM_EMAIL) or '').strip(),
            force_password_change=bool(claims.get(CLAIM_FORCE_PASSWORD_CHANGE)),
        )


def _bearer_token(request) -> str:
    """``Authorization: Bearer <token>``, or ``''``.

    Deliberately the same shape as ``oidc_principal_resolver._bearer_token``. It
    is not imported from there because that module reaches for JWKS over the
    network at import-adjacent paths, and this mode must work on a host that can
    reach no IdP at all — that is the entire point of the mode.
    """
    headers = getattr(request, 'headers', {}) if request is not None else {}
    getter = getattr(headers, 'get', None)
    value = str(getter('authorization', '') if callable(getter) else '').strip()
    if not value.lower().startswith('bearer '):
        return ''
    return value[7:].strip()


def _is_entra_issuer(issuer: str) -> bool:
    normalized = str(issuer or '').strip().lower()
    return (
        'login.microsoftonline.com/' in normalized
        or 'sts.windows.net/' in normalized
        or 'login.microsoft.com/' in normalized
    )
