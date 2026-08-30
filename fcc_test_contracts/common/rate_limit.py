"""In-process fixed-window rate limiter — the *state* half of the policy (2026-07-19).

:mod:`domain.services.rate_limit_policy` owns every **decision** (budget size,
which rule a path gets, which identity a request is charged to, how long until
the window resets). This module owns the only thing that cannot be pure: the
per-key counters, the clock, and the memory bound.

It lives in ``application/common`` for the same reason
:mod:`application.common.metrics_middleware` does — Session / Headless /
Platform all need it and it must stay dependency-free (stdlib + domain only;
sealed by ``TestApplicationCommonPurity``). No FastAPI, no Starlette, no
infrastructure imports.

Design notes
------------
- **Thread-safe** — every web surface runs on an ASGI server with a thread
  pool; the counter dict is guarded by a ``threading.Lock`` exactly like the
  repository's other global caches. The critical section is a few dict
  operations, so contention is negligible next to request handling.
- **Monotonic clock by default** — wall-clock jumps (NTP step, DST) must not
  hand out a free window or freeze a caller out. ``time.monotonic`` is the
  default and is injectable for tests (no ``sleep`` in the suite).
- **Bounded memory, in O(1)** — a limiter keyed by client identity is itself a
  target: a flood from many distinct keys would grow the dict without bound and
  turn the defense into a memory-exhaustion DoS. ``max_tracked_keys`` caps it and
  eviction pops the least-recently-seen entry — a single ``OrderedDict.popitem``.
  An earlier draft also swept the dict for expired windows first; that sweep was
  ``O(n)`` *under the lock* and, once the cap was reached, ran on **every**
  request, converting a key-rotation flood into a CPU/lock-contention
  amplifier — the very DoS this class defends against. LRU order already
  subsumes it (an expired window is by definition older than any live one), so
  the sweep is gone. Eviction can only ever *forgive* a caller (it never denies
  one that is within budget), so the failure mode is safe.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Optional

from fcc_test_contracts.common.rate_limit_policy import RateLimitRule


__all__ = [
    'DEFAULT_MAX_TRACKED_KEYS',
    'FixedWindowRateLimiter',
    'RateLimitOutcome',
]


#: Upper bound on tracked keys. 8192 distinct callers per process is far beyond
#: any real deployment (a chamber lab has tens of operators and a handful of
#: scrapers) while keeping the worst-case footprint trivial: each entry is one
#: short string plus two numbers, i.e. low hundreds of KB at the cap.
DEFAULT_MAX_TRACKED_KEYS = 8192


@dataclass(frozen=True)
class RateLimitOutcome:
    """Result of charging one request against a key's budget.

    ``retry_after_seconds`` is only meaningful when ``allowed`` is ``False``;
    ``limit`` / ``remaining`` are surfaced as response headers so a well-behaved
    client can self-throttle before being denied.
    """

    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class FixedWindowRateLimiter:
    """Fixed-window counters keyed by an opaque string.

    The limiter is deliberately ignorant of HTTP: the caller resolves the key
    and the rule from the pure policy and hands both in. That keeps this class
    reusable for any future non-HTTP throttle (e.g. a WS connect storm) without
    growing surface-specific knowledge.
    """

    def __init__(
        self,
        *,
        clock: Optional[Callable[[], float]] = None,
        max_tracked_keys: int = DEFAULT_MAX_TRACKED_KEYS,
    ) -> None:
        if max_tracked_keys <= 0:
            raise ValueError('max_tracked_keys must be positive')
        self._clock = clock or time.monotonic
        self._max_tracked_keys = int(max_tracked_keys)
        self._lock = threading.Lock()
        # key -> [window_start, count]. OrderedDict so the least-recently-seen
        # key is the cheap eviction victim under the cap.
        self._windows: "OrderedDict[str, list]" = OrderedDict()

    @property
    def tracked_keys(self) -> int:
        """Current number of tracked keys (diagnostics / memory-bound tests)."""
        with self._lock:
            return len(self._windows)

    def check(self, key: str, rule: RateLimitRule) -> RateLimitOutcome:
        """Charge one request against ``key`` under ``rule`` and decide.

        A denied request still counts toward the window — otherwise a caller
        that keeps hammering while throttled would reset nothing and the
        window boundary would be the only relief. Counting denials also means a
        sustained flood keeps the window pinned, which is the intent.
        """
        now = float(self._clock())
        with self._lock:
            state = self._windows.get(key)
            if state is None or rule.is_window_expired(window_start=state[0], now=now):
                state = [now, 0]
            state[1] += 1
            self._windows[key] = state
            self._windows.move_to_end(key)
            if len(self._windows) > self._max_tracked_keys:
                self._evict_locked(protected=key)

            window_start, count = state[0], state[1]

        allowed = rule.is_allowed(count_in_window=count)
        remaining = max(0, rule.max_requests - count)
        retry_after = (
            0
            if allowed
            else rule.retry_after_seconds(window_start=window_start, now=now)
        )
        return RateLimitOutcome(
            allowed=allowed,
            limit=rule.max_requests,
            remaining=remaining,
            retry_after_seconds=retry_after,
        )

    def peek(self, key: str, rule: RateLimitRule) -> RateLimitOutcome:
        """Answer as :meth:`check` would, **without** charging.

        ⚠️ This exists so a caller can *enforce before* an expensive operation and
        *charge after* it, once the verdict is known. The credential account tier
        needs exactly that split: charging every attempt — successes included —
        turned attempts-to-429 and ``Retry-After`` into a channel that reports
        whether and when an account last authenticated (measured twice by
        adversarial review, once in each direction).

        ⚠️ **Peek-then-charge is not atomic, and that is acceptable here.** Two
        concurrent attempts can both peek at the last free slot and both proceed,
        so the budget can overshoot by the in-flight count. It cannot overshoot
        *unboundedly* — every failure still charges, so the window closes on the
        next request — and the alternative (charge first) is the oracle. The layer
        below is also unaffected: the database lockout is a single atomic UPDATE.
        """
        now = float(self._clock())
        with self._lock:
            state = self._windows.get(key)
            if state is None or rule.is_window_expired(window_start=state[0], now=now):
                window_start, count = now, 0
            else:
                window_start, count = state[0], state[1]
        prospective = count + 1
        allowed = rule.is_allowed(count_in_window=prospective)
        return RateLimitOutcome(
            allowed=allowed,
            limit=rule.max_requests,
            remaining=max(0, rule.max_requests - count),
            retry_after_seconds=(
                0 if allowed
                else rule.retry_after_seconds(window_start=window_start, now=now)
            ),
        )

    def _evict_locked(self, *, protected: str) -> None:
        """Drop least-recently-seen keys until back under the cap.

        Caller must hold the lock. O(1) per evicted key — no scan. The key being
        charged right now was just moved to the end, so it is the last candidate;
        the explicit guard makes that independent of ordering details (and covers
        ``max_tracked_keys == 1``).
        """
        while len(self._windows) > self._max_tracked_keys:
            victim, state = self._windows.popitem(last=False)
            if victim == protected:
                self._windows[victim] = state
                break
