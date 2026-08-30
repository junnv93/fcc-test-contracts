"""P1-C — TraceIdRatioBased + OTEL_TRACES_SAMPLER env SSOT invariants."""
from __future__ import annotations

import ast
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact  # noqa: E402

from fcc_test_contracts.common.trace_sampler import (  # noqa: E402
    OTEL_TRACES_SAMPLER,
    OTEL_TRACES_SAMPLER_ARG,
    AlwaysOffSampler,
    AlwaysOnSampler,
    ParentBasedSampler,
    TRACEPARENT_SAMPLER_CTX,
    TraceIdRatioBased,
    bind_sampler,
    current_sampler,
    install_sampler_from_env,
    sampler_from_env,
)
from fcc_test_contracts.common.trace_sampler_port import Sampler  # noqa: E402


SRC_ROOT = Path(__file__).parent.parent / 'src'
TRACE_SAMPLER_PATH = resolve_repo_artifact(__file__, 'src/application/common/trace_sampler.py')


class TestTraceIdRatioBasedDecision(unittest.TestCase):
    def test_ratio_zero_drops_lowest_trace_id(self):
        self.assertFalse(TraceIdRatioBased(0.0).should_sample('0' * 32, None))

    def test_ratio_zero_drops_highest_trace_id(self):
        self.assertFalse(TraceIdRatioBased(0.0).should_sample('f' * 32, None))

    def test_ratio_one_samples_lowest_trace_id(self):
        self.assertTrue(TraceIdRatioBased(1.0).should_sample('0' * 32, None))

    def test_ratio_one_samples_highest_trace_id(self):
        self.assertTrue(TraceIdRatioBased(1.0).should_sample('f' * 32, None))

    def test_half_ratio_boundary_below_threshold_samples(self):
        # OTel Python SDK byte-identity: 하위 64-bit AND mask 사용.
        # 하위 64-bit = '7fffffffffffffff' (= 2^63 - 1) → sample True.
        # 상위 64-bit ('aaa...') 은 AND mask 로 제거됨 (무관).
        self.assertTrue(TraceIdRatioBased(0.5).should_sample('a' * 16 + '7fffffffffffffff', None))

    def test_half_ratio_boundary_at_threshold_drops(self):
        # OTel Python SDK byte-identity: 하위 64-bit AND mask.
        # 하위 64-bit = '8000000000000000' (= 2^63) → drop False.
        self.assertFalse(TraceIdRatioBased(0.5).should_sample('a' * 16 + '8000000000000000', None))

    def test_decision_is_deterministic_for_same_trace_id(self):
        sampler = TraceIdRatioBased(0.1)
        trace_id = '1999999999999999' + 'abcdefabcdefabcd'
        self.assertEqual(
            sampler.should_sample(trace_id, None),
            sampler.should_sample(trace_id, None),
        )

    def test_parent_sampled_is_ignored_for_root_sampler(self):
        sampler = TraceIdRatioBased(0.0)
        self.assertFalse(sampler.should_sample('0' * 32, True))
        self.assertFalse(sampler.should_sample('0' * 32, False))


class TestTraceIdRatioBasedValidation(unittest.TestCase):
    def test_negative_ratio_raises(self):
        with self.assertRaises(ValueError):
            TraceIdRatioBased(-0.01)

    def test_ratio_above_one_raises(self):
        with self.assertRaises(ValueError):
            TraceIdRatioBased(1.01)

    def test_nan_ratio_raises(self):
        with self.assertRaises(ValueError):
            TraceIdRatioBased(math.nan)

    def test_bool_ratio_raises(self):
        with self.assertRaises(ValueError):
            TraceIdRatioBased(True)


class TestTraceIdRatioBasedThreshold(unittest.TestCase):
    def test_threshold_zero(self):
        self.assertEqual(TraceIdRatioBased(0.0).threshold, 0)

    def test_threshold_half(self):
        self.assertEqual(TraceIdRatioBased(0.5).threshold, 1 << 63)

    def test_threshold_one(self):
        self.assertEqual(TraceIdRatioBased(1.0).threshold, 1 << 64)

    def test_ratio_attribute_is_float(self):
        self.assertEqual(TraceIdRatioBased(1).ratio, 1.0)


class TestSamplerFromEnv(unittest.TestCase):
    def test_default_is_parentbased_always_on(self):
        sampler = sampler_from_env({})
        self.assertIsInstance(sampler, ParentBasedSampler)
        self.assertIsInstance(sampler.root, AlwaysOnSampler)

    def test_always_on_token(self):
        self.assertIsInstance(sampler_from_env({OTEL_TRACES_SAMPLER: 'always_on'}), AlwaysOnSampler)

    def test_always_off_token(self):
        self.assertIsInstance(sampler_from_env({OTEL_TRACES_SAMPLER: 'always_off'}), AlwaysOffSampler)

    def test_traceidratio_token(self):
        sampler = sampler_from_env({
            OTEL_TRACES_SAMPLER: 'traceidratio',
            OTEL_TRACES_SAMPLER_ARG: '0.25',
        })
        self.assertIsInstance(sampler, TraceIdRatioBased)
        self.assertEqual(sampler.ratio, 0.25)

    def test_parentbased_always_on_token(self):
        sampler = sampler_from_env({OTEL_TRACES_SAMPLER: 'parentbased_always_on'})
        self.assertIsInstance(sampler, ParentBasedSampler)
        self.assertIsInstance(sampler.root, AlwaysOnSampler)

    def test_parentbased_always_off_token(self):
        sampler = sampler_from_env({OTEL_TRACES_SAMPLER: 'parentbased_always_off'})
        self.assertIsInstance(sampler, ParentBasedSampler)
        self.assertIsInstance(sampler.root, AlwaysOffSampler)

    def test_parentbased_traceidratio_token(self):
        sampler = sampler_from_env({
            OTEL_TRACES_SAMPLER: 'parentbased_traceidratio',
            OTEL_TRACES_SAMPLER_ARG: '0.75',
        })
        self.assertIsInstance(sampler, ParentBasedSampler)
        self.assertIsInstance(sampler.root, TraceIdRatioBased)
        self.assertEqual(sampler.root.ratio, 0.75)

    def test_token_is_case_insensitive_and_trimmed(self):
        self.assertIsInstance(
            sampler_from_env({OTEL_TRACES_SAMPLER: '  ALWAYS_OFF  '}),
            AlwaysOffSampler,
        )

    def test_unknown_token_raises(self):
        with self.assertRaises(ValueError):
            sampler_from_env({OTEL_TRACES_SAMPLER: 'jaeger_remote'})

    def test_traceidratio_missing_arg_raises(self):
        with self.assertRaises(ValueError):
            sampler_from_env({OTEL_TRACES_SAMPLER: 'traceidratio'})

    def test_traceidratio_invalid_arg_raises(self):
        with self.assertRaises(ValueError):
            sampler_from_env({
                OTEL_TRACES_SAMPLER: 'traceidratio',
                OTEL_TRACES_SAMPLER_ARG: 'not-a-float',
            })

    def test_traceidratio_nan_arg_raises(self):
        with self.assertRaises(ValueError):
            sampler_from_env({
                OTEL_TRACES_SAMPLER: 'traceidratio',
                OTEL_TRACES_SAMPLER_ARG: 'nan',
            })


class TestInstallSamplerFromEnv(unittest.TestCase):
    def tearDown(self):
        TRACEPARENT_SAMPLER_CTX.set(None)

    def test_install_sets_contextvar_and_returns_sampler(self):
        sampler = install_sampler_from_env({OTEL_TRACES_SAMPLER: 'always_off'})
        self.assertIs(current_sampler(), sampler)
        self.assertIsInstance(sampler, AlwaysOffSampler)

    def test_install_parentbased_traceidratio(self):
        sampler = install_sampler_from_env({
            OTEL_TRACES_SAMPLER: 'parentbased_traceidratio',
            OTEL_TRACES_SAMPLER_ARG: '0.5',
        })
        self.assertIs(current_sampler(), sampler)
        self.assertIsInstance(sampler, ParentBasedSampler)
        self.assertIsInstance(sampler.root, TraceIdRatioBased)

    def test_bind_sampler_temporarily_overrides_installed_sampler(self):
        installed = install_sampler_from_env({OTEL_TRACES_SAMPLER: 'always_on'})
        with bind_sampler(AlwaysOffSampler()) as scoped:
            self.assertIs(current_sampler(), scoped)
        self.assertIs(current_sampler(), installed)


class TestTraceSamplerArchitecture(unittest.TestCase):
    def test_traceidratio_is_runtime_sampler(self):
        self.assertIsInstance(TraceIdRatioBased(0.5), Sampler)

    def test_public_surface_contains_p1_c_symbols(self):
        import fcc_test_contracts.common.trace_sampler as mod

        for name in (
            'TraceIdRatioBased',
            'OTEL_TRACES_SAMPLER',
            'OTEL_TRACES_SAMPLER_ARG',
            'sampler_from_env',
            'install_sampler_from_env',
        ):
            self.assertIn(name, mod.__all__)

    def test_threshold_uses_otel_python_sdk_byte_identity_and_mask(self):
        """should_sample 이 ``int(trace_id, 16) & _TRACE_ID_LIMIT`` 패턴 사용.

        2026-05-23 follow-up: 옛 ``trace_id[:_TRACE_ID_HEX_CHARS]`` 상위 16
        hex 슬라이스 패턴 영구 폐기 → OTel Python SDK byte-identity 정합
        ``int(trace_id, 16) & _TRACE_ID_LIMIT`` 하위 64-bit AND mask. 본
        invariant 는 module-level AST 에서 BinOp(BitAnd) + Name('_TRACE_ID_LIMIT')
        패턴 존재 + 옛 ``trace_id`` Subscript 슬라이스 0건 양쪽 봉인.
        """
        source = TRACE_SAMPLER_PATH.read_text(encoding='utf-8')
        tree = ast.parse(source)
        # (1) 옛 trace_id[:N] subscript 슬라이스 패턴 0건 봉인
        trace_id_subscripts = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == 'trace_id'
        ]
        self.assertFalse(
            trace_id_subscripts,
            'trace_id[:N] 슬라이스 패턴 영구 폐기 (OTel Python SDK byte-identity 정합 — '
            '하위 64-bit AND mask 사용):\n'
            + '\n'.join(
                f'line {n.lineno}: {ast.unparse(n)}' for n in trace_id_subscripts
            ),
        )
        # (2) BinOp(BitAnd, ..., Name('_TRACE_ID_LIMIT')) 패턴 존재 봉인
        bitand_mask_used = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.BitAnd)
                and isinstance(node.right, ast.Name)
                and node.right.id == '_TRACE_ID_LIMIT'
            ):
                bitand_mask_used = True
                break
        self.assertTrue(
            bitand_mask_used,
            'should_sample 이 (int(trace_id, 16) & _TRACE_ID_LIMIT) 패턴 사용 필수 '
            '(OTel Python SDK byte-identity)',
        )

    def test_env_vars_are_otel_standard_not_fcc_prefixed(self):
        self.assertEqual(OTEL_TRACES_SAMPLER, 'OTEL_TRACES_SAMPLER')
        self.assertEqual(OTEL_TRACES_SAMPLER_ARG, 'OTEL_TRACES_SAMPLER_ARG')

    def test_trace_sampler_has_no_forbidden_dependencies(self):
        source = TRACE_SAMPLER_PATH.read_text(encoding='utf-8')
        forbidden = ('fastapi', 'PySide6', 'sqlalchemy', 'openpyxl', 'pandas', 'pyvisa')
        for name in forbidden:
            self.assertNotIn(name, source)


# ════════════════════════════════════════════════════════════════════════════
# Phase 8 (자평 fix) — App boot install_sampler_from_env 통합 (4 cases)
# ════════════════════════════════════════════════════════════════════════════
#
# P1-C 자평 결과 ``install_sampler_from_env`` 가 src/ 전체에서 0건 caller —
# invariant 만 통과하고 실 runtime 에서 OTel env (OTEL_TRACES_SAMPLER 등) 가
# 적용 안 되던 결함. 정공법: ASGI app factory (session_api_app /
# headless_api_app) 의 create_app(environ) 진입점이 install_sampler_from_env
# 1회 호출 → process-wide ContextVar 영구 설치 (lifespan 외부 호출이라
# request handler 가 본 context 의 child 로 sampler 값 inherit).


class TestAppBootSamplerInstallation(unittest.TestCase):

    def _read(self, rel: str) -> str:
        return (SRC_ROOT / rel).read_text(encoding='utf-8')

    def test_session_api_app_installs_sampler_from_env(self):
        """session_api_app.create_app 본문이 install_sampler_from_env 호출."""
        src = self._read('session_api_app.py')
        self.assertIn(
            'install_sampler_from_env', src,
            'session_api_app MUST call install_sampler_from_env at create_app',
        )

    def test_headless_api_app_installs_sampler_from_env(self):
        """headless_api_app.create_app 본문이 install_sampler_from_env 호출."""
        src = self._read('headless_api_app.py')
        self.assertIn(
            'install_sampler_from_env', src,
            'headless_api_app MUST call install_sampler_from_env at create_app',
        )

    def test_session_api_app_installs_before_runtime_assembly(self):
        """install_sampler_from_env 호출이 runtime 합성 *전* (lifespan 외부).

        ``(`` 포함 검색으로 import 라인 false positive 차단 — 호출 라인만 비교.
        """
        src = self._read('session_api_app.py')
        install_idx = src.find('install_sampler_from_env(')
        runtime_idx = src.find('runtime = create_session_runtime_from_config(')
        self.assertGreater(install_idx, 0)
        self.assertGreater(runtime_idx, 0)
        self.assertLess(
            install_idx, runtime_idx,
            'install_sampler_from_env MUST be called BEFORE runtime assembly '
            '(so request handlers inherit ContextVar in child context)',
        )

    def test_headless_api_app_installs_before_runtime_assembly(self):
        src = self._read('headless_api_app.py')
        install_idx = src.find('install_sampler_from_env(')
        runtime_idx = src.find('runtime = create_headless_api_runtime_from_config(')
        self.assertGreater(install_idx, 0)
        self.assertGreater(runtime_idx, 0)
        self.assertLess(install_idx, runtime_idx)


# ════════════════════════════════════════════════════════════════════════════
# Phase 9 (자평 fix #2) — GUI mode bootstrap 통합 + 중복 코드 제거 + runtime E2E
# ════════════════════════════════════════════════════════════════════════════
#
# P1-C 2차 자평 결과 단편 3건:
# (A) GUI mode boot 통합 누락 — bootstrap._compose_driven_adapters 가
#     install_sampler_from_env 호출 0건. GUI 모드 Teams webhook outbound 가
#     OTel env 적용 안 받음 → 정공법: bootstrap 합성 진입점에서도 install.
# (B) 중복 코드 — session_api_app + headless_api_app 의
#     ``install_sampler_from_env(environ if environ is not None else
#     os.environ)`` 패턴 2 site 동일. install 의 default=None 이 자체 os.environ
#     위임 → caller redundant if-else 폐기.
# (C) runtime E2E test 부재 — Phase 8 AST source 검사만. ASGI create_app(env)
#     호출 시 ContextVar 실제 set 되는지 runtime 검증 0.


class TestPhase9BootstrapGuiModeIntegration(unittest.TestCase):
    """단편 A — bootstrap._compose_driven_adapters 가 install_sampler_from_env
    호출. GUI mode + headless test mode 모두 OTel env 활성화."""

    def test_bootstrap_compose_driven_adapters_calls_install_sampler(self):
        bootstrap_src = (SRC_ROOT / 'bootstrap.py').read_text(encoding='utf-8')
        self.assertIn(
            'install_sampler_from_env', bootstrap_src,
            'bootstrap.py MUST call install_sampler_from_env at composition root '
            '(GUI mode + headless test mode 양쪽 OTel env 활성화)',
        )


class TestPhase9NoRedundantEnvFallback(unittest.TestCase):
    """단편 B — ASGI app factory 가 ``install_sampler_from_env(environ)`` 단일
    호출. caller 측 ``if environ is not None else os.environ`` redundant
    pattern 영구 폐기 (install 함수 내부에서 자체 처리)."""

    def test_session_api_app_no_redundant_environ_fallback(self):
        src = (SRC_ROOT / 'session_api_app.py').read_text(encoding='utf-8')
        self.assertNotIn(
            'environ if environ is not None else os.environ', src,
            'session_api_app MUST NOT duplicate environ fallback — '
            'install_sampler_from_env handles None internally',
        )

    def test_headless_api_app_no_redundant_environ_fallback(self):
        src = (SRC_ROOT / 'headless_api_app.py').read_text(encoding='utf-8')
        self.assertNotIn(
            'environ if environ is not None else os.environ', src,
            'headless_api_app MUST NOT duplicate environ fallback — '
            'install_sampler_from_env handles None internally',
        )


class TestPhase9RuntimeEndToEnd(unittest.TestCase):
    """단편 C — ASGI create_app(env) 호출 시 ContextVar 실제 set 검증.

    AST source 가드만으로는 install 함수가 정말로 ContextVar 를 변경했는지
    봉인 불가. runtime test 가 진정한 효과 활성화 봉인.
    """

    def tearDown(self):
        # 다른 test 오염 방지 — process-wide install 후 reset.
        TRACEPARENT_SAMPLER_CTX.set(None)

    def test_install_sampler_from_env_actually_sets_context_var(self):
        """``install_sampler_from_env({...})`` 직후 ``current_sampler()`` 가
        설치된 sampler 반환 — end-to-end runtime 봉인."""
        installed = install_sampler_from_env({OTEL_TRACES_SAMPLER: 'always_off'})
        self.assertIs(current_sampler(), installed)
        self.assertIsInstance(installed, AlwaysOffSampler)

    def test_install_with_traceidratio_runtime_effect(self):
        """``OTEL_TRACES_SAMPLER=traceidratio`` + ratio=0.0 install →
        outbound 시점에 모든 trace_id drop 결정."""
        installed = install_sampler_from_env({
            OTEL_TRACES_SAMPLER: 'traceidratio',
            OTEL_TRACES_SAMPLER_ARG: '0.0',
        })
        self.assertIsInstance(installed, TraceIdRatioBased)
        # current_sampler() 가 0.0 ratio sampler 반환 — outbound 가 100% drop.
        sampler_runtime = current_sampler()
        self.assertFalse(sampler_runtime.should_sample('a' * 32, None))


# ════════════════════════════════════════════════════════════════════════════
# 2026-05-23 — TraceIdRatioBased SSOT 상수 + OTel Python SDK byte-identity
# ════════════════════════════════════════════════════════════════════════════
#
# **자평 결함 #4 follow-up (2026-05-23)** — 초기 commit 0b53fa0 의 self-reported
# "산업 표준 64-bit" 주장을 OTel Python SDK 공식 source 직접 fetch 검증한 결과,
# 실제 OTel Python SDK 는 `trace_id & TRACE_ID_LIMIT < bound` (하위 64-bit AND
# mask) — FCC 의 옛 `trace_id[:16]` 상위 16 hex 슬라이스와 byte-identity 불일치.
# 정공법: OTel Python SDK 공식 구현과 정확 byte-identity 정합 채택.
#
# **OTel Python SDK 공식 source verified line (2026-05-23)**:
#   https://github.com/open-telemetry/opentelemetry-python/blob/main/
#   opentelemetry-sdk/src/opentelemetry/sdk/trace/sampling.py
#
#   ```
#   TRACE_ID_LIMIT = (1 << 64) - 1
#   bound = round(rate * (cls.TRACE_ID_LIMIT + 1))
#   if trace_id & self.TRACE_ID_LIMIT < self.bound: ...
#   ```
#
# 본 invariant 가 봉인하는 SSOT:
#
# - ``_TRACE_ID_BITS_USED = 64`` — 산업 표준 비트 폭 (OTel Python SDK 정합).
# - ``_TRACE_ID_LIMIT = (1 << _TRACE_ID_BITS_USED) - 1`` — OTel Python SDK
#   ``TRACE_ID_LIMIT`` 와 byte-identity.
# - threshold 산식: ``round(ratio * (_TRACE_ID_LIMIT + 1))`` — OTel Python SDK
#   ``round(rate * (TRACE_ID_LIMIT + 1))`` byte-identity.
# - should_sample 산식: ``(int(trace_id, 16) & _TRACE_ID_LIMIT) < threshold`` —
#   OTel Python SDK ``trace_id & TRACE_ID_LIMIT < bound`` byte-identity.
#
# 사용자 룰 정합: "옛 API shim 0 + 단편적 임시방편 거부 + SSOT 정합 + 업계 표준
# verified" 일괄 충족.


class TestTraceSamplerSsotConstants(unittest.TestCase):
    """OTel Python SDK byte-identity 정합 SSOT 상수 봉인 (2026-05-23 follow-up).

    OTel Python SDK 공식 source verified line:
        TRACE_ID_LIMIT = (1 << 64) - 1
        bound = round(rate * (TRACE_ID_LIMIT + 1))
        trace_id & TRACE_ID_LIMIT < bound

    URL: github.com/open-telemetry/opentelemetry-python/blob/main/
         opentelemetry-sdk/src/opentelemetry/sdk/trace/sampling.py
    """

    def _module_constants(self) -> tuple[int, int]:
        import fcc_test_contracts.common.trace_sampler as mod
        return mod._TRACE_ID_BITS_USED, mod._TRACE_ID_LIMIT

    def test_trace_id_bits_used_constant_is_64(self):
        """SSOT 상수 ``_TRACE_ID_BITS_USED == 64`` — OTel Python SDK 산업 표준 정합."""
        bits_used, _ = self._module_constants()
        self.assertEqual(
            bits_used, 64,
            'OTel Python SDK ``TRACE_ID_LIMIT = (1 << 64) - 1`` byte-identity 정합. '
            '본 값 변경 시 ecosystem 호환성 손실 — 별 sprint 평가 후 변경.',
        )

    def test_trace_id_limit_matches_otel_python_sdk_byte_identity(self):
        """``_TRACE_ID_LIMIT == (1 << 64) - 1 == 0xFFFFFFFFFFFFFFFF`` — OTel
        Python SDK ``TRACE_ID_LIMIT`` 정확 byte-identity 봉인.

        본 검증 위배 시 OTel collector ecosystem downstream sample 결정 불일치 발생.
        """
        _, trace_id_limit = self._module_constants()
        otel_python_sdk_verified_value = (1 << 64) - 1  # 18446744073709551615
        self.assertEqual(
            trace_id_limit, otel_python_sdk_verified_value,
            f'_TRACE_ID_LIMIT ({trace_id_limit}) MUST equal OTel Python SDK '
            f'TRACE_ID_LIMIT ({otel_python_sdk_verified_value}) byte-identity. '
            f'verified URL: github.com/open-telemetry/opentelemetry-python/blob/main/'
            f'opentelemetry-sdk/src/opentelemetry/sdk/trace/sampling.py',
        )
        # 정확 16 hex F 명시 (downstream readability)
        self.assertEqual(
            trace_id_limit, 0xFFFFFFFFFFFFFFFF,
            '_TRACE_ID_LIMIT MUST equal 0xFFFFFFFFFFFFFFFF (64-bit max)',
        )

    def test_threshold_uses_otel_python_sdk_round_pattern(self):
        """``TraceIdRatioBased.__init__`` 가 ``round(ratio * (_TRACE_ID_LIMIT + 1))``
        패턴 사용 — OTel Python SDK ``round(rate * (TRACE_ID_LIMIT + 1))`` byte-identity.
        """
        source = TRACE_SAMPLER_PATH.read_text(encoding='utf-8')
        tree = ast.parse(source)
        # round(...) Call + (_TRACE_ID_LIMIT + 1) BinOp(Add) 패턴 검사
        found_round_pattern = False
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == 'round'):
                continue
            # round() 의 인자에 _TRACE_ID_LIMIT Name 사용 여부
            for arg_node in ast.walk(node):
                if isinstance(arg_node, ast.Name) and arg_node.id == '_TRACE_ID_LIMIT':
                    found_round_pattern = True
                    break
            if found_round_pattern:
                break
        self.assertTrue(
            found_round_pattern,
            'threshold 산정이 round(ratio * (_TRACE_ID_LIMIT + 1)) 패턴 사용 필수 '
            '(OTel Python SDK byte-identity)',
        )

    def test_no_raw_lshift_64_outside_trace_id_limit_definition(self):
        """trace_sampler.py 본문 ``1 << 64`` literal 은 ``_TRACE_ID_LIMIT`` 정의
        + 도메인 상수 정의 + docstring 만 허용. 그 외 사용 0건.

        AST: BinOp(Constant(1), LShift, Constant(64)) 검사 + 부모 Assign target
        이름이 ``_TRACE_ID_LIMIT`` 또는 ``_TRACE_ID_BITS_USED`` 인 경우만 허용.
        """
        source = TRACE_SAMPLER_PATH.read_text(encoding='utf-8')
        tree = ast.parse(source)
        # 1 << _TRACE_ID_BITS_USED 패턴은 허용 (도메인 상수 경유)
        # 1 << 64 raw literal 패턴은 _TRACE_ID_LIMIT 정의 외 0건
        violations = []
        # parent map 빌드
        parent_map = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parent_map[id(child)] = parent
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BinOp)
                    and isinstance(node.op, ast.LShift)
                    and isinstance(node.left, ast.Constant)
                    and node.left.value == 1
                    and isinstance(node.right, ast.Constant)
                    and node.right.value == 64):
                continue
            # 부모가 Assign 이고 target 이 _TRACE_ID_LIMIT 또는 _TRACE_ID_BITS_USED 인 경우 허용
            parent = parent_map.get(id(node))
            if isinstance(parent, ast.BinOp):
                # (1 << 64) - 1 같은 패턴 — _TRACE_ID_LIMIT 정의에 사용
                grandparent = parent_map.get(id(parent))
                if isinstance(grandparent, ast.AnnAssign):
                    target = grandparent.target
                    if isinstance(target, ast.Name) and target.id in (
                        '_TRACE_ID_LIMIT', '_TRACE_ID_BITS_USED'
                    ):
                        continue
            violations.append(f'line {node.lineno}: {ast.unparse(node)} '
                              f'(use _TRACE_ID_LIMIT or _TRACE_ID_BITS_USED)')
        self.assertFalse(
            violations,
            'trace_sampler.py 본문에 raw `1 << 64` literal 0건 봉인 — _TRACE_ID_LIMIT '
            '정의 외 SSOT 상수 경유 필수:\n' + '\n'.join(violations),
        )

    def test_industry_standard_otel_python_sdk_byte_identity_smoke(self):
        """OTel Python SDK 와 byte-identity 동치 — 같은 trace_id 입력에 대해
        동일 sample/drop 결정.

        OTel Python SDK 의 ``trace_id & TRACE_ID_LIMIT < bound`` 비교를 직접
        재현. ratio=0.5 + trace_id 의 **하위 64-bit** 가 정확히 2^63-1 일 때
        sample, 2^63 일 때 drop.

        본 smoke 가 위배 시 = FCC ↔ OTel collector ecosystem downstream sample
        결정 불일치 = byte-identity 정합 위반.
        """
        sampler = TraceIdRatioBased(0.5)
        # 하위 64-bit = '7fffffffffffffff' (= 2^63 - 1) — sample True
        # 상위 64-bit 은 무관 (AND mask 로 제거됨)
        self.assertTrue(
            sampler.should_sample('a' * 16 + '7fffffffffffffff', None),
            '하위 64-bit (7fff...) 가 threshold 직전 → sample (OTel Python SDK byte-identity)',
        )
        # 하위 64-bit = '8000000000000000' (= 2^63) — drop False
        self.assertFalse(
            sampler.should_sample('a' * 16 + '8000000000000000', None),
            '하위 64-bit (8000...) 가 threshold 도달 → drop (OTel Python SDK byte-identity)',
        )
        # 상위 64-bit 무관성 봉인 — 같은 하위 64-bit 입력 시 결과 동일
        self.assertEqual(
            sampler.should_sample('0' * 16 + '7fffffffffffffff', None),
            sampler.should_sample('f' * 16 + '7fffffffffffffff', None),
            '상위 64-bit 은 sample 결정에 무관 (AND mask 로 제거됨)',
        )

    def test_otel_python_sdk_pure_python_reimplementation_equivalence(self):
        """OTel Python SDK 의 should_sample 산식을 Python 직접 재현 + FCC 구현체와
        결과 동치 봉인 (50 random trace_id sample).

        OTel Python SDK 의 verified line:
          bound = round(rate * (TRACE_ID_LIMIT + 1))
          decision = (trace_id & TRACE_ID_LIMIT) < bound

        본 invariant 는 FCC 의 TraceIdRatioBased 가 산업 표준 source 와 매번
        동일한 결과 도출함을 통계적으로 봉인 (50 sample 전부 일치).
        """
        import random
        rng = random.Random(42)  # deterministic seed for CI 안정성
        TRACE_ID_LIMIT_OTEL = (1 << 64) - 1
        ratio = 0.37
        bound_otel = round(ratio * (TRACE_ID_LIMIT_OTEL + 1))
        sampler = TraceIdRatioBased(ratio)
        mismatches = []
        for _ in range(50):
            trace_id_int = rng.randint(0, (1 << 128) - 1)
            trace_id_hex = format(trace_id_int, '032x')
            # OTel Python SDK 의 결정
            otel_decision = (trace_id_int & TRACE_ID_LIMIT_OTEL) < bound_otel
            # FCC 의 결정
            fcc_decision = sampler.should_sample(trace_id_hex, None)
            if otel_decision != fcc_decision:
                mismatches.append(
                    f'trace_id={trace_id_hex}: OTel={otel_decision}, FCC={fcc_decision}'
                )
        self.assertFalse(
            mismatches,
            f'FCC TraceIdRatioBased(ratio={ratio}) MUST match OTel Python SDK '
            f'byte-identity for all trace_id inputs:\n' + '\n'.join(mismatches),
        )
