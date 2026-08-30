"""Shared microbenchmark helpers for repository latency budgets.

The bench scripts measure small Python hot paths where raw p95 numbers are
sensitive to GC and scheduler noise. This module keeps the measurement policy
in one place: warm up first, disable GC only during the measured loop, summarize
with stable percentile math, and expose one assertion helper for tests.
"""
from __future__ import annotations

import gc
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LatencyBudget:
    """Named latency threshold used by benchmark-backed tests."""

    name: str
    metric: str
    limit_us: float


def percentile(samples: list[float], q: float) -> float:
    """Return nearest-rank percentile from pre-collected microsecond samples."""
    if not samples:
        return 0.0
    if len(samples) == 1:
        return samples[0]
    sorted_samples = sorted(samples)
    rank = int(q * (len(sorted_samples) - 1))
    return sorted_samples[rank]


def median(samples: list[float]) -> float:
    """Return the statistical median (mean of the two middle samples for even counts).

    Semantically distinct from ``percentile(samples, 0.50)``, which is the
    *nearest-rank lower* value — it returns ``sorted[mid-1]`` for even counts
    rather than averaging the two middle samples. The statistical median is the
    right outlier-resilient central tendency for GC-sensitive microbenchmarks
    where the typical case matters: the nearest-rank off-by-one would bias
    distributions with spread (e.g. legacy QTableWidget GC outliers) more than
    dense distributions, making a ratio comparison between two such
    distributions systematically skewed.

    Delegates to ``statistics.median`` (Python stdlib, NIST linear-interpolation
    definition for even counts). Returns 0.0 for an empty list to match the
    ``percentile`` empty-input convention so callers can treat both uniformly.
    """
    if not samples:
        return 0.0
    return statistics.median(samples)


def ns_to_us(samples_ns: list[int]) -> list[float]:
    """Convert nanosecond samples to microseconds (the unit SSOT for bench math).

    Inline measurement callers (``time.perf_counter_ns()`` loops) need this when
    they can't use ``measure_latency_us`` (which expects a zero-argument callable
    that wraps the entire measured section). Centralizing the divisor here keeps
    the unit policy with the rest of the bench SSOT.
    """
    return [ns / 1000.0 for ns in samples_ns]


def percentile_us_from_ns_samples(samples_ns: list[int], q: float) -> float:
    """Return nearest-rank percentile of ``samples_ns`` converted to microseconds.

    Convenience wrapper over ``percentile(ns_to_us(samples_ns), q)`` for the
    common inline-measurement pattern. Keeps the unit conversion and the
    percentile policy at the SSOT module so each bench/test does not redefine
    them locally.
    """
    return percentile(ns_to_us(samples_ns), q)


def summarize_samples_us(samples_us: list[float]) -> dict[str, float]:
    """Build the standard latency summary emitted by all bench scripts."""
    return {
        'p50_us': percentile(samples_us, 0.50),
        'p95_us': percentile(samples_us, 0.95),
        'p99_us': percentile(samples_us, 0.99),
        'mean_us': statistics.mean(samples_us) if samples_us else 0.0,
        'max_us': max(samples_us) if samples_us else 0.0,
    }


def measure_latency_us(
    func: Callable[[], Any],
    *,
    iters: int,
    warmup: int = 50,
    disable_gc: bool = True,
) -> dict[str, float]:
    """Measure one callable and return the standard summary dict.

    The callable is intentionally zero-argument so benchmark setup stays outside
    the measured section. Return values are ignored by design.
    """
    for _ in range(warmup):
        func()

    samples_ns: list[int] = []
    gc_was_enabled = gc.isenabled()
    if disable_gc and gc_was_enabled:
        gc.disable()
    try:
        for _ in range(iters):
            t0 = time.perf_counter_ns()
            func()
            samples_ns.append(time.perf_counter_ns() - t0)
    finally:
        if disable_gc and gc_was_enabled:
            gc.enable()

    samples_us = ns_to_us(samples_ns)
    return {'iters': float(iters), **summarize_samples_us(samples_us)}


#: Default trial count for ``measure_latency_us_robust``. Matches the canonical
#: Python micro-timing idiom ``timeit.repeat(repeat=5)`` — enough independent
#: full measurements that a single OS-scheduler outlier does not dominate the
#: minimum, but few enough to keep CI wall-clock bounded. This is an industry
#: convention, not a tuned magic number (see ADR-0002 §Decision).
DEFAULT_TRIALS = 5

#: Metric keys that ``_aggregate_min_across_trials`` reduces by per-metric
#: minimum across trials. Mirrors the summary emitted by ``summarize_samples_us``
#: so a robust run is drop-in compatible with ``assert_latency_budget`` (which
#: indexes ``stats[budget.metric]``).
_TRIAL_AGGREGATED_METRICS = ('p50_us', 'p95_us', 'p99_us', 'mean_us', 'max_us')


def _aggregate_min_across_trials(summaries: list[dict[str, float]]) -> dict[str, float]:
    """Reduce per-trial summaries to one summary by per-metric minimum.

    Pure function (no timing) so the aggregation policy is unit-testable in
    isolation: a single trial whose p95 was inflated by a transient
    OS-scheduler/CPU-contention spike must NOT poison the result, because every
    metric is reduced by ``min`` across trials.

    Rationale (``timeit`` docs §"timeit — Measure execution time", note on
    ``repeat``): "the lowest value gives a lower bound for how fast your machine
    can run the given code snippet; higher values in the result vector are
    typically not caused by variability in Python's speed, but by other
    processes interfering with your timing accuracy. So the min() of the result
    is probably the only number you should be interested in." Each metric is
    therefore reduced independently — for any given percentile, the cleanest
    (least noise-affected) estimate across the trials is its minimum.

    ``p95_trial_spread_us`` (max trial p95 − min trial p95) is emitted as a
    diagnostic: a large spread signals a noisy host (the robust min already
    rejected it, but the spread makes the noise visible in CI output).
    """
    if not summaries:
        return {
            'iters': 0.0,
            'trials': 0.0,
            **{metric: 0.0 for metric in _TRIAL_AGGREGATED_METRICS},
            'p95_trial_spread_us': 0.0,
        }
    trial_p95s = [s['p95_us'] for s in summaries]
    aggregated = {
        metric: min(s[metric] for s in summaries)
        for metric in _TRIAL_AGGREGATED_METRICS
    }
    return {
        'iters': summaries[0]['iters'],
        'trials': float(len(summaries)),
        **aggregated,
        'p95_trial_spread_us': max(trial_p95s) - min(trial_p95s),
    }


def measure_latency_us_robust(
    func: Callable[[], Any],
    *,
    iters: int,
    trials: int = DEFAULT_TRIALS,
    warmup: int = 50,
    disable_gc: bool = True,
) -> dict[str, float]:
    """Measure ``func`` across ``trials`` independent runs; return per-metric minimum.

    Each trial is a full ``measure_latency_us`` run (warmup + ``gc.disable()`` +
    nearest-rank percentile). The trial summaries are reduced by per-metric
    minimum (see ``_aggregate_min_across_trials``).

    This is the ``timeit.repeat()`` → ``min`` idiom and pytest-benchmark's
    "rounds" concept expressed in the repository's own measurement SSOT, instead
    of taking on a third-party dependency (see ADR-0002). It closes the recurring
    GC/scheduler p99 flakiness where a single ``measure_latency_us`` run is
    poisoned by a transient OS-scheduler preemption or cross-process CPU
    contention (e.g. dozens of latency invariants running in one pytest process):
    such noise inflates latency but never deflates it, so the minimum trial is
    the cleanest estimate of the code's intrinsic latency.

    Returns the same summary keys as ``measure_latency_us`` (so
    ``assert_latency_budget`` works unchanged) plus ``trials`` and
    ``p95_trial_spread_us`` (host-noise diagnostic). Asserting
    ``stats['p95_us'] <= budget`` against a robust run means "even on its best
    independent run, the code was within budget" — a real regression slows every
    trial, while transient noise cannot make slow code look fast.
    """
    if trials < 1:
        raise ValueError(f'trials must be >= 1, got {trials}')
    summaries = [
        measure_latency_us(func, iters=iters, warmup=warmup, disable_gc=disable_gc)
        for _ in range(trials)
    ]
    return _aggregate_min_across_trials(summaries)


#: Upper bound on trials for the budget-aware sequential reducer below.
#:
#: Unlike ``DEFAULT_TRIALS`` — which borrows ``timeit.repeat(repeat=5)`` — this
#: value is **derived from this repository's own measurement**, because the
#: borrowed convention does not transfer. ``timeit.repeat`` minimises the *total
#: time of a loop* (a mean-like, low-variance statistic); the budgets here
#: minimise a *p95* (a high-order statistic whose sampling variance is far
#: larger). Five trials is calibrated for the former and is not calibrated for
#: the latter — which is why four latency budgets flipped run-to-run on the same
#: tree while already delegating to ``measure_latency_us_robust``.
#:
#: Derivation (2026-08-29, ``bench-judgment-reliability``; receipts in
#: ``.claude/evaluations/bench-judgment-reliability.md``): 40 independent trials
#: were collected per budget, quiescent and under deterministic 8-burner load,
#: and the sequential rule below was simulated over 400 random trial orderings.
#: The criterion is *zero* simulated failure for the repository's
#: tightest-margin budget (``FakeProgressIndicator`` lifecycle, whose budget sits
#: only ~17% above its judged value). Five trials leaves that budget failing
#: 22% of the time on an idle host.
#:
#: This is a wall-clock safety valve, not a target: the reducer stops as soon as
#: the verdict is decided, so the *typical* cost is 1-4 trials — measurably
#: cheaper than today's unconditional five — and the cap is reached only when a
#: budget genuinely cannot be met.
DEFAULT_MAX_TRIALS = 30


def reduce_trials_until_decided(
    trial_fn: Callable[[], dict[str, float]],
    *,
    budgets: Sequence[LatencyBudget],
    max_trials: int = DEFAULT_MAX_TRIALS,
) -> dict[str, float]:
    """Draw trial summaries one at a time until every budget is decided.

    ``budgets`` must name **all** budgets the resulting summary will be judged
    against, not just the tightest one. A measurement judged on both p95 and p99
    (``TestWalCheckpointDurabilityLatencyBudget``) that stopped as soon as p95
    cleared would leave p99 undecided, reintroducing on the second axis exactly
    the flakiness this reducer removes on the first.

    ``trial_fn`` must return one ``summarize_samples_us``-shaped summary — the
    same contract ``measure_latency_us`` satisfies, so a bench script's
    ``run_*()`` is a valid trial producer without adaptation. Summaries are
    reduced by the existing per-metric-minimum SSOT
    (``_aggregate_min_across_trials``); this function adds *when to stop*, not a
    second reduction policy.

    **Verdict-equivalence.** ``min`` over a superset is never greater than
    ``min`` over a subset, so ``aggregated[metric]`` is monotonically
    non-increasing in the number of trials drawn — for every metric
    independently. Therefore stopping the moment all budgets are satisfied
    yields *exactly* the verdict that drawing all ``max_trials`` would have
    yielded — early stopping is a pure
    wall-clock optimisation with zero effect on pass/fail. This is why the usual
    optional-stopping objection does not apply here, and it is the reason this
    shape was chosen over simply raising ``trials``.

    The asymmetry is deliberate and matches where evidence is worth paying for:

    * **Passing is cheap.** A healthy host usually decides on the first trial,
      so the common path costs *less* than the unconditional ``DEFAULT_TRIALS``
      it replaces.
    * **Failing is expensive.** A verdict of "over budget" is only returned
      after ``max_trials``, i.e. on the maximum evidence the cap allows. Noise
      inflates latency but never deflates it, so a genuine regression keeps
      every trial slow and the minimum never crosses; a transient spike is
      outvoted by the trials that follow it.

    Returns the ``_aggregate_min_across_trials`` summary plus ``trials_used``,
    ``max_trials`` and ``decided`` — the last three make the *cost* and the
    *confidence* of a judgement visible instead of leaving them implicit, which
    is the gap that let four budgets sit inside their own measurement noise
    unnoticed.
    """
    if max_trials < 1:
        raise ValueError(f'max_trials must be >= 1, got {max_trials}')
    if not budgets:
        raise ValueError('budgets must name at least one LatencyBudget')
    for budget in budgets:
        if budget.metric not in _TRIAL_AGGREGATED_METRICS:
            raise ValueError(
                f'budget.metric {budget.metric!r} is not reduced across trials; '
                f'expected one of {_TRIAL_AGGREGATED_METRICS}'
            )
    summaries: list[dict[str, float]] = []
    aggregated: dict[str, float] = {}
    decided = False
    while len(summaries) < max_trials:
        summaries.append(trial_fn())
        aggregated = _aggregate_min_across_trials(summaries)
        if all(aggregated[b.metric] <= b.limit_us for b in budgets):
            decided = True
            break
    return {
        **aggregated,
        'trials_used': float(len(summaries)),
        'max_trials': float(max_trials),
        'decided': decided,
    }


def measure_latency_us_for_budget(
    func: Callable[[], Any],
    *,
    iters: int,
    budget: LatencyBudget,
    max_trials: int = DEFAULT_MAX_TRIALS,
    warmup: int = 50,
    disable_gc: bool = True,
) -> dict[str, float]:
    """Measure ``func`` against ``budget`` using the sequential reducer.

    The measurement helpers above (``measure_latency_us`` /
    ``measure_latency_us_robust``) deliberately do **not** know about budgets —
    the ``.bench-snapshots/`` time-series path consumes them and must keep
    producing a threshold-independent number. This is the *gate* helper: it
    knows the threshold, which is precisely what makes stopping early possible.

    The judge is unchanged. Pass the result to ``assert_latency_budget`` exactly
    as a ``measure_latency_us_robust`` result, so adopting this helper costs a
    consumer one call site and no change to how a budget is expressed.
    """
    return reduce_trials_until_decided(
        lambda: measure_latency_us(
            func, iters=iters, warmup=warmup, disable_gc=disable_gc,
        ),
        budgets=(budget,),
        max_trials=max_trials,
    )


def assert_latency_budget(stats: dict[str, float], budget: LatencyBudget) -> None:
    """Raise ``AssertionError`` when a measured stat exceeds its budget."""
    actual = stats[budget.metric]
    if actual > budget.limit_us:
        raise AssertionError(
            f"{budget.name} {budget.metric}={actual:.2f}us > "
            f"{budget.limit_us:.2f}us budget"
        )


def print_latency_summary(label: str, stats: dict[str, float]) -> None:
    """Print a consistent CLI summary for benchmark scripts."""
    print(f'{label} (n={int(stats["iters"])}):')
    print(f'  p50  = {stats["p50_us"]:8.2f} us')
    print(f'  p95  = {stats["p95_us"]:8.2f} us')
    print(f'  p99  = {stats["p99_us"]:8.2f} us')
    print(f'  mean = {stats["mean_us"]:8.2f} us')
    print(f'  max  = {stats["max_us"]:8.2f} us')
