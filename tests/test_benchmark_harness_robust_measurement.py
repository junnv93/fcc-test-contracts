"""Robust multi-trial measurement SSOT — bench-harness-robust-measurement (2026-05-23).

``scripts/benchmark_harness.py::measure_latency_us`` already warms up and disables
GC during the measured loop, but a *single* run's p95/p99 can still be poisoned by
a transient OS-scheduler preemption or cross-process CPU contention (e.g. dozens of
latency invariants running in one pytest process). That is the recurring p99
flakiness recorded in tech-debt ``p0-5-ble-labeled-schema-completion`` S-2.

``measure_latency_us_robust`` closes the gap with the ``timeit.repeat()``→``min``
idiom (industry standard; see ADR-0002): run the full measurement ``trials`` times
and reduce each metric by its minimum across trials. Transient noise inflates
latency but never deflates it, so the minimum trial is the cleanest estimate of the
code's intrinsic latency.

This module proves the property **deterministically** — the headline anti-flakiness
test feeds synthetic trial summaries (no timing) so a spiked trial is provably
rejected, and the test itself can never flake. The integration tests then confirm
the helper wires real measurement runs through the same aggregation.

NOTE: every method/helper name here is intentionally outside
``_BANNED_TEST_PERCENTILE_HELPER_REGEX`` and ``_SSOT_MATH_FUNCTION_NAMES`` so this
guard module does not trip the percentile SSOT AST guard it complements.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = PROJECT_ROOT / 'scripts'
# Idempotent insert so ``from benchmark_harness import ...`` resolves even when
# this module is imported outside the normal pytest collection path (conftest
# also registers scripts/ since Phase 7, 2026-05-23).
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# ⚠️ **2026-09-03 — `scripts/` 에서 배포되는 패키지로 올렸다.**
# `scripts/` 는 이 상자가 배포하지 않으므로 그 자리의 모듈은 소비 레인이
# 쓸 수 없었다. 그래서 import 가 배포 이름을 지난다.
from fcc_test_contracts.common.benchmark_harness import (  # noqa: E402
    DEFAULT_TRIALS,
    LatencyBudget,
    _aggregate_min_across_trials,
    assert_latency_budget,
    measure_latency_us_robust,
)


def _trial(*, p50: float, p95: float, p99: float, mean: float, mx: float, iters: float = 100.0) -> dict[str, float]:
    """Build one synthetic per-trial summary (the shape ``measure_latency_us`` emits)."""
    return {
        'iters': iters,
        'p50_us': p50,
        'p95_us': p95,
        'p99_us': p99,
        'mean_us': mean,
        'max_us': mx,
    }


class TestAggregateMinAcrossTrials:
    """Deterministic aggregation policy — the anti-flakiness proof (no timing)."""

    def test_per_metric_minimum_selected(self) -> None:
        """Each metric in the result is the minimum of that metric across trials."""
        trials = [
            _trial(p50=10, p95=20, p99=30, mean=12, mx=40),
            _trial(p50=8, p95=18, p99=25, mean=11, mx=35),
            _trial(p50=9, p95=22, p99=28, mean=13, mx=50),
        ]
        result = _aggregate_min_across_trials(trials)
        assert result['p50_us'] == 8
        assert result['p95_us'] == 18
        assert result['p99_us'] == 25
        assert result['mean_us'] == 11
        assert result['max_us'] == 35
        assert result['trials'] == 3.0
        assert result['iters'] == 100.0

    def test_transient_spike_is_rejected(self) -> None:
        """Headline anti-flakiness proof: one spiked trial cannot poison the result.

        Trial 2 simulates an OS-scheduler stall that inflated every metric 100×.
        Because aggregation takes the per-metric minimum, the clean trials win and
        the budget-relevant p95/p99 are unaffected by the spike.
        """
        clean_a = _trial(p50=10, p95=20, p99=30, mean=12, mx=40)
        spiked = _trial(p50=1000, p95=2000, p99=3000, mean=1500, mx=5000)
        clean_b = _trial(p50=11, p95=21, p99=31, mean=13, mx=42)
        result = _aggregate_min_across_trials([clean_a, spiked, clean_b])
        # The spike never appears in any reduced metric.
        assert result['p95_us'] == 20
        assert result['p99_us'] == 30
        assert result['max_us'] == 40
        # ... but the spread diagnostic surfaces that the host was noisy.
        assert result['p95_trial_spread_us'] == 2000 - 20

    def test_spread_diagnostic_is_max_minus_min_trial_p95(self) -> None:
        trials = [
            _trial(p50=5, p95=15, p99=25, mean=7, mx=30),
            _trial(p50=6, p95=45, p99=60, mean=8, mx=70),
        ]
        result = _aggregate_min_across_trials(trials)
        assert result['p95_trial_spread_us'] == 45 - 15

    def test_metrics_may_come_from_different_trials(self) -> None:
        """Per-metric independence — the lowest p95 and lowest p99 need not share a trial."""
        # Trial A has the lowest p95; trial B has the lowest p99.
        trial_a = _trial(p50=10, p95=10, p99=99, mean=11, mx=100)
        trial_b = _trial(p50=10, p95=90, p99=11, mean=11, mx=100)
        result = _aggregate_min_across_trials([trial_a, trial_b])
        assert result['p95_us'] == 10   # from trial A
        assert result['p99_us'] == 11   # from trial B

    def test_monotonic_ordering_preserved_after_reduction(self) -> None:
        """min(p99) >= min(p95) >= min(p50) holds for the reduced result.

        Proof: within each trial p99>=p95>=p50 (nearest-rank monotonicity), so
        every p99_i >= min(p95) and every p95_i >= min(p50). The aggregated
        result therefore preserves the percentile ordering even though metrics are
        reduced independently — a useful sanity invariant for budget consumers.
        """
        trials = [
            _trial(p50=10, p95=10, p99=20, mean=10, mx=20),
            _trial(p50=8, p95=30, p99=40, mean=9, mx=40),
        ]
        result = _aggregate_min_across_trials(trials)
        assert result['p99_us'] >= result['p95_us'] >= result['p50_us']

    def test_empty_trials_returns_zero_summary(self) -> None:
        """Empty input → zero summary (matches the percentile/measure empty convention)."""
        result = _aggregate_min_across_trials([])
        assert result['trials'] == 0.0
        assert result['iters'] == 0.0
        for metric in ('p50_us', 'p95_us', 'p99_us', 'mean_us', 'max_us', 'p95_trial_spread_us'):
            assert result[metric] == 0.0

    def test_single_trial_spread_is_zero(self) -> None:
        result = _aggregate_min_across_trials([_trial(p50=5, p95=10, p99=15, mean=6, mx=20)])
        assert result['trials'] == 1.0
        assert result['p95_us'] == 10
        assert result['p95_trial_spread_us'] == 0.0


class TestMeasureLatencyUsRobustIntegration:
    """Integration — the helper wires real measurement runs through the aggregation."""

    def test_default_trials_matches_timeit_convention(self) -> None:
        """DEFAULT_TRIALS is the canonical ``timeit.repeat(repeat=5)`` industry value."""
        assert DEFAULT_TRIALS == 5

    def test_returns_summary_dict_with_robust_keys(self) -> None:
        stats = measure_latency_us_robust(lambda: sum(range(64)), iters=200, trials=3)
        for key in ('iters', 'trials', 'p50_us', 'p95_us', 'p99_us', 'mean_us', 'max_us', 'p95_trial_spread_us'):
            assert key in stats, f'robust summary missing {key!r}'
        assert stats['trials'] == 3.0
        assert stats['iters'] == 200.0

    def test_all_metrics_finite_and_nonnegative(self) -> None:
        stats = measure_latency_us_robust(lambda: sum(range(32)), iters=100, trials=3)
        for key in ('p50_us', 'p95_us', 'p99_us', 'mean_us', 'max_us', 'p95_trial_spread_us'):
            assert stats[key] >= 0.0
        assert stats['p99_us'] >= stats['p95_us'] >= stats['p50_us']

    def test_compatible_with_assert_latency_budget(self) -> None:
        """A robust summary is drop-in for ``assert_latency_budget`` (key shape preserved)."""
        stats = measure_latency_us_robust(lambda: None, iters=100, trials=3)
        # A generous budget — this asserts the contract (no KeyError), not a number.
        assert_latency_budget(stats, LatencyBudget(name='noop', metric='p95_us', limit_us=1_000_000.0))

    def test_invalid_trials_raises(self) -> None:
        with pytest.raises(ValueError):
            measure_latency_us_robust(lambda: None, iters=10, trials=0)

    def test_single_trial_equivalent_to_one_measure_run_shape(self) -> None:
        stats = measure_latency_us_robust(lambda: None, iters=50, trials=1)
        assert stats['trials'] == 1.0
        assert stats['p95_trial_spread_us'] == 0.0
