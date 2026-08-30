"""순차 min-of-trials 축약 봉인 — 판정 동등성 · 비용 비대칭 · 정지 조건 전량성.

**이 파일은 시계를 읽지 않는다.** 합성 trial 요약과 AST 만 본다. 측정 flakiness
를 고치는 웨이브의 봉인이 스스로 flake 이면 아무것도 지키지 못한다 — 그것이
``TestSnapshotReleaseLifecycleMeasurementPolicy`` 와
``TestFakeProgressIndicatorMeasurementPolicy`` 가 이미 택한 자리이고, 이 파일은
그 둘이 각자 재발명하던 **harness 쪽 명제**를 한 곳으로 모은다.

---

**웨이브의 명제 (2026-08-29, ``bench-judgment-reliability``)**

같은 커밋·같은 트리에서 실행마다 뒤집히던 latency budget 넷 중 **둘은 이미
``measure_latency_us_robust`` 에 위임하고 있었다.** 그러므로 첫 질문은
「위임했나」가 아니라 **「위임했는데도 왜 뒤집히나」** 였고, 답은 축약의
**시행 수**에 있었다:

``DEFAULT_TRIALS = 5`` 의 출처는 ``timeit.repeat(repeat=5)`` 인데, 그 관용구는
**총 루프 시간**(평균류·저분산)을 최소화한다. 여기서 최소화하는 것은 **p95**
(고차 순서통계량·고분산)라 그 보정이 이월되지 않는다 — **관용구가 통계량이
바뀌는 경계를 넘어 이식되면서 무효가 됐다.** 실측(40 trial 수집 · 400 순열
시뮬 · 조용한 호스트): 고정 5 로 ``FakeProgressIndicator`` lifecycle 예산이
**22%** 뒤집힌다.

그리고 이것은 ADR-0002 가 §Consequences/Negative 에 **이름으로 적어 둔** 공백의
청구서다 — *"No automatic iteration calibration — iters/trials are caller-chosen
(pytest-benchmark auto-calibrates)."*
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / 'scripts'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from benchmark_harness import (  # noqa: E402
    DEFAULT_MAX_TRIALS,
    DEFAULT_TRIALS,
    LatencyBudget,
    _aggregate_min_across_trials,
    measure_latency_us_for_budget,
    reduce_trials_until_decided,
)

pytestmark = pytest.mark.invariant

_HARNESS = SCRIPTS_DIR / 'benchmark_harness.py'


def _summary(p95: float, *, p99: float | None = None) -> dict[str, float]:
    """``summarize_samples_us`` 와 같은 모양의 **합성** trial (시계 미사용)."""
    tail = p95 if p99 is None else p99
    return {
        'iters': 1.0,
        'p50_us': p95, 'p95_us': p95, 'p99_us': tail,
        'mean_us': p95, 'max_us': tail,
    }


def _scripted(values: list[dict[str, float]]):
    """주어진 순서대로 trial 을 내주고, 소진되면 마지막 값을 반복한다.

    소진 시 예외를 던지면 「상한까지 뽑힌다」는 명제를 시험하는 witness 가
    상한이 바뀔 때마다 조용히 IndexError 로 죽는다 — 그러면 그 봉인은 상한의
    함수가 아니라 리스트 길이의 함수가 된다.
    """
    calls: list[int] = []

    def _next() -> dict[str, float]:
        calls.append(len(calls))
        return values[min(len(calls) - 1, len(values) - 1)]

    return _next, calls


# ════════════════════════════════════════════════════════════════════════════
# 1. 판정 동등성 — 조기 정지는 벽시계만 줄이고 판정을 바꾸지 않는다
# ════════════════════════════════════════════════════════════════════════════

class TestEarlyStoppingDoesNotChangeTheVerdict:
    """조기 정지의 판정 ≡ 상한을 무조건 다 도는 판정.

    이것이 이 설계를 고른 이유 전부다. ``min`` 은 상위집합에서 부분집합보다
    크지 않으므로 축약값은 뽑은 trial 수에 대해 **단조 비증가**이고, 따라서
    「예산 아래로 내려간 순간 멈춘다」는 규칙은 끝까지 돌았을 때의 판정과
    **글자 그대로 같은 답**을 낸다. 통계에서 optional stopping 이 문제가 되는
    이유(정지 규칙이 판정을 편향시킨다)가 여기서는 성립하지 않으며, 그 사실이
    산문이 아니라 실행되는 명제로 남아 있어야 한다.
    """

    _BUDGET = LatencyBudget('t', 'p95_us', 10.0)

    #: 판정이 갈리는 모양을 고루 덮는다 — 즉시 통과 / 늦게 통과 / 끝내 미달 /
    #: 마지막 trial 에서 겨우 통과(경계) / 등호(예산과 정확히 같음).
    _SEQUENCES = (
        [5.0],
        [50.0, 40.0, 9.0],
        [50.0, 40.0, 30.0],
        [50.0, 50.0, 50.0, 50.0, 10.0],
        [10.0],
        [11.0, 10.5, 10.0001],
    )

    @pytest.mark.parametrize('values', _SEQUENCES)
    @pytest.mark.parametrize('max_trials', (1, 2, 3, 5, 8))
    def test_sequential_verdict_equals_exhaustive_verdict(self, values, max_trials):
        seq_fn, _ = _scripted([_summary(v) for v in values])
        sequential = reduce_trials_until_decided(
            seq_fn, budgets=(self._BUDGET,), max_trials=max_trials,
        )
        exhaustive_trials = [
            _summary(values[min(i, len(values) - 1)]) for i in range(max_trials)
        ]
        exhaustive = _aggregate_min_across_trials(exhaustive_trials)

        assert (sequential['p95_us'] <= self._BUDGET.limit_us) == (
            exhaustive['p95_us'] <= self._BUDGET.limit_us
        ), (
            f'조기 정지가 판정을 바꿨다: 순차 {sequential["p95_us"]} vs '
            f'전량 {exhaustive["p95_us"]} (예산 {self._BUDGET.limit_us})'
        )

    def test_the_equivalence_witness_is_not_vacuous(self):
        """위 명제가 **조기 정지가 실제로 일어난 경우**를 포함한다.

        모든 케이스가 상한까지 돌았다면 위 테스트는 동등성이 아니라 항등식을
        확인한 것이 되고, 정지 규칙을 지워도 초록으로 남는다.
        """
        stopped_early = 0
        for values in self._SEQUENCES:
            seq_fn, calls = _scripted([_summary(v) for v in values])
            reduce_trials_until_decided(
                seq_fn, budgets=(self._BUDGET,), max_trials=8,
            )
            if len(calls) < 8:
                stopped_early += 1
        assert stopped_early >= 3, (
            f'8개 중 {stopped_early}개만 조기 정지했다 — 동등성 witness 가 '
            f'정지 경로를 거의 밟지 않는다.'
        )

    def test_the_reduced_value_is_monotone_in_trials_drawn(self):
        """축약값은 뽑은 trial 수에 대해 단조 비증가 — 동등성의 근거 그 자체."""
        values = [_summary(v) for v in (90.0, 30.0, 55.0, 12.0, 12.0, 7.0)]
        previous = float('inf')
        for k in range(1, len(values) + 1):
            current = _aggregate_min_across_trials(values[:k])['p95_us']
            assert current <= previous, f'k={k} 에서 축약값이 증가했다'
            previous = current


# ════════════════════════════════════════════════════════════════════════════
# 2. 비용 비대칭 — 통과는 싸고 실패는 최대 증거 위에서만
# ════════════════════════════════════════════════════════════════════════════

class TestTheCostIsAsymmetricByDesign:
    """통과 1 trial / 실패 상한 trial.

    비대칭이 우연이 아니라 설계다. **실패 판정은 되돌리기 어려운 주장**
    (「이 코드가 느려졌다」)이므로 상한이 허용하는 최대 증거 위에서만 내려야
    하고, **통과는 잡음이 지연을 깎지 못하므로** 첫 깨끗한 trial 로 충분하다.

    그리고 이 성질에는 이 라운드 고유의 값이 있다 — bench 레인은 배타적이어야
    하므로 그 레인이 쥐고 있는 시간이 곧 다른 세션의 대기 시간이다. 실측 평균
    사용 trial: ``wal 5→1.05`` · ``bind 5→1.08`` · ``lifecycle 5→3.74``.
    """

    _BUDGET = LatencyBudget('t', 'p95_us', 10.0)

    def test_a_clean_first_trial_costs_exactly_one(self):
        fn, calls = _scripted([_summary(1.0)])
        stats = reduce_trials_until_decided(fn, budgets=(self._BUDGET,))
        assert len(calls) == 1
        assert stats['trials_used'] == 1.0
        assert stats['decided'] is True

    def test_an_undecidable_budget_costs_exactly_the_cap(self):
        fn, calls = _scripted([_summary(999.0)])
        stats = reduce_trials_until_decided(fn, budgets=(self._BUDGET,))
        assert len(calls) == DEFAULT_MAX_TRIALS
        assert stats['trials_used'] == float(DEFAULT_MAX_TRIALS)
        assert stats['decided'] is False

    def test_the_cap_exceeds_the_fixed_trial_count_it_replaces(self):
        """상한이 옛 고정 시행 수보다 크다 — 아니면 이 웨이브는 무연산이다.

        고정 5 는 조용한 호스트에서도 이 저장소의 가장 좁은 예산을 22%
        뒤집었다. 상한이 5 이하로 내려가면 그 상태로 되돌아간다.
        """
        assert DEFAULT_MAX_TRIALS > DEFAULT_TRIALS, (
            f'DEFAULT_MAX_TRIALS={DEFAULT_MAX_TRIALS} <= '
            f'DEFAULT_TRIALS={DEFAULT_TRIALS} — 순차 축약이 옛 고정 축약보다 '
            f'많은 증거를 모을 수 없으면 뒤집힘이 그대로 남는다.'
        )

    def test_a_transient_spike_is_outvoted_but_a_uniform_regression_is_not(self):
        """흡수 witness ∧ 보존 witness 쌍.

        흡수만 단언하면 「무엇이든 통과시킨다」와 구별되지 않는다. 두 명제가
        같은 자리에 있어야 축약이 *잡음만* 깎는다는 주장이 검사 가능해진다.
        """
        spike_then_clean, _ = _scripted(
            [_summary(999.0), _summary(999.0), _summary(2.0)]
        )
        assert reduce_trials_until_decided(
            spike_then_clean, budgets=(self._BUDGET,),
        )['p95_us'] == 2.0

        uniformly_slow, _ = _scripted([_summary(self._BUDGET.limit_us * 1.2)])
        assert reduce_trials_until_decided(
            uniformly_slow, budgets=(self._BUDGET,),
        )['p95_us'] == self._BUDGET.limit_us * 1.2


# ════════════════════════════════════════════════════════════════════════════
# 3. 정지 조건은 판정 지표 **전량**을 본다
# ════════════════════════════════════════════════════════════════════════════

class TestTheStopConditionSpansEveryBudget:
    """한 측정이 여러 예산에 판정받으면 정지 조건이 그 전부를 봐야 한다.

    ``TestWalCheckpointDurabilityLatencyBudget`` 은 하나의 fixture 를 p95 와
    p99 두 예산으로 판정한다. p95 가 먼저 내려갔다고 멈추면 p99 는 미결로
    남고, 첫 번째 축에서 없앤 flake 가 **두 번째 축에서 그대로 재발**한다.
    """

    _P95 = LatencyBudget('t', 'p95_us', 10.0)
    _P99 = LatencyBudget('t', 'p99_us', 20.0)

    def test_it_keeps_drawing_while_any_budget_is_unmet(self):
        # trial 1: p95 통과(9) · p99 미달(99) → 계속 뽑아야 한다.
        # trial 2: 둘 다 통과 → 여기서 멈춘다.
        fn, calls = _scripted([_summary(9.0, p99=99.0), _summary(9.0, p99=15.0)])
        stats = reduce_trials_until_decided(fn, budgets=(self._P95, self._P99))
        assert len(calls) == 2, (
            'p95 만 보고 멈췄다 — p99 가 미결로 남으면 두 번째 축에서 같은 '
            'flake 가 재발한다.'
        )
        assert stats['decided'] is True

    def test_a_single_budget_view_would_have_stopped_early(self):
        """위 명제의 비-공허성 — p95 만 봤다면 **1 trial 에 멈췄을** 입력이다."""
        fn, calls = _scripted([_summary(9.0, p99=99.0), _summary(9.0, p99=15.0)])
        reduce_trials_until_decided(fn, budgets=(self._P95,))
        assert len(calls) == 1


# ════════════════════════════════════════════════════════════════════════════
# 4. 계약 방어 — 잘못 쓰면 조용히 통과하지 않고 거부한다
# ════════════════════════════════════════════════════════════════════════════

class TestTheReducerRefusesUndecidableConfigurations:

    def test_zero_budgets_is_refused(self):
        fn, _ = _scripted([_summary(1.0)])
        with pytest.raises(ValueError, match='at least one'):
            reduce_trials_until_decided(fn, budgets=())

    def test_a_cap_below_one_is_refused(self):
        fn, _ = _scripted([_summary(1.0)])
        with pytest.raises(ValueError, match='max_trials'):
            reduce_trials_until_decided(
                fn, budgets=(LatencyBudget('t', 'p95_us', 1.0),), max_trials=0,
            )

    def test_a_metric_that_is_not_reduced_across_trials_is_refused(self):
        """축약되지 않는 지표로는 정지 판단을 할 수 없다 — 조용히 통과 금지.

        ``p95_trial_spread_us`` 는 요약 dict 에 **있지만** metric 별 최소로
        축약되지 않는다. 그것을 정지 기준으로 쓰면 값이 단조가 아니어서
        §1 의 판정 동등성이 무너진다.
        """
        fn, _ = _scripted([_summary(1.0)])
        with pytest.raises(ValueError, match='not reduced across trials'):
            reduce_trials_until_decided(
                fn, budgets=(LatencyBudget('t', 'p95_trial_spread_us', 1.0),),
            )


# ════════════════════════════════════════════════════════════════════════════
# 5. SSOT 규율 — 축약 정책을 두 번 정의하지 않는다
# ════════════════════════════════════════════════════════════════════════════

class TestTheReducerDelegatesRatherThanReimplements:
    """순차 축약은 **정지 시점**만 더한다. 축약 정책은 기존 SSOT 그대로."""

    @staticmethod
    def _fn(name: str) -> ast.FunctionDef:
        tree = ast.parse(_HARNESS.read_text(encoding='utf-8'), filename=str(_HARNESS))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f'benchmark_harness.{name} 을 찾지 못했다.')

    def test_it_calls_the_aggregation_ssot(self):
        called = {
            child.func.id
            for child in ast.walk(self._fn('reduce_trials_until_decided'))
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        assert '_aggregate_min_across_trials' in called

    def test_it_does_not_reimplement_the_reduction_or_the_percentile(self):
        fn = self._fn('reduce_trials_until_decided')
        local = {
            child.func.id
            for child in ast.walk(fn)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        } | {
            child.func.attr
            for child in ast.walk(fn)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
        }
        forbidden = local & {'sorted', 'median', 'mean', 'percentile',
                             'summarize_samples_us'}
        assert not forbidden, (
            f'순차 축약이 축약/백분위 정책을 재구현한다: {sorted(forbidden)}'
        )

    def test_the_budget_aware_wrapper_delegates_to_the_reducer(self):
        called = {
            child.func.id
            for child in ast.walk(self._fn('measure_latency_us_for_budget'))
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        assert 'reduce_trials_until_decided' in called
        assert 'measure_latency_us' in called

    def test_the_measurement_helpers_stay_budget_free(self):
        """측정 helper 는 예산을 모른다 — 시계열 경로가 그것을 소비한다.

        ``.bench-snapshots/`` 는 문턱과 무관한 수를 필요로 한다. 측정 helper 가
        예산을 알게 되면 기록되는 값이 그 순간의 문턱에 의존하게 되고, 시계열이
        코드가 아니라 예산의 역사를 재게 된다.
        """
        for name in ('measure_latency_us', 'measure_latency_us_robust'):
            args = self._fn(name).args
            names = {a.arg for a in (*args.args, *args.kwonlyargs)}
            assert not names & {'budget', 'budgets'}, (
                f'{name} 이 예산을 인자로 받는다 — 측정과 게이트의 분리가 깨졌다.'
            )


class TestTheCapCarriesItsDerivationNotJustANumber:
    """``DEFAULT_MAX_TRIALS`` 는 빌린 관용구가 아니라 실측에서 왔다.

    ``DEFAULT_TRIALS`` 는 자기 출처(``timeit.repeat``)를 docstring 에 싣는다.
    그 관행 자체는 옳았고 **틀린 것은 그 출처가 다른 통계량의 것이었다**는
    점이다. 새 상한이 같은 실수를 반복하지 않도록, 그것이 *무엇을 재서* 정해진
    값인지가 모듈 안에 남아 있어야 한다.
    """

    def test_the_constant_names_the_measurement_that_set_it(self):
        text = _HARNESS.read_text(encoding='utf-8')
        head = text[: text.index('DEFAULT_MAX_TRIALS = ')]
        provenance = head[head.rindex('#: Upper bound'):]
        for token in ('timeit', 'p95', 'bench-judgment-reliability'):
            assert token in provenance, (
                f'DEFAULT_MAX_TRIALS 의 근거에 {token!r} 이 없다 — 상한이 '
                f'파생값이 아니라 매직 넘버로 굳었다.'
            )

    def test_the_wave_evaluation_is_reachable_from_the_constant(self):
        text = _HARNESS.read_text(encoding='utf-8')
        assert '.claude/evaluations/bench-judgment-reliability.md' in text, (
            '상한의 영수증 경로가 모듈에 없다 — 다음 세션이 이 값을 재유도할 '
            '방법을 잃는다.'
        )
