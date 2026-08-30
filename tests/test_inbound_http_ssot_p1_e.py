"""P1-E (2026-05-22) — Inbound HTTP correlation SSOT helper invariants.

Sealing contract:

- ``application.common.inbound_http`` is dependency-free (stdlib +
  ``application.common.correlation`` only). FastAPI / PySide6 / infrastructure
  imports forbidden by the broader ``TestApplicationCommonPurity`` guard.
- ``IncomingCorrelation`` is frozen + hashable (5 identifiers).
- ``extract_incoming_correlation`` parses incoming headers per W3C spec § 3.2
  (traceparent) + § 3.3 (tracestate) + OBS-1 (X-Request-Id).
- Invalid traceparent → fresh trace generated (W3C "treat as if doesn't exist").
- Invalid tracestate entries → silently dropped per spec § 3.3.
- ``apply_correlation_response_headers`` echoes the three canonical headers
  (X-Request-Id always, traceparent always, tracestate only when non-empty).

stdlib-only — no FastAPI dependency.
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact  # noqa: E402

from fcc_test_contracts.common.inbound_http import (  # noqa: E402
    REQUEST_ID_HEADER,
    REQUEST_ID_HEADER_ALT,
    TRACEPARENT_HEADER,
    TRACESTATE_HEADER,
    IncomingCorrelation,
    WsTraceContext,
    apply_correlation_response_headers,
    extract_incoming_correlation,
    extract_ws_trace_context,
)


_HEX32_RE = re.compile(r'^[0-9a-f]{32}$')
_HEX16_RE = re.compile(r'^[0-9a-f]{16}$')
_TRACEPARENT_RE = re.compile(r'^00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]$')

_SRC_ROOT = Path(__file__).parent.parent / 'src'


class TestInboundHttpSSOTPurity(unittest.TestCase):
    """Module-level purity + SSOT shape guards."""

    def test_inbound_http_dependency_free(self):
        """No FastAPI / PySide6 / infrastructure imports — application/common SSOT.

        Mirror of the architectural guard that applies to ``outbound_http.py``;
        kept inline here so a focused P1-E test run catches the regression
        without depending on the full ``test_architecture_conformance`` suite.
        """
        path = resolve_repo_artifact(__file__, 'src/application/common/inbound_http.py')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        forbidden = (
            'fastapi',
            'starlette',
            'pyside6',
            'PySide6',
            'infrastructure',
            'pyvisa',
            'pandas',
            'openpyxl',
        )
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            else:
                continue
            for name in names:
                for forbidden_prefix in forbidden:
                    if name == forbidden_prefix or name.startswith(forbidden_prefix + '.'):
                        offenders.append(name)
        self.assertEqual(
            offenders, [],
            f'inbound_http.py must stay dependency-free; offenders: {offenders}',
        )

    def test_exports_match_public_surface(self):
        """Module ``__all__`` matches the documented public API."""
        from fcc_test_contracts.common import inbound_http
        self.assertEqual(
            set(inbound_http.__all__),
            {
                'IncomingCorrelation',
                'REQUEST_ID_HEADER',
                'REQUEST_ID_HEADER_ALT',
                'TRACEPARENT_HEADER',
                'TRACESTATE_HEADER',
                'WsTraceContext',
                'apply_correlation_response_headers',
                'extract_incoming_correlation',
                'extract_ws_trace_context',
            },
        )

    def test_header_constants_lowercase(self):
        """Header lookup constants must be lowercase — Starlette already
        lowercases incoming header names, so the SSOT must agree to avoid
        silent case-sensitivity regressions."""
        self.assertEqual(REQUEST_ID_HEADER, REQUEST_ID_HEADER.lower())
        self.assertEqual(REQUEST_ID_HEADER_ALT, REQUEST_ID_HEADER_ALT.lower())
        self.assertEqual(TRACEPARENT_HEADER, TRACEPARENT_HEADER.lower())
        self.assertEqual(TRACESTATE_HEADER, TRACESTATE_HEADER.lower())


class TestIncomingCorrelationValueSemantics(unittest.TestCase):

    def test_frozen_and_hashable(self):
        correlation = IncomingCorrelation(
            request_id='r',
            trace_id='a' * 32,
            span_id='b' * 16,
            sampled=True,
            tracestate='',
        )
        with self.assertRaises(AttributeError):
            correlation.request_id = 'mutated'  # type: ignore[misc]
        # Hashable — important for cache/set membership semantics.
        _ = hash(correlation)

    def test_equality_by_value(self):
        a = IncomingCorrelation('r', 'a' * 32, 'b' * 16, True, 'dd=p:1')
        b = IncomingCorrelation('r', 'a' * 32, 'b' * 16, True, 'dd=p:1')
        self.assertEqual(a, b)


class TestExtractIncomingCorrelationRequestId(unittest.TestCase):

    def test_uuid4_generated_when_missing(self):
        result = extract_incoming_correlation({})
        self.assertTrue(
            _HEX32_RE.match(result.request_id),
            f'OBS-1 default must be uuid4 hex 32; got {result.request_id!r}',
        )

    def test_incoming_x_request_id_honored(self):
        result = extract_incoming_correlation(
            {'x-request-id': 'caller-provided-abc'},
        )
        self.assertEqual(result.request_id, 'caller-provided-abc')

    def test_incoming_x_request_id_takes_precedence(self):
        """When both ``X-Request-Id`` and ``Request-Id`` are present, the
        former wins (matches the Session API OBS-1 precedence)."""
        result = extract_incoming_correlation({
            'x-request-id': 'preferred',
            'request-id': 'fallback',
        })
        self.assertEqual(result.request_id, 'preferred')

    def test_request_id_alt_used_when_primary_missing(self):
        result = extract_incoming_correlation({'request-id': 'fallback-only'})
        self.assertEqual(result.request_id, 'fallback-only')

    def test_case_insensitive_header_lookup_via_manual_dict(self):
        """Plain dict with mixed-case keys still resolves — Starlette
        normalises to lowercase but test fixtures often use ``X-Request-Id``."""
        result = extract_incoming_correlation({'X-Request-Id': 'cased-abc'})
        self.assertEqual(result.request_id, 'cased-abc')

    def test_empty_request_id_string_treated_as_missing(self):
        result = extract_incoming_correlation({'x-request-id': '   '})
        self.assertTrue(_HEX32_RE.match(result.request_id))


class TestExtractIncomingCorrelationTraceparent(unittest.TestCase):

    def test_valid_traceparent_sampled(self):
        header = '00-0af7651916cd43dd8448eb211c80319c-b9c7c989f97918e1-01'
        result = extract_incoming_correlation({'traceparent': header})
        self.assertEqual(result.trace_id, '0af7651916cd43dd8448eb211c80319c')
        self.assertEqual(result.span_id, 'b9c7c989f97918e1')
        self.assertIs(result.sampled, True)

    def test_valid_traceparent_not_sampled(self):
        header = '00-0af7651916cd43dd8448eb211c80319c-b9c7c989f97918e1-00'
        result = extract_incoming_correlation({'traceparent': header})
        self.assertIs(result.sampled, False)

    def test_invalid_traceparent_generates_fresh_trace(self):
        """W3C spec § 3.2 — invalid traceparent MUST be treated as if it
        doesn't exist. Caller's bad header MUST NOT poison the generated span."""
        result = extract_incoming_correlation({'traceparent': 'bogus-not-a-traceparent'})
        self.assertTrue(_HEX32_RE.match(result.trace_id))
        self.assertTrue(_HEX16_RE.match(result.span_id))
        self.assertIs(result.sampled, True)

    def test_missing_traceparent_generates_fresh_trace(self):
        result = extract_incoming_correlation({})
        self.assertTrue(_HEX32_RE.match(result.trace_id))
        self.assertTrue(_HEX16_RE.match(result.span_id))

    def test_unknown_version_treated_as_invalid(self):
        """W3C spec § 3.2 — versions other than ``00`` MUST be treated as if
        the header doesn't exist."""
        header = 'ff-0af7651916cd43dd8448eb211c80319c-b9c7c989f97918e1-01'
        result = extract_incoming_correlation({'traceparent': header})
        # Fresh trace generated.
        self.assertNotEqual(result.trace_id, '0af7651916cd43dd8448eb211c80319c')

    def test_all_zero_trace_id_treated_as_invalid(self):
        header = '00-' + '0' * 32 + '-b9c7c989f97918e1-01'
        result = extract_incoming_correlation({'traceparent': header})
        self.assertNotEqual(result.trace_id, '0' * 32)


class TestExtractIncomingCorrelationTracestate(unittest.TestCase):

    def test_valid_vendor_entry_preserved(self):
        result = extract_incoming_correlation({
            'tracestate': 'dd=p:abc,rojo=1',
        })
        self.assertEqual(result.tracestate, 'dd=p:abc,rojo=1')

    def test_empty_tracestate_returns_empty(self):
        result = extract_incoming_correlation({})
        self.assertEqual(result.tracestate, '')

    def test_invalid_tracestate_silently_dropped(self):
        """W3C spec § 3.3 — invalid entries are skipped, the rest survives.

        An entirely invalid header collapses to empty (no echo).
        """
        result = extract_incoming_correlation({'tracestate': 'Bad=1'})
        self.assertEqual(result.tracestate, '')

    def test_partially_invalid_tracestate_keeps_valid_entries(self):
        result = extract_incoming_correlation({
            'tracestate': 'dd=p:abc,Bad=1,rojo=1',
        })
        # Spec: invalid entry skipped, valid entries preserved.
        self.assertEqual(result.tracestate, 'dd=p:abc,rojo=1')


class TestApplyCorrelationResponseHeaders(unittest.TestCase):

    def _correlation(self, **overrides):
        defaults = {
            'request_id': 'rid-abc',
            'trace_id': '0af7651916cd43dd8448eb211c80319c',
            'span_id': 'b9c7c989f97918e1',
            'sampled': True,
            'tracestate': '',
        }
        defaults.update(overrides)
        return IncomingCorrelation(**defaults)

    def test_request_id_always_echoed(self):
        headers: dict[str, str] = {}
        apply_correlation_response_headers(headers, self._correlation())
        self.assertEqual(headers['X-Request-Id'], 'rid-abc')

    def test_traceparent_always_echoed_canonical(self):
        headers: dict[str, str] = {}
        apply_correlation_response_headers(headers, self._correlation())
        self.assertTrue(_TRACEPARENT_RE.match(headers['traceparent']))
        self.assertEqual(
            headers['traceparent'],
            '00-0af7651916cd43dd8448eb211c80319c-b9c7c989f97918e1-01',
        )

    def test_traceparent_sampled_zero_when_not_sampled(self):
        headers: dict[str, str] = {}
        apply_correlation_response_headers(
            headers, self._correlation(sampled=False),
        )
        self.assertTrue(headers['traceparent'].endswith('-00'))

    def test_empty_tracestate_not_echoed(self):
        """P1-A behaviour — empty tracestate is spec-valid but skipping the
        response header keeps the surface minimal."""
        headers: dict[str, str] = {}
        apply_correlation_response_headers(headers, self._correlation())
        self.assertNotIn('tracestate', headers)

    def test_non_empty_tracestate_echoed(self):
        headers: dict[str, str] = {}
        apply_correlation_response_headers(
            headers, self._correlation(tracestate='dd=p:abc,rojo=1'),
        )
        self.assertEqual(headers['tracestate'], 'dd=p:abc,rojo=1')


class TestSSOTAdoptionByCallers(unittest.TestCase):
    """AST guard — both driving adapters must delegate to the helper SSOT."""

    def _read(self, rel: str) -> str:
        return (_SRC_ROOT / rel).read_text(encoding='utf-8')

    def test_session_router_imports_helper(self):
        src = self._read('infrastructure/adapters/driving/api/session_router.py')
        self.assertIn('from application.common.inbound_http import', src)
        self.assertIn('extract_incoming_correlation', src)
        self.assertIn('apply_correlation_response_headers', src)

    def test_headless_routes_imports_helper(self):
        src = self._read('infrastructure/adapters/driving/api/headless_routes.py')
        self.assertIn('from application.common.inbound_http import', src)
        self.assertIn('extract_incoming_correlation', src)
        self.assertIn('apply_correlation_response_headers', src)

    def test_no_inline_traceparent_parsing_in_session_router(self):
        """Session router HTTP middleware + WS handler no longer carry inline
        ``parse_traceparent`` / ``parse_tracestate`` calls — the helper SSOT
        owns both transports (P1-E v2)."""
        src = self._read('infrastructure/adapters/driving/api/session_router.py')
        self.assertNotIn('parse_traceparent(', src)
        self.assertNotIn('parse_tracestate(', src)

    def test_session_router_ws_handler_uses_ws_ssot(self):
        """WS handler must delegate header/query dual-transport lookup +
        canonical parsing to ``extract_ws_trace_context`` (P1-E v2)."""
        src = self._read('infrastructure/adapters/driving/api/session_router.py')
        self.assertIn('extract_ws_trace_context', src)
        # WS handler should not reach into ``websocket.query_params.get`` for
        # traceparent/tracestate anymore — the helper owns that lookup.
        self.assertNotIn("query_params.get('traceparent')", src)
        self.assertNotIn("query_params.get('tracestate')", src)


class TestExtractWsTraceContext(unittest.TestCase):
    """``extract_ws_trace_context`` SSOT — WS-specific dual-transport variant."""

    class _StubWebSocket:
        """Minimal WebSocket stand-in carrying ``headers`` + ``query_params``
        — both expose a ``get(name) -> Optional[str]`` matching the Starlette
        contract used in production."""

        class _MappingProxy:
            def __init__(self, data: dict[str, str]) -> None:
                self._data = data

            def get(self, name, default=None):
                lowered = name.lower()
                for key, value in self._data.items():
                    if key.lower() == lowered:
                        return value
                return default

        def __init__(self, *, headers=None, query=None):
            self.headers = self._MappingProxy(headers or {})
            self.query_params = self._MappingProxy(query or {})

    def test_ws_trace_context_is_frozen_and_hashable(self):
        ctx = WsTraceContext(
            trace_id='a' * 32, span_id='b' * 16, sampled=True, tracestate='',
        )
        with self.assertRaises(AttributeError):
            ctx.trace_id = 'mutated'  # type: ignore[misc]
        _ = hash(ctx)

    def test_ws_trace_context_does_not_carry_request_id(self):
        """WS uses connection-scoped ``connection_id`` — request_id MUST NOT
        leak into the WS dataclass so the type system makes the WS-vs-HTTP
        distinction explicit."""
        self.assertFalse(hasattr(WsTraceContext, 'request_id'))

    def test_header_traceparent_takes_precedence_over_query(self):
        """RFC-strong source (header) wins when both transports present."""
        header_value = '00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-1111111111111111-01'
        query_value = '00-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-2222222222222222-01'
        ws = self._StubWebSocket(
            headers={'traceparent': header_value},
            query={'traceparent': query_value},
        )
        ctx = extract_ws_trace_context(ws)
        self.assertEqual(ctx.trace_id, 'a' * 32)

    def test_query_string_used_when_header_missing(self):
        """Browser ``new WebSocket(url)`` cannot set headers — query falls
        back to honored W3C transport."""
        query_value = '00-cccccccccccccccccccccccccccccccc-3333333333333333-01'
        ws = self._StubWebSocket(query={'traceparent': query_value})
        ctx = extract_ws_trace_context(ws)
        self.assertEqual(ctx.trace_id, 'c' * 32)
        self.assertIs(ctx.sampled, True)

    def test_missing_both_generates_fresh_trace(self):
        ws = self._StubWebSocket()
        ctx = extract_ws_trace_context(ws)
        self.assertTrue(_HEX32_RE.match(ctx.trace_id))
        self.assertTrue(_HEX16_RE.match(ctx.span_id))
        self.assertIs(ctx.sampled, True)
        self.assertEqual(ctx.tracestate, '')

    def test_invalid_header_falls_through_to_query(self):
        """If the header transport carries an invalid traceparent, the helper
        does NOT fall through to the query string — header wins ambiguity AND
        the invalid-as-doesn't-exist spec is applied locally. (Falling through
        to query would invert RFC priority and let an attacker inject a trace
        via query when the legitimate header is malformed.)"""
        ws = self._StubWebSocket(
            headers={'traceparent': 'malformed-header'},
            query={'traceparent':
                   '00-dddddddddddddddddddddddddddddddd-4444444444444444-01'},
        )
        ctx = extract_ws_trace_context(ws)
        # Header transport returned a non-empty value first — helper used it,
        # parse_traceparent rejected it, fresh trace generated. Query string
        # is NOT consulted (header precedence).
        self.assertNotEqual(ctx.trace_id, 'd' * 32)

    def test_invalid_traceparent_generates_fresh_trace(self):
        ws = self._StubWebSocket(headers={'traceparent': 'malformed'})
        ctx = extract_ws_trace_context(ws)
        self.assertTrue(_HEX32_RE.match(ctx.trace_id))

    def test_tracestate_header_precedence(self):
        ws = self._StubWebSocket(
            headers={'tracestate': 'dd=p:hdr'},
            query={'tracestate': 'rojo=qry'},
        )
        ctx = extract_ws_trace_context(ws)
        self.assertEqual(ctx.tracestate, 'dd=p:hdr')

    def test_tracestate_invalid_silently_dropped(self):
        ws = self._StubWebSocket(headers={'tracestate': 'Bad=1'})
        ctx = extract_ws_trace_context(ws)
        self.assertEqual(ctx.tracestate, '')

    def test_robust_to_missing_attributes(self):
        """Stub object with no ``headers`` or ``query_params`` MUST NOT crash —
        unit-test fixtures sometimes pass minimal stubs."""
        class _Empty:
            pass
        ctx = extract_ws_trace_context(_Empty())
        # Falls back to generated trace.
        self.assertTrue(_HEX32_RE.match(ctx.trace_id))

    def test_ws_handler_destructures_attributes_in_order(self):
        """The session_router WS handler still destructures into the legacy
        local variable names (``_ws_trace_id`` / ``_ws_span_id`` / ``_ws_sampled``
        / ``_ws_tracestate``) — guard against drift since other tests (P1-B
        sampled bit AST) depend on those literal names."""
        src = (_SRC_ROOT / 'infrastructure' / 'adapters' / 'driving' / 'api'
               / 'session_router.py').read_text(encoding='utf-8')
        for marker in (
            '_ws_trace_id = _ws_trace.trace_id',
            '_ws_span_id = _ws_trace.span_id',
            '_ws_sampled = _ws_trace.sampled',
            '_ws_tracestate = _ws_trace.tracestate',
        ):
            self.assertIn(marker, src)


if __name__ == '__main__':
    unittest.main()
