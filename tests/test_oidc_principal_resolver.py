import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fcc_test_contracts.common.ws_subprotocol_auth import (
    WS_BEARER_SUBPROTOCOL,
    bearer_credential_request,
    encode_bearer_subprotocols,
    parse_bearer_offer,
)
from fcc_test_contracts.common.oidc_principal_resolver import (
    BearerTokenPrincipalResolver,
    OidcJwtConfig,
)

from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact


class _Request:
    def __init__(self, authorization=''):
        self.headers = {'authorization': authorization}


class _KeyProvider:
    def get_key(self, kid):
        if kid != 'key-1':
            raise PermissionError('missing key')
        return 'public-key'


class TestOidcPrincipalResolver(unittest.TestCase):
    def test_missing_bearer_token_returns_anonymous(self):
        resolver = BearerTokenPrincipalResolver(_config(), key_provider=_KeyProvider())

        principal = resolver.resolve(_Request())

        self.assertEqual(principal.subject, 'anonymous')
        self.assertEqual(principal.permissions, frozenset())

    def test_valid_token_maps_subject_permissions_scopes_and_roles(self):
        fake_jwt = _fake_jwt({
            'sub': 'operator@example.com',
            'name': 'Operator One',
            'email': 'operator@example.com',
            'permissions': ['headless:read'],
            'scope': 'report_automation:read',
            'roles': ['operator'],
        })
        resolver = BearerTokenPrincipalResolver(
            OidcJwtConfig(
                issuer='https://login.example.com/tenant',
                audience='fcc-platform',
                jwks_uri='https://login.example.com/tenant/keys',
                role_permission_map={'operator': ('headless:control',)},
            ),
            key_provider=_KeyProvider(),
        )

        with patch.dict(sys.modules, {'jwt': fake_jwt}):
            principal = resolver.resolve(_Request('Bearer token'))

        self.assertEqual(principal.subject, 'operator@example.com')
        self.assertEqual(principal.display_name, 'Operator One')
        self.assertEqual(principal.email, 'operator@example.com')
        self.assertEqual(principal.permissions, frozenset({
            'headless:read',
            'report_automation:read',
            'headless:control',
        }))
        self.assertEqual(fake_jwt.decode_kwargs['audience'], 'fcc-platform')
        self.assertEqual(fake_jwt.decode_kwargs['issuer'], 'https://login.example.com/tenant')

    def test_invalid_token_raises_permission_error(self):
        fake_jwt = _fake_jwt(RuntimeError('bad token'))
        resolver = BearerTokenPrincipalResolver(_config(), key_provider=_KeyProvider())

        with patch.dict(sys.modules, {'jwt': fake_jwt}):
            with self.assertRaisesRegex(PermissionError, 'JWT validation failed'):
                resolver.resolve(_Request('Bearer token'))


def _config() -> OidcJwtConfig:
    return OidcJwtConfig(
        issuer='https://login.example.com/tenant',
        audience='fcc-platform',
        jwks_uri='https://login.example.com/tenant/keys',
    )


def _fake_jwt(claims_or_error):
    module = types.SimpleNamespace()
    module.decode_kwargs = {}

    def get_unverified_header(token):
        return {'kid': 'key-1'}

    def decode(token, key, algorithms, audience, issuer, leeway=0):
        module.decode_kwargs = {
            'token': token,
            'key': key,
            'algorithms': algorithms,
            'audience': audience,
            'issuer': issuer,
            'leeway': leeway,
        }
        if isinstance(claims_or_error, Exception):
            raise claims_or_error
        return claims_or_error

    module.get_unverified_header = get_unverified_header
    module.decode = decode
    return module


# ════════════════════════════════════════════════════════════════════════════
# WS bearer subprotocol auth SSOT (W3-4, 2026-08-01) — moved here (rather than
# tests/test_ws_state_lifecycle_p1_3.py) so these pure/text-scan tests land in
# the fast ``-m invariant`` CI lane via this file's ``oidc`` filename token
# (``conftest.py::_INVARIANT_FILENAME_TOKENS`` has no token matching
# ``ws_state_lifecycle``). Only the FastAPI-runtime crash-path-closure test
# stays in the WS lifecycle file, next to the lifecycle tests it exercises.
# ════════════════════════════════════════════════════════════════════════════


class _HeaderRequest:
    """Minimal ``.headers`` duck-type mirroring ``_Request`` above, but with
    an arbitrary header dict (bearer-overlay tests need more than just
    ``authorization``)."""

    def __init__(self, headers: dict):
        self.headers = headers


class TestWsBearerSubprotocolGrammar(unittest.TestCase):
    """M1 — encode/parse grammar unit tests."""

    def test_encode_blank_token_yields_empty_tuple(self):
        self.assertEqual(encode_bearer_subprotocols(''), ())
        self.assertEqual(encode_bearer_subprotocols('   '), ())
        self.assertEqual(encode_bearer_subprotocols(None), ())  # type: ignore[arg-type]

    def test_encode_nonblank_token_yields_sentinel_then_token(self):
        self.assertEqual(
            encode_bearer_subprotocols('abc.def-123'),
            (WS_BEARER_SUBPROTOCOL, 'abc.def-123'),
        )

    def test_parse_no_offer_returns_none_selected(self):
        self.assertEqual((parse_bearer_offer(None).selected, parse_bearer_offer(None).token), (None, ''))
        self.assertEqual((parse_bearer_offer('').selected, parse_bearer_offer('').token), (None, ''))
        offer = parse_bearer_offer('chat, superchat')
        self.assertEqual((offer.selected, offer.token), (None, ''))

    def test_parse_raw_header_string_extracts_sentinel_and_token(self):
        offer = parse_bearer_offer(f'{WS_BEARER_SUBPROTOCOL}, abc.def')
        self.assertEqual(offer.selected, WS_BEARER_SUBPROTOCOL)
        self.assertEqual(offer.token, 'abc.def')

    def test_parse_sequence_form_extracts_sentinel_and_token(self):
        offer = parse_bearer_offer([WS_BEARER_SUBPROTOCOL, 'abc.def'])
        self.assertEqual(offer.selected, WS_BEARER_SUBPROTOCOL)
        self.assertEqual(offer.token, 'abc.def')

    def test_parse_sentinel_without_following_token_returns_none(self):
        offer = parse_bearer_offer([WS_BEARER_SUBPROTOCOL])
        self.assertEqual((offer.selected, offer.token), (None, ''))

    def test_encode_then_parse_round_trips(self):
        offered = encode_bearer_subprotocols('  spaced.token  ')
        offer = parse_bearer_offer(list(offered))
        self.assertEqual(offer.token, 'spaced.token')
        self.assertEqual(offer.selected, WS_BEARER_SUBPROTOCOL)

    def test_representative_jwt_satisfies_rfc6455_token_grammar(self):
        """M5 axis 7 (grammar fact) — a representative JWT's charset must be
        a subset of RFC 7230 §3.2.6 ``tchar`` (the RFC 6455 §4.1 subprotocol
        value grammar). Asserted directly, not assumed."""
        representative_jwt = (
            'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.'
            'eyJzdWIiOiJvcGVyYXRvckBleGFtcGxlLmNvbSJ9.'
            'c2lnbmF0dXJlLWJ5dGVzLWJhc2U2NHVybA'
        )
        tchar_pattern = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
        self.assertTrue(
            tchar_pattern.match(representative_jwt),
            'representative JWT must satisfy the RFC 6455 subprotocol token grammar',
        )
        # Normal-form control: a value containing a real header-forbidden
        # character (space) must NOT satisfy the grammar — the assertion
        # above is not vacuously true for any string.
        self.assertIsNone(tchar_pattern.match('has a space'))


class TestWsBearerSubprotocolLiteralUniqueness(unittest.TestCase):
    """M5 axis 1 — the sentinel literal must be authored in exactly one
    place. A second literal definition (e.g. a copy-pasted handler constant)
    is the drift this guards against."""

    def test_literal_defined_exactly_once_in_src(self):
        src_root = Path(__file__).parent.parent / 'src'
        pattern = re.compile(r"['\"]fcc\.bearer\.v1['\"]")
        occurrences = []
        for py_file in src_root.rglob('*.py'):
            text = py_file.read_text(encoding='utf-8')
            for _ in pattern.finditer(text):
                occurrences.append(str(py_file))
        self.assertGreater(len(occurrences), 0, 'sentinel literal was not found at all — scan is broken')
        self.assertEqual(
            occurrences,
            [str(resolve_repo_artifact(__file__, 'src/application/common/ws_subprotocol_auth.py'))],
            f'sentinel literal must be authored in exactly one file, found: {occurrences}',
        )


class TestWsBearerCredentialRequestPrecedence(unittest.TestCase):
    """M1 §2 precedence + M5 axis 3/7 — real ``authorization`` header always
    wins over the subprotocol overlay; overlay only fills in when absent."""

    def test_real_header_wins_over_subprotocol_offer(self):
        request = _HeaderRequest({
            'authorization': 'Bearer real-token',
            'sec-websocket-protocol': f'{WS_BEARER_SUBPROTOCOL}, overlay-token',
        })
        result = bearer_credential_request(request)
        # Red if the overlay ever strips/replaces a real header — identity
        # passthrough is the contract when the real header is present.
        self.assertIs(result, request)
        self.assertEqual(result.headers.get('authorization'), 'Bearer real-token')

    def test_overlay_applies_when_real_header_absent(self):
        request = _HeaderRequest({
            'sec-websocket-protocol': f'{WS_BEARER_SUBPROTOCOL}, overlay-token',
        })
        result = bearer_credential_request(request)
        self.assertEqual(result.headers.get('authorization'), 'Bearer overlay-token')

    def test_overlay_applies_when_real_header_blank(self):
        request = _HeaderRequest({
            'authorization': '   ',
            'sec-websocket-protocol': f'{WS_BEARER_SUBPROTOCOL}, overlay-token',
        })
        result = bearer_credential_request(request)
        self.assertEqual(result.headers.get('authorization'), 'Bearer overlay-token')

    def test_no_offer_and_no_real_header_returns_identity(self):
        request = _HeaderRequest({})
        result = bearer_credential_request(request)
        self.assertIs(result, request)

    def test_overlay_preserves_other_headers_untouched(self):
        """trusted_headers mode fields must pass through — the two auth
        modes must not interfere (M1 §2)."""
        request = _HeaderRequest({
            'sec-websocket-protocol': f'{WS_BEARER_SUBPROTOCOL}, overlay-token',
            'x-fcc-subject': 'operator@example.com',
            'x-fcc-permissions': 'headless:read,headless:write',
        })
        result = bearer_credential_request(request)
        self.assertEqual(result.headers.get('x-fcc-subject'), 'operator@example.com')
        self.assertEqual(
            result.headers.get('x-fcc-permissions'), 'headless:read,headless:write',
        )

    def test_normal_form_ordinary_accept_call_is_not_flagged(self):
        """M5 normal-form control — a plain request with a real header and
        NO subprotocol offer at all resolves to identity passthrough (the
        overwhelming majority of today's traffic)."""
        request = _HeaderRequest({'authorization': 'Bearer plain-token'})
        result = bearer_credential_request(request)
        self.assertIs(result, request)

    def test_real_header_wins_regardless_of_key_case_on_a_plain_mapping(self):
        """A plain (case-sensitive) mapping with a mixed/upper-case
        ``Authorization`` key must still win over the overlay — Starlette's
        ``Headers`` already folds case, but this module's ``.get()``
        duck-type contract does not require the caller's mapping to. The
        presence-check inside ``bearer_credential_request`` looks up
        ``'authorization'`` (lower-case); a case-sensitive lookup against an
        ``'Authorization'``-keyed mapping would miss, wrongly conclude no
        real header is present, and return the (lower-case-keyed) overlay
        object instead of identity passthrough."""
        request = _HeaderRequest({
            'Authorization': 'Bearer REAL-mixed-case-token',
            'sec-websocket-protocol': f'{WS_BEARER_SUBPROTOCOL}, overlay-token',
        })
        result = bearer_credential_request(request)
        self.assertIs(result, request)
        self.assertEqual(result.headers.get('Authorization'), 'Bearer REAL-mixed-case-token')

    def test_overlay_passthrough_resolves_other_headers_case_insensitively(self):
        """M1 §2 passthrough must match Starlette ``Headers`` semantics even
        when the underlying mapping is case-sensitive: a header stored under
        a mixed-case key must still resolve via a lower-case lookup (and
        vice versa) once the bearer overlay is active."""
        request = _HeaderRequest({
            'sec-websocket-protocol': f'{WS_BEARER_SUBPROTOCOL}, overlay-token',
            'X-Fcc-Subject': 'operator@example.com',
        })
        result = bearer_credential_request(request)
        self.assertEqual(result.headers.get('x-fcc-subject'), 'operator@example.com')
        self.assertEqual(result.headers.get('X-FCC-SUBJECT'), 'operator@example.com')


class TestWsHandlerStructuralSymmetry(unittest.TestCase):
    """M2 — both WS boundaries must wire the offer-parse → credential-resolve
    → accept(subprotocol=...) sequence via the SAME SSOT calls in the SAME
    order. A one-sided fix (drift between the two handlers) is exactly what
    this guards against; each ``.index()`` lookup below also fails loudly
    (``ValueError``) if a handler drops the call outright."""

    _API_DIR = resolve_repo_artifact(__file__, 'src/infrastructure/adapters/driving/api')

    _ACCEPT_CALL = (
        'await websocket.accept(\n'
        '            subprotocol=accepted_subprotocol(\n'
        '                _ws_bearer_offer,\n'
        '                principal_resolver_active=principal_resolver is not None,\n'
        '            ),\n'
        '        )'
    )

    def test_both_handlers_call_helpers_in_the_same_order(self):
        for filename in ('platform_routes.py', 'session_router.py'):
            text = (self._API_DIR / filename).read_text(encoding='utf-8')
            idx_parse = text.index('_ws_bearer_offer = parse_bearer_offer(')
            idx_cred = text.index(
                'principal_resolver.resolve(bearer_credential_request(websocket))'
            )
            idx_accept = text.index(self._ACCEPT_CALL)
            self.assertLess(
                idx_parse, idx_cred,
                f'{filename}: offer must be parsed before credential resolution',
            )
            self.assertLess(
                idx_cred, idx_accept,
                f'{filename}: credential resolution must precede accept() negotiation',
            )

    def test_ordinary_unrelated_accept_call_does_not_confuse_the_scan(self):
        """M5 normal-form control — the scan targets the exact negotiated
        call, not any ``.accept(`` occurrence, so an unrelated accept() call
        elsewhere in either file would not silently satisfy the assertion."""
        for filename in ('platform_routes.py', 'session_router.py'):
            text = (self._API_DIR / filename).read_text(encoding='utf-8')
            self.assertEqual(
                text.count(self._ACCEPT_CALL),
                1,
                f'{filename}: negotiated accept() call must appear exactly once',
            )

    def test_accept_call_gates_on_principal_resolver_active(self):
        """M2.3 — auth-disabled deployments (``principal_resolver is None``)
        must never echo the client's offered subprotocol back: the offer
        was never routed through ``bearer_credential_request`` in that
        branch, so accepting it would falsely imply the server validated a
        credential it never touched. Both handlers must delegate this
        decision to the same SSOT helper (``accepted_subprotocol``) rather
        than re-deriving the gate locally."""
        for filename in ('platform_routes.py', 'session_router.py'):
            text = (self._API_DIR / filename).read_text(encoding='utf-8')
            self.assertIn(
                'principal_resolver_active=principal_resolver is not None',
                text,
                f'{filename}: accept() must gate the echoed subprotocol on '
                'whether a principal resolver is actually wired',
            )


class TestWsBearerSubprotocolCrossLanguageParity(unittest.TestCase):
    """M3 — ``apps/web/src/api/ws-bearer.ts`` must mirror the Python SSOT
    constant + encoding rule byte-for-byte. Reuses the established
    ``tests/support/parity.py`` helper (M1 §3 — no new convention)."""

    _TS_PATH = Path(__file__).parent.parent / 'apps' / 'web' / 'src' / 'api' / 'ws-bearer.ts'
    _PY_PATH = (
        resolve_repo_artifact(__file__, 'src/application/common/ws_subprotocol_auth.py')
    )

    def test_sentinel_constant_matches_python_ssot(self):
        from support.parity import parse_ts_export_const_strings

        self.assertTrue(self._TS_PATH.is_file(), 'ws-bearer.ts must exist')
        ts_source = self._TS_PATH.read_text(encoding='utf-8')
        ts_consts = parse_ts_export_const_strings(
            ts_source, name_pattern=r'WS_BEARER_SUBPROTOCOL',
        )
        self.assertIn(
            'WS_BEARER_SUBPROTOCOL', ts_consts,
            'ws-bearer.ts must declare export const WS_BEARER_SUBPROTOCOL',
        )
        self.assertEqual(ts_consts['WS_BEARER_SUBPROTOCOL'], WS_BEARER_SUBPROTOCOL)

    def test_encoding_rule_matches_python_ssot(self):
        """M5 axis 5 red→green: changing only the frontend constant/order
        (without touching the Python side) must fail this test."""
        from support.parity import strip_ts_comments

        ts_source = strip_ts_comments(self._TS_PATH.read_text(encoding='utf-8'))
        py_source = self._PY_PATH.read_text(encoding='utf-8')

        # Rule 1 — blank/null token encodes to empty (TS `[]` / Python `()`).
        self.assertIn('return []', ts_source)
        self.assertIn('return ()', py_source)
        # Rule 2 — non-blank token encodes sentinel-first, token-second.
        self.assertIn('return [WS_BEARER_SUBPROTOCOL, normalized]', ts_source)
        self.assertIn('return (WS_BEARER_SUBPROTOCOL, normalized)', py_source)

    def test_normal_form_unrelated_ts_file_is_not_silently_satisfying(self):
        """M5 normal-form control — the parity assertion targets
        ws-bearer.ts specifically; a file that merely imports (not
        re-declares) the constant must not silently pass the same check."""
        from support.parity import parse_ts_export_const_strings

        chamber_events = (
            Path(__file__).parent.parent / 'apps' / 'web' / 'src' / 'api' / 'chamber-events.ts'
        ).read_text(encoding='utf-8')
        self.assertNotIn(
            'WS_BEARER_SUBPROTOCOL',
            parse_ts_export_const_strings(chamber_events, name_pattern=r'WS_BEARER_SUBPROTOCOL'),
        )


class TestWsBearerAsyncApiDeclaration(unittest.TestCase):
    """M4 (contract 정정, 2026-08-01 iter1 후) — the AsyncAPI contract
    document for BOTH real-time WS surfaces must declare the bearer
    subprotocol mechanism, not just the code. A wire contract that only
    lives in the handler source (and not in the document consumers read to
    generate clients / write integrations) is not a contract.

    Originally M4 named only the platform artifact; the contract was
    corrected because M2 wires both surfaces identically, so leaving one
    surface's AsyncAPI document silent about the mechanism would be the
    contract's own asymmetry, not the code's.
    """

    _DOCS_API_DIR = resolve_repo_artifact(__file__, 'docs/api')
    _ARTIFACTS = (
        _DOCS_API_DIR / 'platform-api.asyncapi.json',
        _DOCS_API_DIR / 'session-api.asyncapi.json',
    )

    def test_both_asyncapi_artifacts_declare_the_bearer_subprotocol(self):
        import json

        checked = []
        for path in self._ARTIFACTS:
            self.assertTrue(path.is_file(), f'{path} must exist')
            document = json.loads(path.read_text(encoding='utf-8'))
            channels = document.get('channels', {})
            self.assertGreater(len(channels), 0, f'{path.name}: no channels — scan is broken')
            for channel in channels.values():
                self.assertEqual(
                    channel.get('x-fcc-ws-bearer-subprotocol'), WS_BEARER_SUBPROTOCOL,
                    f'{path.name}: channel must declare x-fcc-ws-bearer-subprotocol',
                )
            self.assertIn(
                'Sec-WebSocket-Protocol', document.get('info', {}).get('description', ''),
                f'{path.name}: info.description must describe the AuthZ mechanism',
            )
            checked.append(path.name)
        # Lower bound (M5) — the scan must have actually read both files, not
        # silently passed over a missing/empty artifact list.
        self.assertEqual(
            checked,
            ['platform-api.asyncapi.json', 'session-api.asyncapi.json'],
        )

    def test_normal_form_unrelated_channel_field_is_not_silently_satisfying(self):
        """M5 normal-form control — a channel dict that has neither the
        bearer field nor the AuthZ sentence must fail the positive
        assertions above (i.e. they are not vacuously true for any dict)."""
        benign_channel = {'address': '/some/other/channel', 'messages': {}}
        self.assertNotEqual(
            benign_channel.get('x-fcc-ws-bearer-subprotocol'), WS_BEARER_SUBPROTOCOL,
        )


if __name__ == '__main__':
    unittest.main()
