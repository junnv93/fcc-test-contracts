"""WebSocket bearer-credential subprotocol grammar SSOT (W3-4, 2026-08-01).

Browser ``WebSocket`` cannot set custom request headers on the upgrade
handshake, so a bearer token cannot ride the standard ``authorization``
header the way it does on ``fetch()``. RFC 6455 §4.1 lets the client offer
one or more ``Sec-WebSocket-Protocol`` values, each of which must satisfy the
``token`` grammar of RFC 7230 §3.2.6. A JWT's charset (base64url
``A-Za-z0-9-_`` plus ``.`` segment separators) is a strict subset of that
grammar's ``tchar`` set, so the token can ride a subprotocol offer
unmodified — no encoding, no truncation.

This module is the single definition point for that offer/selection
grammar. Both WS driving adapters (``platform_routes.py`` chamber-progress
relay and ``session_router.py`` session-events stream) and the frontend
mirror (``apps/web/src/api/ws-bearer.ts``) consume it (the frontend mirror
is asserted byte-parity against this module's constant + encoding rule by a
dedicated cross-language test — see the contract).

dependency-free (`TestApplicationCommonPurity`) — stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Union


__all__ = [
    'WS_BEARER_SUBPROTOCOL',
    'WsBearerOffer',
    'encode_bearer_subprotocols',
    'parse_bearer_offer',
    'bearer_credential_request',
    'accepted_subprotocol',
]


#: Sentinel subprotocol value marking "the subprotocol offered immediately
#: after this one is a bearer credential, not a real application
#: subprotocol". The literal string is defined HERE ONLY — every other
#: producer/consumer (backend handlers, frontend mirror, tests) references
#: this constant rather than re-typing the string, so the grammar has
#: exactly one authorship point (`src/`-wide occurrence count of the literal
#: must equal 1).
WS_BEARER_SUBPROTOCOL = 'fcc.bearer.v1'


@dataclass(frozen=True)
class WsBearerOffer:
    """Result of parsing a client's offered ``Sec-WebSocket-Protocol`` values.

    ``selected`` is the subprotocol value the server MUST echo back via
    ``websocket.accept(subprotocol=...)`` — RFC 6455 forbids a server from
    selecting a value the client did not offer, so ``None`` means "offer
    something else or nothing" (byte-identical to today's unauthenticated
    ``accept()`` call). ``token`` is the decoded bearer credential, or the
    empty string when no bearer offer was present.
    """

    selected: Union[str, None]
    token: str


def encode_bearer_subprotocols(token: str) -> tuple:
    """Client-side encoding SSOT — mirrored by ``ws-bearer.ts``.

    A blank/whitespace-only token encodes to an empty tuple (no subprotocol
    offer at all — auth-disabled deployments and today's test doubles stay
    byte-identical). Otherwise the sentinel is offered first, immediately
    followed by the raw token.
    """
    normalized = (token or '').strip()
    if not normalized:
        return ()
    return (WS_BEARER_SUBPROTOCOL, normalized)


def parse_bearer_offer(offered) -> WsBearerOffer:
    """Parse a client's offered subprotocol(s) for a bearer credential.

    ``offered`` accepts either the raw ``Sec-WebSocket-Protocol`` header
    value (a comma-separated string per RFC 6455 §4.3) or an already-split
    sequence (ASGI servers commonly expose the offer as
    ``websocket.scope['subprotocols']``, a list). Absence of the sentinel —
    including an empty/``None`` offer — parses to ``WsBearerOffer(None,
    '')``, i.e. byte-identical to today's non-browser clients that never
    offer a subprotocol at all.
    """
    values = _split_offer(offered)
    for index, value in enumerate(values):
        if value == WS_BEARER_SUBPROTOCOL and index + 1 < len(values):
            token = values[index + 1].strip()
            if token:
                return WsBearerOffer(selected=WS_BEARER_SUBPROTOCOL, token=token)
    return WsBearerOffer(selected=None, token='')


def bearer_credential_request(websocket):
    """Build the credential view a principal resolver should consume.

    Precedence (security-relevant): a genuine, non-blank ``authorization``
    header always wins — the subprotocol overlay only fills in when that
    header is absent/blank. This keeps non-browser clients (node heartbeat
    sender, proxies) that already send a real header unaffected by browser
    grammar. Only ``authorization`` is synthesized; every other header —
    including the ``trusted_headers`` mode's ``X-FCC-Subject`` /
    ``X-FCC-Permissions`` — passes through untouched so the two auth modes
    never interfere.

    When no overlay applies (real header present, or no bearer offer), the
    original ``websocket`` is returned unchanged — today's callers see
    byte-identical behavior.
    """
    headers = getattr(websocket, 'headers', {})
    if _header_get(headers, 'authorization'):
        return websocket
    offer = parse_bearer_offer(_header_get(headers, 'sec-websocket-protocol'))
    if not offer.token:
        return websocket
    return _BearerOverlayRequest(headers, offer.token)


def accepted_subprotocol(
    offer: WsBearerOffer, *, principal_resolver_active: bool,
) -> Union[str, None]:
    """``accept(subprotocol=...)`` negotiation SSOT (M2.3, 2026-08-01).

    When auth is disabled (``principal_resolver_active=False``), the
    handler never routes the offer through ``bearer_credential_request`` —
    resolution is skipped entirely, so nothing validated the offered
    token. Echoing the sentinel back in that case would tell the client
    the server checked a credential it never touched, so this returns
    ``None`` unconditionally (byte-identical to the original pre-W3-4
    ``accept()`` call with no subprotocol) regardless of what the client
    offered. Only when a resolver is actually wired does the negotiated
    ``offer.selected`` value apply.
    """
    if not principal_resolver_active:
        return None
    return offer.selected


def _split_offer(offered) -> list:
    if offered is None:
        return []
    if isinstance(offered, str):
        return [part.strip() for part in offered.split(',') if part.strip()]
    if isinstance(offered, Sequence):
        return [str(part).strip() for part in offered if str(part).strip()]
    return []


def _case_insensitive_get(headers, name: str, default=None):
    """Duck-typed ``.get(name, default)`` lookup that tolerates a plain
    (case-sensitive) mapping as well as Starlette's ``Headers`` object
    (already case-insensitive internally). This module's contract with
    callers is "anything with a ``.get()`` method" — a real ASGI request
    always hands us Starlette ``Headers``, but a mixed/upper-case
    ``authorization`` key on a plain-dict mapping (test doubles, future
    callers) must resolve identically, or the security-relevant real-header
    precedence in ``bearer_credential_request`` silently degrades to the
    overlay on a case mismatch alone.

    Tries the exact key first (single call, no scan, for the common
    already-normalized case), then falls back to a case-insensitive
    ``.items()`` scan only when that misses.
    """
    getter = getattr(headers, 'get', None)
    if not callable(getter):
        return default
    value = getter(name, None)
    if value is not None:
        return value
    target = str(name).strip().lower()
    items = getattr(headers, 'items', None)
    if callable(items):
        for key, val in items():
            if str(key).strip().lower() == target:
                return val
    return default


def _header_get(headers, name: str) -> str:
    return str(_case_insensitive_get(headers, name, '') or '').strip()


class _OverlayHeaders:
    """Read-only header view — same ``.get(name, default)`` duck-type the
    resolvers already consume, with ``authorization`` synthesized and every
    other name (case-insensitive, matching Starlette ``Headers`` semantics —
    enforced here via ``_case_insensitive_get`` rather than assumed of the
    underlying mapping) passed straight through to the underlying headers
    object."""

    __slots__ = ('_headers', '_token')

    def __init__(self, headers, token: str) -> None:
        self._headers = headers
        self._token = token

    def get(self, name: str, default=''):
        if str(name).strip().lower() == 'authorization':
            return f'Bearer {self._token}'
        return _case_insensitive_get(self._headers, name, default)


class _BearerOverlayRequest:
    """Minimal credential view — exposes only ``.headers`` (the sole
    attribute every principal resolver in this codebase reads)."""

    __slots__ = ('headers',)

    def __init__(self, headers, token: str) -> None:
        self.headers = _OverlayHeaders(headers, token)
