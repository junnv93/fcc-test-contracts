"""Inbound HTTP/WS request correlation SSOT (P1-E, 2026-05-22).

Mirror module of :mod:`application.common.outbound_http`. Both Session and
Headless web surfaces share this single source of truth for parsing W3C
TraceContext / OBS-1 request-id headers and echoing the canonical response
headers — duplicating the parse/format/echo logic in each FastAPI driving
adapter would have re-introduced the SSOT violation that P1-1/OBS-1/P1-A/P1-B
already eliminated for Session API.

Scope:

- ``IncomingCorrelation`` frozen dataclass captures the five identifiers that
  every inbound HTTP request resolves to (``request_id`` + W3C
  ``trace_id``/``span_id``/``sampled``/``tracestate``). Both ContextVar
  binding and response-header echo consume the same dataclass.
- ``extract_incoming_correlation(headers)`` is a pure function — no FastAPI,
  no PySide6, no infrastructure imports. Caller passes any
  ``Mapping[str, str]``-shaped headers object (FastAPI's ``request.headers``,
  Starlette's ``Headers``, a plain ``dict``) and receives the resolved
  correlation. W3C spec § 3.2 ("invalid traceparent → treat as if doesn't
  exist") and § 3.3 (tracestate vendor extension propagation) are honored.
- ``apply_correlation_response_headers(response_headers, correlation)`` echoes
  ``X-Request-Id`` + canonical ``traceparent`` (always) + ``tracestate``
  (only when non-empty — matches P1-A behaviour). Caller passes a
  ``MutableMapping[str, str]``-shaped response headers object.
- ``WsTraceContext`` + ``extract_ws_trace_context(websocket)`` — WebSocket
  upgrade resolves trace context via two transports (header first, query
  string fallback). RFC unspecified for WS, so we support both: the header
  transport works through TestClient + reverse proxies, the query string
  works through browser ``new WebSocket(url)`` calls that cannot set custom
  request headers. ``request_id`` is intentionally absent — WS uses
  connection-scoped correlation via a locally-generated ``connection_id``.

Why a pure-function SSOT instead of a middleware factory:

Both driving adapters keep their ``@app.middleware('http')`` decorator + the
``with bind_request_id(...): with bind_trace_context(...):`` context manager
nesting in their own module body. The AST guards introduced by P1-1 / OBS-1 /
P1-A / P1-B (e.g. ``test_correlation_contextvars_deep1`` asserts the literal
``with bind_request_id(request_id):`` is present in ``session_router.py``)
remain valid because the call-site stays in each adapter's file. The shared
helper carries only the parts of the work that are spec-defined and
adapter-independent — header parsing + canonical echo.

dependency-free: stdlib + ``application.common.correlation`` only.
"""
from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Tuple

from fcc_test_contracts.common.correlation import (
    format_traceparent_unchecked,
    format_tracestate,
    generate_span_id,
    generate_trace_id,
    parse_traceparent,
    parse_tracestate,
)


__all__ = [
    'IncomingCorrelation',
    'REQUEST_ID_HEADER',
    'REQUEST_ID_HEADER_ALT',
    'TRACEPARENT_HEADER',
    'TRACESTATE_HEADER',
    'WsTraceContext',
    'apply_correlation_response_headers',
    'extract_incoming_correlation',
    'extract_ws_trace_context',
]


# W3C / OWASP standard header names — defined by the spec, not project-local
# magic strings. Keeping them as module-level constants makes the AST grep
# guard (and the test fixtures) self-documenting and prevents typos.
REQUEST_ID_HEADER: str = 'x-request-id'
REQUEST_ID_HEADER_ALT: str = 'request-id'
TRACEPARENT_HEADER: str = 'traceparent'
TRACESTATE_HEADER: str = 'tracestate'

# Canonical response header — Starlette is case-preserving but case-insensitive,
# so the conventional ``X-Request-Id`` casing surfaces to clients.
_RESPONSE_REQUEST_ID_HEADER: str = 'X-Request-Id'


@dataclass(frozen=True)
class IncomingCorrelation:
    """Resolved identifiers for a single inbound HTTP request.

    All fields are populated — when the caller did not supply an incoming
    value, ``extract_incoming_correlation`` substitutes a freshly generated
    one (uuid4 hex for ``request_id``, W3C-compliant random hex for
    ``trace_id``/``span_id``). ``sampled`` defaults to ``True`` per W3C spec
    "sampled flag is the recommended default for ad-hoc client spans".
    ``tracestate`` is the canonical re-formatted vendor extension string —
    empty when the incoming header was missing or fully invalid.
    """

    request_id: str
    trace_id: str
    span_id: str
    sampled: bool
    tracestate: str


@dataclass(frozen=True)
class WsTraceContext:
    """Resolved W3C trace context for a WebSocket upgrade (P1-E v2).

    WebSocket has no per-request_id; the WS handler tracks correlation via a
    locally-generated ``connection_id`` instead. This dataclass therefore
    intentionally excludes ``request_id`` so the type system makes the WS-vs-
    HTTP distinction explicit at the call site.
    """

    trace_id: str
    span_id: str
    sampled: bool
    tracestate: str


def _normalize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Lowercase-key snapshot for canonical case-insensitive lookup.

    The W3C / RFC 7230 spec treats header field names as case-insensitive,
    but ``dict`` (the common test-fixture shape) preserves the caller's
    casing. Normalising once at the boundary gives every downstream lookup a
    single canonical key, eliminating the dual fast-path / fallback branch
    that would otherwise leak the input shape's case-sensitivity through.

    Starlette already lowercases header names internally, so the dict
    comprehension is a no-op-in-key-form for the production hot path (the
    iteration cost is O(n) where n is the small ~10-15 inbound headers).
    """
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _resolve_trace_context(
    traceparent_raw: str,
    tracestate_raw: str,
) -> Tuple[str, str, bool, str]:
    """Pure W3C trace context resolver — shared by HTTP and WS callers.

    Returns ``(trace_id, span_id, sampled, tracestate)``:

    - ``traceparent`` valid → adopt ``(trace_id, span_id, sampled)``
      (downstream propagation preserves the caller's trace).
    - ``traceparent`` invalid / missing → fresh trace_id + span_id generated,
      ``sampled=True`` default. W3C spec § 3.2 mandates "treat invalid
      traceparent as if doesn't exist" — the caller's invalid header MUST
      NOT corrupt the span we generate.
    - ``tracestate`` parsed + canonical re-formatted; invalid entries are
      skipped per W3C spec § 3.3.
    """
    tracestate = format_tracestate(parse_tracestate(tracestate_raw))
    parsed = parse_traceparent(traceparent_raw) if traceparent_raw else None
    if parsed is None:
        return generate_trace_id(), generate_span_id(), True, tracestate
    trace_id, span_id, sampled = parsed
    return trace_id, span_id, sampled, tracestate


def extract_incoming_correlation(
    headers: Mapping[str, str],
) -> IncomingCorrelation:
    """Resolve OBS-1 / P1-1 / P1-A / P1-B identifiers for one inbound request.

    Behaviour by header:

    - ``X-Request-Id`` / ``request-id`` — first non-empty value wins
      (``X-Request-Id`` checked first). Missing → fresh ``uuid4().hex``.
    - ``traceparent`` — per :func:`_resolve_trace_context` (W3C § 3.2).
    - ``tracestate`` — per :func:`_resolve_trace_context` (W3C § 3.3).

    Pure function — no side effects, no ContextVar mutation, no FastAPI
    coupling. The caller drives the ``bind_*`` context managers + the
    response-header echo separately so the AST guards on each driving
    adapter (P1-1/OBS-1/P1-A/P1-B) remain valid.
    """
    lowered = _normalize_headers(headers)
    incoming_request_id = (
        lowered.get(REQUEST_ID_HEADER, '')
        or lowered.get(REQUEST_ID_HEADER_ALT, '')
    ).strip()
    request_id = incoming_request_id or _uuid.uuid4().hex

    trace_id, span_id, sampled, tracestate = _resolve_trace_context(
        lowered.get(TRACEPARENT_HEADER, '').strip(),
        lowered.get(TRACESTATE_HEADER, '').strip(),
    )

    return IncomingCorrelation(
        request_id=request_id,
        trace_id=trace_id,
        span_id=span_id,
        sampled=sampled,
        tracestate=tracestate,
    )


def _ws_header_or_query(websocket: Any, name: str) -> str:
    """WS-specific dual-transport lookup — header first, query string second.

    RFC does not define how W3C ``traceparent`` propagates across a WebSocket
    upgrade. Industry practice supports both transports, with the header
    taking precedence (RFC-strong source wins ambiguity):

    1. ``websocket.headers.get(name)`` — Starlette ``Headers`` (case-
       insensitive). Works for TestClient + reverse proxies that forward the
       upgrade headers.
    2. ``websocket.query_params.get(name)`` — works through browser
       ``new WebSocket(url)`` calls that cannot set custom request headers.

    Defensive ``try/except`` keeps the helper robust against stub objects
    that omit either attribute (test fixtures, internal driver code).
    """
    headers = getattr(websocket, 'headers', None)
    if headers is not None:
        try:
            value = (headers.get(name) or '').strip()
        except Exception:
            value = ''
        if value:
            return value
    query_params = getattr(websocket, 'query_params', None)
    if query_params is not None:
        try:
            return (query_params.get(name) or '').strip()
        except Exception:
            return ''
    return ''


def extract_ws_trace_context(websocket: Any) -> WsTraceContext:
    """Resolve W3C trace context for a WebSocket upgrade (HIGH-3 + P1-E v2).

    Honors ``traceparent`` + ``tracestate`` from both the upgrade headers and
    the URL query string (see :func:`_ws_header_or_query` for transport
    precedence). Caller MUST still handle ``connection_id`` generation +
    ``bind_connection_id`` separately — that identifier is connection-scoped
    and outside W3C's scope.

    Pure function — no FastAPI coupling. ``websocket`` is typed ``Any`` so
    the helper stays usable with both Starlette ``WebSocket`` and stub
    objects in unit tests.
    """
    trace_id, span_id, sampled, tracestate = _resolve_trace_context(
        _ws_header_or_query(websocket, TRACEPARENT_HEADER),
        _ws_header_or_query(websocket, TRACESTATE_HEADER),
    )
    return WsTraceContext(
        trace_id=trace_id,
        span_id=span_id,
        sampled=sampled,
        tracestate=tracestate,
    )


def apply_correlation_response_headers(
    response_headers: MutableMapping[str, str],
    correlation: IncomingCorrelation,
) -> None:
    """Echo OBS-1 / P1-1 / P1-A identifiers to the outbound response.

    Behaviour:

    - ``X-Request-Id`` — always set (uuid4 default when the caller did not
      supply one — OBS-1 invariant).
    - ``traceparent`` — always set, canonical W3C format (P1-1 invariant).
      Uses :func:`correlation.format_traceparent_unchecked` because the
      trace_id/span_id came from a validated parse or this module's own
      generator (zero possibility of malformed input).
    - ``tracestate`` — set only when non-empty (P1-A invariant: empty
      tracestate is spec-valid but skipping the header keeps the response
      surface minimal).
    """
    response_headers[_RESPONSE_REQUEST_ID_HEADER] = correlation.request_id
    response_headers[TRACEPARENT_HEADER] = format_traceparent_unchecked(
        correlation.trace_id,
        correlation.span_id,
        sampled=correlation.sampled,
    )
    if correlation.tracestate:
        response_headers[TRACESTATE_HEADER] = correlation.tracestate
