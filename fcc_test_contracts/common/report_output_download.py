"""Stateless HMAC-signed download token for filesystem report outputs (FE-P6-DL).

A browser top-level navigation (``window.location.assign``) cannot attach the
RBAC permission header, so the download URL must be **self-authorizing**. A
short-TTL HMAC token — issued only to a ``report_automation:read`` principal at
grant time and bound to one output path + expiry — lets the stream endpoint
authorize the request without any server-side state (multi-worker safe, no
per-download lookup). This is the industry-standard pre-signed-token model.

Distinct from ``platform_signed_download`` (object-store *URLs*, HTTPS-only): this
targets the on-disk report output proxy-stream path. The actual file resolution
+ path-traversal guard live in ``platform_download_proxy.resolve_download_grant``;
this module only proves token authenticity + freshness.

Dependency-free — stdlib only (``TestApplicationCommonPurity`` neighborhood).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Mapping


__all__ = [
    'DownloadExpiredError',
    'DownloadIntegrityError',
    'DownloadTokenError',
    'MIN_SIGNING_SECRET_LENGTH',
    'REPORT_DOWNLOAD_TOKEN_FIELDS',
    'sign_report_download_token',
    'verify_report_download_token',
]

# HMAC signing secret floor — mirrors platform_signed_download's 32-char minimum
# so a misconfigured (short/empty) secret fails loud instead of issuing weak
# tokens.
MIN_SIGNING_SECRET_LENGTH = 32

# Signed payload fields (the cryptographic binding). request_id scopes the token
# to one report-automation request; relative_path/storage_backend bind the exact
# file; expires_at bounds the lifetime; sha256/disposition flow to the resolver.
REPORT_DOWNLOAD_TOKEN_FIELDS = (
    'request_id',
    'relative_path',
    'storage_backend',
    'disposition',
    'expires_at',
    'sha256',
)


class DownloadTokenError(PermissionError):
    """Raised when a download token is missing, malformed, or forged.

    Maps to HTTP 403 (the token IS the credential — a bad one is forbidden).
    """


class DownloadExpiredError(DownloadTokenError):
    """Raised when a download token / grant has expired.

    Subclass of :class:`DownloadTokenError` so existing ``except`` / ``isinstance``
    checks (and the expiry tests) keep working, but the stream route maps it to
    HTTP **410 Gone** — the access window elapsed and the client should request a
    fresh grant (distinct from a forged/invalid 403).
    """


class DownloadIntegrityError(Exception):
    """Raised when the file bytes do not match the grant's signed sha256.

    Maps to HTTP **409 Conflict** — the resource that was granted has changed on
    disk (or is corrupt); 404 ("not found") would be misleading because the file
    exists. NOT a ``PermissionError`` subclass, so the route error boundary must
    list it explicitly (it would otherwise escape as a 500).
    """


def sign_report_download_token(*, payload: Mapping[str, object], secret: str) -> str:
    """Return an opaque base64url token binding ``payload`` under ``secret``."""
    _require_secret(secret)
    body = {key: str(payload.get(key, '') or '') for key in REPORT_DOWNLOAD_TOKEN_FIELDS}
    if not body['request_id'] or not body['relative_path']:
        raise ValueError('request_id and relative_path are required')
    if not body['expires_at']:
        raise ValueError('expires_at is required')
    body['sig'] = _signature(body, secret)
    raw = json.dumps(body, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii')


def verify_report_download_token(token: str, *, secret: str, now: datetime) -> dict:
    """Verify a token's HMAC + freshness and return its bound fields.

    Raises ``DownloadTokenError`` for any missing/malformed/forged/expired token
    so the stream route can map it to 401/403 (never silently serve a file).
    """
    _require_secret(secret)
    if not isinstance(token, str) or not token:
        raise DownloadTokenError('download token is required')
    try:
        raw = base64.urlsafe_b64decode(token.encode('ascii'))
        decoded = json.loads(raw.decode('utf-8'))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise DownloadTokenError('malformed download token') from exc
    if not isinstance(decoded, dict):
        raise DownloadTokenError('malformed download token payload')
    signature = str(decoded.get('sig') or '')
    body = {key: str(decoded.get(key, '') or '') for key in REPORT_DOWNLOAD_TOKEN_FIELDS}
    expected = _signature(body, secret)
    if not signature or not hmac.compare_digest(signature, expected):
        raise DownloadTokenError('invalid download token signature')
    _require_not_expired(body['expires_at'], now)
    return body


def _require_secret(secret: str) -> None:
    if len(str(secret or '')) < MIN_SIGNING_SECRET_LENGTH:
        raise ValueError(
            f'download signing secret must be at least {MIN_SIGNING_SECRET_LENGTH} characters'
        )


def _canonical(payload: Mapping[str, str]) -> str:
    return '\n'.join(f'{key}={payload[key]}' for key in sorted(payload))


def _signature(payload: Mapping[str, str], secret: str) -> str:
    return hmac.new(
        secret.encode('utf-8'),
        _canonical(payload).encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def _require_not_expired(expires_at: str, now: datetime) -> None:
    text = expires_at.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        expiry = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DownloadTokenError('malformed expires_at') from exc
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if current.astimezone(timezone.utc) >= expiry.astimezone(timezone.utc):
        raise DownloadExpiredError('download token has expired')
