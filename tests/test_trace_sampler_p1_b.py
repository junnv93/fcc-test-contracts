"""P1-B — W3C Trace Sampler Policy SSOT invariants (2026-05-25).

Sealing contract:

- ``application.common.trace_sampler`` 는 OTel SDK Sampling Spec
  (https://opentelemetry.io/docs/specs/otel/trace/sdk/#sampling) 의
  ``ParentBased(root=AlwaysOn)`` default sampler 정공법.
- ``Sampler`` Protocol 은 ``domain/ports/output/trace_sampler_port.py`` 에 위치
  (hexagonal 정공법 — TestProtocolPlacement invariant 봉인 일관성).
- 구현체 3 종 (AlwaysOn / AlwaysOff / ParentBased) + DEFAULT_SAMPLER 인스턴스 +
  TRACEPARENT_SAMPLER_CTX ContextVar 는 ``application.common.trace_sampler`` 에.
- ``correlation.py`` 가 ``PARENT_SAMPLED_CTX`` ContextVar (P1-D, 2026-05-22 —
  ``Optional[bool]`` default ``None``) + ``bind_trace_context(..., sampled=None)``
  kwarg + ``current_parent_sampled() -> Optional[bool]`` + ``current_correlation_dict()``
  의 ``'parent_sampled'`` Optional[bool] 키 노출.
- ``outbound_http.build_outbound_traceparent_headers`` 의 ``sampled`` 인자
  default 는 ``None`` (sentinel) — None 시 ``current_sampler()`` 위임.
  ``True`` / ``False`` 명시 시 caller override 보존 (debugging / forced).
- AST 가드: ``outbound_http.py`` 의 옛 ``sampled: bool = True`` 시그니처
  패턴 0건 (회귀 가드).
- Domain purity: ``trace_sampler.py`` 가 infrastructure / fastapi / PySide6 /
  pyvisa / openpyxl / sqlalchemy / docx / docxtpl / pandas import 0건.

stdlib-only — dependency-free invariants.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from fcc_test_contracts.common.correlation import (  # noqa: E402
    PARENT_SAMPLED_CTX,
    bind_trace_context,
    current_correlation_dict,
    current_parent_sampled,
)
from fcc_test_contracts.common.outbound_http import (  # noqa: E402
    TRACEPARENT_HEADER,
    build_outbound_traceparent_headers,
)
from fcc_test_contracts.common.trace_sampler import (  # noqa: E402
    AlwaysOffSampler,
    AlwaysOnSampler,
    DEFAULT_SAMPLER,
    ParentBasedSampler,
    TRACEPARENT_SAMPLER_CTX,
    bind_sampler,
    current_sampler,
)
from fcc_test_contracts.common.trace_sampler_port import Sampler  # noqa: E402


# ════════════════════════════════════════════════════════════════════════════
# Phase 3.1 — Sampler Protocol + 3 구현체 단위 (8 cases)
# ════════════════════════════════════════════════════════════════════════════


class TestSamplerProtocol(unittest.TestCase):

    def test_protocol_is_runtime_checkable(self):
        """``isinstance(sampler, Sampler)`` 가 runtime 에서 동작."""
        self.assertIsInstance(AlwaysOnSampler(), Sampler)
        self.assertIsInstance(AlwaysOffSampler(), Sampler)
        self.assertIsInstance(ParentBasedSampler(root=AlwaysOnSampler()), Sampler)

    def test_module_exports_match_all(self):
        """``trace_sampler`` 모듈의 public surface 가 ``__all__`` 와 정확히 일치.

        P1-C (2026-05-25) ratchet — TraceIdRatioBased + OTEL_TRACES_SAMPLER /
        OTEL_TRACES_SAMPLER_ARG + sampler_from_env + install_sampler_from_env
        5 entry 추가.
        """
        import fcc_test_contracts.common.trace_sampler as mod
        expected = {
            'AlwaysOffSampler', 'AlwaysOnSampler', 'DEFAULT_SAMPLER',
            'OTEL_TRACES_SAMPLER', 'OTEL_TRACES_SAMPLER_ARG',
            'ParentBasedSampler', 'Sampler', 'TRACEPARENT_SAMPLER_CTX',
            'TraceIdRatioBased',
            'bind_sampler', 'current_sampler',
            'install_sampler_from_env', 'sampler_from_env',
        }
        self.assertEqual(set(mod.__all__), expected)


class TestAlwaysOnSampler(unittest.TestCase):

    def test_always_returns_true_root(self):
        """parent 없을 때 (root) True."""
        sampler = AlwaysOnSampler()
        self.assertTrue(sampler.should_sample('a' * 32, None))

    def test_always_returns_true_ignoring_parent(self):
        """parent decision 무관 True (parent_sampled=False 도 True)."""
        sampler = AlwaysOnSampler()
        self.assertTrue(sampler.should_sample('a' * 32, True))
        self.assertTrue(sampler.should_sample('a' * 32, False))


class TestAlwaysOffSampler(unittest.TestCase):

    def test_always_returns_false_root(self):
        sampler = AlwaysOffSampler()
        self.assertFalse(sampler.should_sample('a' * 32, None))

    def test_always_returns_false_ignoring_parent(self):
        sampler = AlwaysOffSampler()
        self.assertFalse(sampler.should_sample('a' * 32, True))
        self.assertFalse(sampler.should_sample('a' * 32, False))


class TestParentBasedSampler(unittest.TestCase):
    """OTel ParentBased — parent decision 보존, root 는 위임."""

    def test_root_uses_root_sampler_alwayson(self):
        """parent 없으면 root_sampler 결정 (AlwaysOn → True)."""
        sampler = ParentBasedSampler(root=AlwaysOnSampler())
        self.assertTrue(sampler.should_sample('a' * 32, None))

    def test_root_uses_root_sampler_alwaysoff(self):
        """root=AlwaysOff 시 root → False (모든 root span drop)."""
        sampler = ParentBasedSampler(root=AlwaysOffSampler())
        self.assertFalse(sampler.should_sample('a' * 32, None))

    def test_parent_sampled_preserved(self):
        """parent sampled True → True (decision 보존)."""
        sampler = ParentBasedSampler(root=AlwaysOnSampler())
        self.assertTrue(sampler.should_sample('a' * 32, True))

    def test_parent_not_sampled_preserved(self):
        """parent sampled False → False (decision 보존, root=AlwaysOn 무시)."""
        sampler = ParentBasedSampler(root=AlwaysOnSampler())
        self.assertFalse(sampler.should_sample('a' * 32, False))

    def test_root_attribute_exposed(self):
        """root sampler 접근 가능 (introspection)."""
        root = AlwaysOffSampler()
        sampler = ParentBasedSampler(root=root)
        self.assertIs(sampler.root, root)


# ════════════════════════════════════════════════════════════════════════════
# Phase 3.2 — DEFAULT_SAMPLER + ContextVar (5 cases)
# ════════════════════════════════════════════════════════════════════════════


class TestDefaultSampler(unittest.TestCase):

    def test_default_is_parent_based_always_on(self):
        """DEFAULT_SAMPLER = ParentBased(root=AlwaysOn) — OTel SDK spec default."""
        self.assertIsInstance(DEFAULT_SAMPLER, ParentBasedSampler)
        self.assertIsInstance(DEFAULT_SAMPLER.root, AlwaysOnSampler)

    def test_default_matches_p0_3_behavior_root(self):
        """root 시 DEFAULT → True — 옛 P0-3 sampled=True 행동 보존."""
        self.assertTrue(DEFAULT_SAMPLER.should_sample('a' * 32, None))

    def test_default_preserves_parent_not_sampled(self):
        """parent_sampled=False → False (parent decision 보존)."""
        self.assertFalse(DEFAULT_SAMPLER.should_sample('a' * 32, False))


class TestTraceparentSamplerContextVar(unittest.TestCase):

    def test_default_returns_default_sampler(self):
        """ContextVar override 없으면 DEFAULT_SAMPLER fallback."""
        self.assertIs(current_sampler(), DEFAULT_SAMPLER)

    def test_contextvar_override(self):
        """bind_sampler context manager 안에서 override 적용."""
        custom = AlwaysOffSampler()
        with bind_sampler(custom):
            self.assertIs(current_sampler(), custom)

    def test_contextvar_reset_after_with(self):
        """with 종료 후 default 로 복원."""
        with bind_sampler(AlwaysOffSampler()):
            pass
        self.assertIs(current_sampler(), DEFAULT_SAMPLER)


# ════════════════════════════════════════════════════════════════════════════
# Phase 3.3 — correlation.py 시그니처 확장 (4 cases)
# ════════════════════════════════════════════════════════════════════════════


class TestCorrelationParentSampledExtension(unittest.TestCase):

    def test_parent_sampled_ctx_default_none(self):
        """PARENT_SAMPLED_CTX default = None (P1-D, W3C spec § 3.2 root context).

        옛 default=True (P1-B 잔재) 영구 폐기 — producer 가 None 을 흘리지
        못해 ParentBasedSampler 의 root 위임 분기 가 사실상 dead path 였던
        결함 봉합. P1-D 이후 producer/consumer 양쪽 모두 Optional[bool] 시멘틱.
        """
        self.assertIsNone(PARENT_SAMPLED_CTX.get())
        self.assertIsNone(current_parent_sampled())

    def test_bind_trace_context_sampled_kwarg(self):
        """bind_trace_context(..., sampled=False) → PARENT_SAMPLED_CTX False."""
        with bind_trace_context('a' * 32, '1' * 16, sampled=False):
            self.assertFalse(current_parent_sampled())

    def test_bind_trace_context_default_sampled_none(self):
        """sampled kwarg 미명시 시 default None (P1-D 정공법).

        middleware 가 traceparent flags 의 sampled bit 추출 시 True/False
        명시 bind, 그 외 (root context / parse 실패 fallback) 는 None 으로
        ParentBasedSampler root 위임 trigger.
        """
        with bind_trace_context('b' * 32, '2' * 16):
            self.assertIsNone(current_parent_sampled())

    def test_correlation_dict_includes_parent_sampled(self):
        """current_correlation_dict 에 'parent_sampled' 키 포함 (Optional[bool])."""
        d = current_correlation_dict()
        self.assertIn('parent_sampled', d)
        # P1-D — Optional[bool]. default None / bind 시 True|False.
        self.assertIsInstance(d['parent_sampled'], (bool, type(None)))

    def test_bind_trace_context_resets_sampled_on_exit(self):
        """with 종료 후 PARENT_SAMPLED_CTX 복원 (default None)."""
        with bind_trace_context('c' * 32, '3' * 16, sampled=False):
            self.assertFalse(current_parent_sampled())
        # 복원 — outer default None (P1-D).
        self.assertIsNone(current_parent_sampled())


# ════════════════════════════════════════════════════════════════════════════
# Phase 3.4 — outbound_http sampler 통합 (6 cases)
# ════════════════════════════════════════════════════════════════════════════


def _extract_flags(traceparent: str) -> str:
    """W3C ``00-{trace_id}-{span_id}-{flags}`` 마지막 2 글자."""
    return traceparent.rsplit('-', 1)[1]


class TestOutboundHttpSamplerDelegation(unittest.TestCase):

    def test_root_default_sampler_sampled(self):
        """root + DEFAULT (ParentBased(AlwaysOn)) → flags=01."""
        headers = build_outbound_traceparent_headers()
        self.assertEqual(_extract_flags(headers[TRACEPARENT_HEADER]), '01')

    def test_root_with_alwaysoff_sampler_not_sampled(self):
        """root + bind_sampler(AlwaysOff) → flags=00."""
        with bind_sampler(AlwaysOffSampler()):
            headers = build_outbound_traceparent_headers()
        self.assertEqual(_extract_flags(headers[TRACEPARENT_HEADER]), '00')

    def test_parent_sampled_true_propagates_sampled(self):
        """parent trace + sampled=True → flags=01 (DEFAULT 위임 결과 True)."""
        with bind_trace_context('a' * 32, '1' * 16, sampled=True):
            headers = build_outbound_traceparent_headers()
        self.assertEqual(_extract_flags(headers[TRACEPARENT_HEADER]), '01')

    def test_parent_sampled_false_propagates_not_sampled(self):
        """parent trace + sampled=False → DEFAULT(ParentBased) 가 parent
        decision 보존 → flags=00.

        OTel ParentBased 의 핵심 — parent 가 not sampled 면 child 도 not
        sampled. 이게 신규 P1-B 동작.
        """
        with bind_trace_context('a' * 32, '1' * 16, sampled=False):
            headers = build_outbound_traceparent_headers()
        self.assertEqual(_extract_flags(headers[TRACEPARENT_HEADER]), '00')

    def test_caller_explicit_sampled_true_overrides_sampler(self):
        """caller sampled=True 명시 시 sampler 무시 (debugging/forced).

        bind_sampler(AlwaysOff) 가 있어도 caller 가 True 강제 시 flags=01.
        """
        with bind_sampler(AlwaysOffSampler()):
            headers = build_outbound_traceparent_headers(sampled=True)
        self.assertEqual(_extract_flags(headers[TRACEPARENT_HEADER]), '01')

    def test_caller_explicit_sampled_false_overrides_sampler(self):
        """caller sampled=False 명시 시 sampler 무시 (forced not-sampled).

        DEFAULT (AlwaysOn) 가 있어도 caller 가 False 강제 시 flags=00.
        """
        headers = build_outbound_traceparent_headers(sampled=False)
        self.assertEqual(_extract_flags(headers[TRACEPARENT_HEADER]), '00')


# ════════════════════════════════════════════════════════════════════════════
# Phase 3.5 — AST 가드 (옛 sampled=True 시그니처 패턴 폐기) (1 case)
# ════════════════════════════════════════════════════════════════════════════


def _read_src(rel_path: str) -> str:
    src_root = Path(__file__).parent.parent / 'src'
    return (src_root / rel_path).read_text(encoding='utf-8')


class TestAstGuards(unittest.TestCase):

    def test_outbound_http_sampled_default_is_none(self):
        """build_outbound_traceparent_headers 의 sampled kwarg default 는
        Optional[None] — 옛 ``sampled: bool = True`` 시그니처 영구 폐기.

        본 가드가 회귀 시 caller 가 sampler 위임을 우회하고 1.0 sampling rate
        하드코딩으로 회귀했음을 즉시 감지.
        """
        src = _read_src('application/common/outbound_http.py')
        tree = ast.parse(src)
        target_func: Optional[ast.FunctionDef] = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'build_outbound_traceparent_headers':
                target_func = node
                break
        self.assertIsNotNone(target_func, 'build_outbound_traceparent_headers 함수 미발견')

        # kwonly args 안에서 ``sampled`` 의 default 가 ``None`` (ast.Constant value=None) 여야 함.
        sampled_default: Optional[ast.expr] = None
        kwonly_args = target_func.args.kwonlyargs
        kw_defaults = target_func.args.kw_defaults
        for arg, default in zip(kwonly_args, kw_defaults):
            if arg.arg == 'sampled':
                sampled_default = default
                break
        self.assertIsNotNone(sampled_default, 'sampled kwarg 미발견')
        self.assertIsInstance(sampled_default, ast.Constant)
        self.assertIsNone(sampled_default.value,
                          f'sampled default 가 None 이 아님: {ast.dump(sampled_default)}')


# ════════════════════════════════════════════════════════════════════════════
# Phase 3.6 — Domain purity (3 cases)
# ════════════════════════════════════════════════════════════════════════════


class TestTraceSamplerDomainPurity(unittest.TestCase):

    def test_trace_sampler_imports_stdlib_and_domain_port_only(self):
        """trace_sampler.py 의 import set 은 stdlib + domain.ports.output.trace_sampler_port 만.

        P1-C (2026-05-25) ratchet — TraceIdRatioBased boundary check 가 ``math``
        (NaN 검출) + ``install_sampler_from_env`` default 가 ``os`` (environ)
        사용. 둘 다 stdlib.
        """
        src = _read_src('application/common/trace_sampler.py')
        tree = ast.parse(src)
        external_imports: list[str] = []
        STDLIB_ALLOWED = (
            '__future__', 'typing', 'contextvars', 'contextlib',
            'math',  # P1-C TraceIdRatioBased NaN check
            'os',    # P1-C install_sampler_from_env environ default
        )
        DOMAIN_ALLOWED = ('domain.ports.output.trace_sampler_port',)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if module in STDLIB_ALLOWED:
                    continue
                if module in DOMAIN_ALLOWED:
                    continue
                external_imports.append(f'line {node.lineno}: from {module}')
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in STDLIB_ALLOWED:
                        external_imports.append(f'line {node.lineno}: import {alias.name}')
        self.assertEqual(external_imports, [], '\n'.join(external_imports))

    def test_trace_sampler_no_forbidden_dependencies(self):
        """infrastructure / fastapi / PySide6 / pyvisa / openpyxl / sqlalchemy /
        docx / docxtpl / pandas / requests / httpx / aiohttp 0건."""
        src = _read_src('application/common/trace_sampler.py')
        forbidden = (
            'infrastructure', 'fastapi', 'PySide6', 'pyvisa',
            'openpyxl', 'sqlalchemy', 'docx', 'docxtpl', 'pandas',
            'requests', 'httpx', 'aiohttp',
        )
        violations: list[str] = []
        for token in forbidden:
            for line_no, line in enumerate(src.splitlines(), start=1):
                stripped = line.strip()
                if (stripped.startswith('import ') or stripped.startswith('from ')) and token in stripped:
                    violations.append(f'line {line_no}: {stripped}')
        self.assertEqual(violations, [], '\n'.join(violations))

    def test_trace_sampler_port_imports_stdlib_only(self):
        """domain/ports/output/trace_sampler_port.py 도메인 순수성."""
        src = _read_src('domain/ports/output/trace_sampler_port.py')
        tree = ast.parse(src)
        external_imports: list[str] = []
        STDLIB_ALLOWED = ('__future__', 'typing')
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if module in STDLIB_ALLOWED:
                    continue
                external_imports.append(f'line {node.lineno}: from {module}')
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in STDLIB_ALLOWED:
                        external_imports.append(f'line {node.lineno}: import {alias.name}')
        self.assertEqual(external_imports, [], '\n'.join(external_imports))


# ════════════════════════════════════════════════════════════════════════════
# Phase 3.7 — P0-3 backwards-compat (2 case) — 옛 caller 호출 site 100% 보존
# ════════════════════════════════════════════════════════════════════════════


class TestP03BackwardsCompat(unittest.TestCase):
    """P0-3 의 oidc/teams 호출 site 가 sampler 위임 후에도 100% 동작.

    caller 가 sampled 인자 미명시 → default None → sampler 위임 → ParentBased
    (AlwaysOn) → 옛 P0-3 의 sampled=True 동작과 완전 동일.
    """

    def test_oidc_caller_pattern_still_sampled(self):
        """oidc_principal_resolver 의 호출 pattern (existing={'Accept': 'application/json'})."""
        headers = build_outbound_traceparent_headers(
            existing={'Accept': 'application/json'},
        )
        self.assertEqual(headers['Accept'], 'application/json')
        self.assertEqual(_extract_flags(headers[TRACEPARENT_HEADER]), '01')

    def test_teams_caller_pattern_still_sampled(self):
        """teams_channel 의 호출 pattern (existing={'Content-Type': '...'} 등)."""
        headers = build_outbound_traceparent_headers(
            existing={'Content-Type': 'application/json'},
        )
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(_extract_flags(headers[TRACEPARENT_HEADER]), '01')


# ════════════════════════════════════════════════════════════════════════════
# Phase 7 (자평 fix) — Middleware sampled bit propagation runtime 효과 (5 cases)
# ════════════════════════════════════════════════════════════════════════════
#
# 본 sprint 의 ParentBasedSampler 핵심 기능 ("parent decision 보존") 이 실
# runtime 에서 활성화됨을 봉인. 옛 session_router.py 가 parse_traceparent 의
# sampled bit 를 ``_`` 로 버리고 bind_trace_context default True 만 사용했음.
# 정공법: middleware 가 sampled bit 를 bind_trace_context(..., sampled=) 로
# 명시 전달 → outbound 시 PARENT_SAMPLED_CTX 가 정확한 parent decision 노출.


class TestMiddlewareSampledBitPropagation(unittest.TestCase):

    def test_session_router_ws_destructures_sampled(self):
        """session_router.py WS handler 가 sampled bit 를 ``_ws_sampled`` 변수로
        보존함을 AST 봉인.

        옛 ``_ws_trace_id, _ws_span_id, _ = _ws_parsed`` 패턴 (sampled 폐기)
        영구 폐기 — 본 가드가 회귀 시 P1-B 가 도입한 ParentBased runtime
        효과가 다시 사라짐을 즉시 감지.

        P1-E v2 (2026-05-22) — WS handler 가 ``extract_ws_trace_context(websocket)``
        SSOT 위임으로 마이그레이션 후 destructure 도 ``_ws_sampled =
        _ws_trace.sampled`` 형태로 변경. ``_ws_parsed`` tuple 패턴 + WsTraceContext
        attribute 패턴 양쪽 모두 허용 (전자는 historic, 후자는 SSOT-after).
        둘 다 sampled bit 를 ``_ws_sampled`` 로 lift 한다는 의미는 동일.
        """
        src = _read_src('infrastructure/adapters/driving/api/session_router.py')
        legacy_destructure = '_ws_trace_id, _ws_span_id, _ws_sampled = _ws_parsed'
        ssot_attribute = '_ws_sampled = _ws_trace.sampled'
        self.assertTrue(
            legacy_destructure in src or ssot_attribute in src,
            'WS handler MUST surface sampled bit into _ws_sampled '
            f'(neither {legacy_destructure!r} nor {ssot_attribute!r} found)',
        )
        # 옛 패턴 _ws_trace_id, _ws_span_id, _ = _ws_parsed 폐기 — 새 SSOT
        # 패턴도 동일하게 ``_`` 사용 금지.
        for forbidden in (
            '_ws_trace_id, _ws_span_id, _ = _ws_parsed',
            '_ws_sampled = _ws_trace.sampled  # type: ignore',  # any masquerade
        ):
            self.assertNotIn(
                forbidden, src,
                f'Old pattern discarding sampled bit MUST be removed: {forbidden!r}',
            )

    def test_session_router_ws_passes_sampled_to_bind_trace_context(self):
        """WS handler 의 bind_trace_context 호출이 sampled=_ws_sampled kwarg 명시."""
        src = _read_src('infrastructure/adapters/driving/api/session_router.py')
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != 'bind_trace_context':
                continue
            if len(node.args) < 2:
                continue
            if not (isinstance(node.args[0], ast.Name) and node.args[0].id == '_ws_trace_id'):
                continue
            if not (isinstance(node.args[1], ast.Name) and node.args[1].id == '_ws_span_id'):
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords}
            sampled = keywords.get('sampled')
            found = isinstance(sampled, ast.Name) and sampled.id == '_ws_sampled'
        self.assertTrue(found, 'WS bind_trace_context MUST pass sampled=_ws_sampled kwarg')

    def test_session_router_http_middleware_passes_sampled(self):
        """HTTP middleware 의 bind_trace_context 호출이 sampled=sampled kwarg 명시."""
        src = _read_src('infrastructure/adapters/driving/api/session_router.py')
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != 'bind_trace_context':
                continue
            if len(node.args) < 2:
                continue
            if not (isinstance(node.args[0], ast.Name) and node.args[0].id == 'trace_id'):
                continue
            if not (isinstance(node.args[1], ast.Name) and node.args[1].id == 'span_id'):
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords}
            sampled = keywords.get('sampled')
            found = isinstance(sampled, ast.Name) and sampled.id == 'sampled'
        self.assertTrue(found, 'HTTP middleware bind_trace_context MUST pass sampled=sampled kwarg')

    def test_no_bind_trace_context_call_drops_sampled(self):
        """``bind_trace_context(...)`` 호출 site 가 sampled kwarg 미명시 시 fail.

        AST 가드: 모든 ``bind_trace_context`` 호출이 sampled kwarg 또는
        주석 화이트리스트. 본 가드가 회귀 시 누군가 middleware 에서 sampled
        를 다시 떨어뜨렸음을 즉시 감지.
        """
        src = _read_src('infrastructure/adapters/driving/api/session_router.py')
        tree = ast.parse(src)
        bare_calls: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == 'bind_trace_context':
                    kw_names = {kw.arg for kw in node.keywords}
                    if 'sampled' not in kw_names:
                        bare_calls.append(f'line {node.lineno}: bind_trace_context without sampled=')
        self.assertEqual(
            bare_calls, [],
            'bind_trace_context calls MUST pass sampled= kwarg (P1-B runtime activation):\n'
            + '\n'.join(bare_calls),
        )

    def test_runtime_parent_sampled_false_propagates_to_outbound(self):
        """End-to-end: middleware 가 sampled=False 를 bind 하면 outbound 가
        ParentBased(AlwaysOn) default sampler 위임으로 flags=00 (parent decision
        보존). 옛 동작 (default sampled=True) 시 flags=01 로 잘못 propagate 함.

        이 case 가 P1-B sprint 의 진정한 runtime 가치를 봉인 — invariant
        통과만 했던 옛 자평 결함 해소.
        """
        # middleware 시뮬레이션: parent traceparent 의 sampled bit=False 를 bind.
        with bind_trace_context('a' * 32, '1' * 16, sampled=False):
            # default sampler (ParentBased(AlwaysOn)) — parent decision 보존.
            headers = build_outbound_traceparent_headers()
        self.assertEqual(
            _extract_flags(headers[TRACEPARENT_HEADER]), '00',
            'outbound MUST honor parent sampled=False (ParentBased decision preservation)',
        )


if __name__ == '__main__':
    unittest.main()
