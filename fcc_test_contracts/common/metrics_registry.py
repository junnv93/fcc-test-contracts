"""Generic in-process Prometheus metrics registry — OBS-2 phase 3 (2026-05-22).

도메인 SSOT — Session API (OBS-2 phase 2, 2026-05-25) 가 처음 도입한
namespace-fixed registry 를 ``ApiMetricsRegistry(namespace, *,
enable_websocket=...)`` 로 namespace 매개변수화한 후 ``application/common/``
으로 추출. Session/Headless 양 web surface 가 같은 SSOT 를 재사용한다.

Design contract
---------------
- **stdlib only** — ``threading`` (RLock) + ``bisect`` (O(log N) bucket
  classification) + ``time``. No ``prometheus_client`` dependency.
- **namespace-parameterized** — caller injects ``namespace='fcc_session'`` /
  ``'fcc_headless'`` / arbitrary string; metric body name template
  builds ``{namespace}_request_total`` etc. (Prometheus convention —
  service prefix is service-specific, naming SSOT is shared).
- **websocket-optional** — ``enable_websocket=False`` (Headless API,
  HTTP-only) → WS section is omitted from ``render()`` and the three WS
  mutators (``inc_ws_connection``, ``dec_ws_connection``,
  ``inc_ws_closed_total``) raise ``RuntimeError`` (loud failure — silent
  no-op would hide a deployment error). Session API stays
  ``enable_websocket=True`` (default).
- **adapter-injected** — composition root (``session_api_composition`` /
  ``headless_api_composition``) composes one registry instance and shares
  it with the FastAPI router middleware + ``/metrics`` endpoint. Tests
  get isolation by passing ``metrics_registry=None`` or instantiating
  directly.
- **thread-safe** — every write acquires ``RLock``. ``render()`` snapshots
  under lock so a concurrent ``record_request`` cannot tear a Prometheus
  text line.
- **operation/status SSOT** — operations match the API's
  ``api_contracts.{SESSION,HEADLESS}_API_OPERATIONS`` keys; status is one
  of ``{ok, denied, error}`` matching the router's existing ``_log_op``
  status token. Invariant tests verify the join.
- **dependency-free purity** — stdlib only. Verified by
  ``TestApplicationCommonPurity`` (``application/common/**`` must not
  import infrastructure/PySide6/FastAPI/sqlalchemy/openpyxl/pandas/etc.).
"""
from __future__ import annotations

import bisect
import math
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Iterable, Mapping


__all__ = [
    'ApiMetricsRegistry',
    'CounterFamily',
    'GaugeFamily',
    'WS_STATE_CONNECTING',
    'WS_STATE_OPEN',
    'WS_STATE_CLOSING',
    'VALID_WS_STATES',
    'WS_CLOSE_REASON_NORMAL',
    'WS_CLOSE_REASON_ERROR',
    'WS_CLOSE_REASON_TIMEOUT',
    'WS_CLOSE_REASON_DENIED',
    'VALID_WS_CLOSE_REASONS',
    'STATUS_OK',
    'STATUS_DENIED',
    'STATUS_ERROR',
    'VALID_STATUSES',
    'METRICS_BUCKETS_ENV',
    'metrics_buckets_from_env',
    # OBS-2 phase 3 follow-up (2026-05-23) — namespace SSOT + middleware helpers
    'METRICS_NAMESPACE_SESSION',
    'METRICS_NAMESPACE_HEADLESS',
    'METRICS_NAMESPACE_PLATFORM',
    'status_token_from_http_code',
    'build_route_pattern_index',
    'lookup_operation',
]


# ── Namespace constants — single source of truth ─────────────────────────────
# OBS-2 phase 3 follow-up (2026-05-23) — composition root literal 폐기.
# ``session_api_composition`` + ``headless_api_composition`` 가 import 사용.
# Platform read surface (FE-P0d S5, 2026-05-27) 도 동일 SSOT 위임 — HTTP-only.
METRICS_NAMESPACE_SESSION = 'fcc_session'
METRICS_NAMESPACE_HEADLESS = 'fcc_headless'
METRICS_NAMESPACE_PLATFORM = 'fcc_platform'


# ── Constants — single source of truth for the status taxonomy ─────────────
STATUS_OK = 'ok'
STATUS_DENIED = 'denied'
STATUS_ERROR = 'error'
VALID_STATUSES: frozenset[str] = frozenset({STATUS_OK, STATUS_DENIED, STATUS_ERROR})


def status_token_from_http_code(status_code: int) -> str:
    """Map an HTTP response status code to the metric ``status`` label.

    OBS-2 phase 3 follow-up (2026-05-23) — Session/Headless 미들웨어가 동일한
    매핑 if/elif/else 를 인라인으로 보유하던 패턴 SSOT 통합.

    Taxonomy (Envoy / nginx access log convention 유사):
    - 401 / 403  → ``denied`` (auth/authZ 거부)
    - 4xx / 5xx  → ``error``
    - 그 외      → ``ok``
    """
    if status_code in (401, 403):
        return STATUS_DENIED
    if status_code >= 400:
        return STATUS_ERROR
    return STATUS_OK


# ── Route pattern helpers ──────────────────────────────────────────────────
# OBS-2 phase 3 follow-up (2026-05-23) — Session/Headless 양 router 의 path →
# operation 역인덱스 통일. Session 은 단순 path 였으나 future-safe 하게 regex
# 통일 (Session 6 routes / Headless 15 routes — O(N) iterate 비용 negligible).
# WebSocket 라우트는 제외 (별 gauge 채널).

_PATH_PARAM_RE = re.compile(r'\{[^}]+\}')


def build_route_pattern_index(
    routes: Mapping[str, tuple[str, str]],
) -> list[tuple[re.Pattern[str], str]]:
    """Compile a list of ``(compiled_pattern, operation_name)`` from a route map.

    ``routes`` shape mirrors ``SESSION_API_ROUTES`` / ``HEADLESS_API_ROUTES`` —
    ``{op_name: (method, path_template)}``. FastAPI-style path params
    (``{job_id}`` etc.) become ``[^/]+`` regex groups.

    WebSocket routes (``method == 'WEBSOCKET'``) are excluded — WS endpoints
    have their own gauge/counter channels (``inc_ws_connection`` etc.) and
    must not be observed as HTTP request latency.
    """
    patterns: list[tuple[re.Pattern[str], str]] = []
    for op, (method, path_template) in routes.items():
        if method == 'WEBSOCKET':
            continue
        regex_str = '^' + _PATH_PARAM_RE.sub(r'[^/]+', path_template) + '$'
        patterns.append((re.compile(regex_str), op))
    return patterns


def lookup_operation(
    patterns: list[tuple[re.Pattern[str], str]],
    request_path: str,
) -> str | None:
    """Return the canonical operation name for ``request_path`` or ``None``.

    Used by ``create_metrics_middleware`` to map an incoming HTTP request
    path to the contract-declared operation. Returning ``None`` deliberately
    skips the metric observation — used for self-referential signals
    (``/session/metrics`` / ``/headless/metrics`` are intentionally not in
    the route SSOT to avoid drowning out SLO signal).
    """
    for pattern, op in patterns:
        if pattern.match(request_path):
            return op
    return None

WS_STATE_CONNECTING = 'connecting'
WS_STATE_OPEN = 'open'
WS_STATE_CLOSING = 'closing'
VALID_WS_STATES: frozenset[str] = frozenset({
    WS_STATE_CONNECTING, WS_STATE_OPEN, WS_STATE_CLOSING,
})

# Envoy ``upstream_cx_destroyed_<reason>`` / nginx ``upstream_status`` 패턴
# (HIGH-4, 2026-05-25) — close reasons 분리로 dashboards 가 'clean disconnect'
# vs 'server timeout' vs 'auth denied' 분간 가능.
WS_CLOSE_REASON_NORMAL = 'normal'    # WebSocketDisconnect or context manager exit
WS_CLOSE_REASON_ERROR = 'error'      # Exception during streaming
WS_CLOSE_REASON_TIMEOUT = 'timeout'  # Heartbeat / lease timeout
WS_CLOSE_REASON_DENIED = 'denied'    # Auth failed before accept()
VALID_WS_CLOSE_REASONS: frozenset[str] = frozenset({
    WS_CLOSE_REASON_NORMAL,
    WS_CLOSE_REASON_ERROR,
    WS_CLOSE_REASON_TIMEOUT,
    WS_CLOSE_REASON_DENIED,
})


# ── Default bucket boundaries — milliseconds ───────────────────────────────
# Matches ``prometheus_client.Histogram`` DEFAULT_BUCKETS scaled to ms. The
# values cover sub-millisecond GET /is-running (5ms bucket) through slow
# /start operations (5s bucket) for a typical API workload.
_DEFAULT_BUCKETS_MS: tuple[float, ...] = (
    5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0,
)
METRICS_BUCKETS_ENV = 'FCC_METRICS_BUCKETS_MS'


def metrics_buckets_from_env(
    environ: Mapping[str, str] | None = None,
) -> tuple[float, ...]:
    """Return histogram bucket boundaries from ``FCC_METRICS_BUCKETS_MS``.

    Unset env keeps the built-in defaults. When configured, the value must be
    a comma-separated list of positive finite millisecond boundaries. Invalid
    input raises ``ValueError`` so deployment config drift is noisy.
    """
    source = os.environ if environ is None else environ
    raw = source.get(METRICS_BUCKETS_ENV)
    if raw is None:
        return _DEFAULT_BUCKETS_MS
    parts = [part.strip() for part in raw.split(',')]
    if not parts or any(part == '' for part in parts):
        raise ValueError(
            f'{METRICS_BUCKETS_ENV} must be comma-separated positive finite numbers'
        )

    values: list[float] = []
    for part in parts:
        try:
            value = float(part)
        except ValueError as exc:
            raise ValueError(
                f'{METRICS_BUCKETS_ENV} contains non-numeric boundary {part!r}'
            ) from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                f'{METRICS_BUCKETS_ENV} boundary {part!r} must be positive and finite'
            )
        values.append(value)

    boundaries = tuple(sorted(values))
    if len(set(boundaries)) != len(boundaries):
        raise ValueError(f'{METRICS_BUCKETS_ENV} must not contain duplicate boundaries')
    return boundaries


def _format_le(boundary: float) -> str:
    """Render a bucket boundary value in Prometheus-canonical form.

    ``5.0`` → ``"5.0"`` / ``+Inf`` → ``"+Inf"`` / non-finite raises.
    """
    if boundary == float('inf'):
        return '+Inf'
    return f'{boundary:g}' if '.' in f'{boundary:g}' else f'{boundary:g}.0'


def _format_gauge(value: float) -> str:
    """Render a gauge value: integral floats as ints (``3.0`` → ``"3"``),
    otherwise canonical float (``1.5`` → ``"1.5"``). Non-finite → ``"0"``
    (defensive — a gauge never emits NaN/Inf)."""
    if not math.isfinite(value):
        return '0'
    if float(value).is_integer():
        return str(int(value))
    return f'{value:g}'


def _escape_label_value(value: str) -> str:
    """Escape ``\\``, ``"``, and newline per Prometheus text format spec."""
    return (
        value.replace('\\', '\\\\')
        .replace('"', '\\"')
        .replace('\n', '\\n')
    )


def _render_labels(labels: Mapping[str, str]) -> str:
    """Render a ``{k="v",k2="v2"}`` block; empty mapping → ``""``."""
    if not labels:
        return ''
    parts = [
        f'{k}="{_escape_label_value(v)}"'
        for k, v in sorted(labels.items())
    ]
    return '{' + ','.join(parts) + '}'


@dataclass(frozen=True)
class GaugeFamily:
    """A declared gauge metric family (domain-agnostic).

    ``name`` is the base metric name WITHOUT the registry namespace prefix
    (render() prepends ``{namespace}_``). ``label_key`` empty → a single
    unlabeled series; non-empty → one series per ``label_values`` entry, each
    rendered as ``{label_key}="<value>"``. All declared series default to 0 so
    the metric name is part of the exposition SSOT before any sample (alert-parity
    gate sees it). Values are refreshed at scrape time via ``set_gauge``.
    """

    name: str
    help: str
    label_key: str = ''
    label_values: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CounterFamily:
    """A bounded, declared counter family with optional fixed label tuples.

    ``label_names`` and ``label_values`` are generic so the common registry
    does not need to know platform/session vocabulary.  Every declared tuple
    is rendered from zero, which makes the exposition stable before traffic
    arrives and prevents callers from introducing unbounded labels at runtime.
    """

    name: str
    help: str
    label_names: tuple[str, ...] = field(default_factory=tuple)
    label_values: tuple[tuple[str, ...], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.name or not self.help:
            raise ValueError('counter name and help are required')
        if len(set(self.label_names)) != len(self.label_names):
            raise ValueError('counter label names must be unique')
        if self.label_names and not self.label_values:
            raise ValueError('labeled counter families must declare label values')
        expected = len(self.label_names)
        for values in self.label_values:
            if len(values) != expected:
                raise ValueError('counter label value tuples must match label_names')
            if any(not isinstance(value, str) for value in values):
                raise TypeError('counter label values must be strings')
        if len(set(self.label_values)) != len(self.label_values):
            raise ValueError('counter label value tuples must be unique')


class _Histogram:
    """One ``(operation, status)`` histogram bucket family.

    ``bisect_left`` classifies a sample value into the lowest bucket whose
    boundary is >= the sample. Cumulative counts are computed lazily at
    render time so write-path latency is O(log N) bucket lookup + O(1)
    list append.
    """

    __slots__ = ('_buckets_ms', '_counts', '_count', '_sum')

    def __init__(self, buckets_ms: tuple[float, ...]) -> None:
        self._buckets_ms = buckets_ms
        # +Inf 버킷은 별도 카운터 — 마지막 finite bucket 보다 큰 모든 sample.
        # _counts length = len(buckets_ms) + 1 (마지막 = +Inf).
        self._counts: list[int] = [0] * (len(buckets_ms) + 1)
        self._count = 0
        self._sum = 0.0

    def observe(self, value_ms: float) -> None:
        idx = bisect.bisect_left(self._buckets_ms, value_ms)
        if idx > len(self._buckets_ms):
            idx = len(self._buckets_ms)
        self._counts[idx] += 1
        self._count += 1
        self._sum += value_ms

    def cumulative(self) -> list[tuple[float, int]]:
        """Return ``[(boundary, cumulative_count), ...]`` with ``+Inf`` last."""
        running = 0
        out: list[tuple[float, int]] = []
        for i, boundary in enumerate(self._buckets_ms):
            running += self._counts[i]
            out.append((boundary, running))
        running += self._counts[-1]
        out.append((float('inf'), running))
        return out

    @property
    def count(self) -> int:
        return self._count

    @property
    def sum(self) -> float:
        return self._sum


class ApiMetricsRegistry:
    """In-process Prometheus registry — generic API metrics SSOT.

    OBS-2 phase 3 (2026-05-22) — Session API 가 처음 도입한
    namespace-fixed registry 를 namespace 매개변수화로 일반화. Session/Headless
    양 composition root 가 동일 클래스를 다른 namespace 로 인스턴스화한다.

    Args:
        namespace: Metric name prefix (e.g. ``'fcc_session'``,
            ``'fcc_headless'``). Empty string raises ``ValueError`` —
            Prometheus convention requires service prefix.
        enable_websocket: 기본 ``True``. ``False`` 시 (Headless API, HTTP-only)
            WS 관련 3 mutator 는 ``RuntimeError`` raise + ``render()`` 출력에
            WS section 부재. Silent no-op 회피 (deployment error 감추기 차단).
        buckets_ms: Histogram bucket boundaries. ``None`` 시
            :func:`metrics_buckets_from_env` (env override 또는 default).
    """

    DEFAULT_BUCKETS_MS: tuple[float, ...] = _DEFAULT_BUCKETS_MS

    def __init__(
        self,
        *,
        namespace: str,
        enable_websocket: bool = True,
        buckets_ms: Iterable[float] | None = None,
        gauge_families: Iterable['GaugeFamily'] | None = None,
        counter_families: Iterable['CounterFamily'] | None = None,
    ) -> None:
        if not isinstance(namespace, str) or not namespace:
            raise ValueError(
                'namespace must be a non-empty string (e.g. "fcc_session")'
            )
        # Prometheus metric name spec: [a-zA-Z_:][a-zA-Z0-9_:]* — 우리 namespace
        # 는 prefix 이므로 동일 규칙 적용.
        if not namespace[0].isalpha() and namespace[0] != '_':
            raise ValueError(
                f'namespace {namespace!r} must start with letter or underscore'
            )
        if not all(c.isalnum() or c == '_' for c in namespace):
            raise ValueError(
                f'namespace {namespace!r} must contain only [a-zA-Z0-9_]'
            )
        self._namespace = namespace
        self._enable_websocket = enable_websocket

        boundaries = _normalize_buckets(buckets_ms) if buckets_ms is not None \
            else metrics_buckets_from_env()
        if not boundaries:
            raise ValueError('buckets_ms must contain at least one boundary')
        self._buckets_ms: tuple[float, ...] = boundaries
        self._lock = threading.RLock()
        self._histograms: dict[tuple[str, str], _Histogram] = {}
        self._ws_gauge: dict[str, int] = {}
        self._ws_closed_total: int = 0
        self._ws_closed_by_reason: dict[str, int] = {}
        # Generic declared gauge families (domain-agnostic). A caller (e.g. the
        # platform composition) DECLARES families at construction; render() always
        # emits every declared family's series (default 0) so the metric NAME is
        # part of the registry's exposition SSOT even before a sample — this is
        # what lets the alert-parity gate see derived gauges. Values are refreshed
        # at scrape time by a collector via set_gauge().
        self._gauge_families: dict[str, GaugeFamily] = {
            f.name: f for f in (gauge_families or ())
        }
        self._scrape_hooks: list = []
        self._gauge_values: dict[tuple[str, str], float] = {}
        for fam in self._gauge_families.values():
            for label_value in (fam.label_values or ('',)):
                self._gauge_values[(fam.name, label_value)] = 0.0
        families = tuple(counter_families or ())
        for family in families:
            if not isinstance(family, CounterFamily):
                raise TypeError('counter_families must contain CounterFamily values')
        if len({family.name for family in families}) != len(families):
            raise ValueError('counter family names must be unique')
        if any(family.name in self._gauge_families for family in families):
            raise ValueError('counter and gauge family names must be unique')
        self._counter_families: dict[str, CounterFamily] = {
            family.name: family for family in families
        }
        self._counter_values: dict[tuple[str, tuple[str, ...]], int] = {}
        for family in families:
            for label_values in (family.label_values or ((),)):
                self._counter_values[(family.name, label_values)] = 0

    # ── Identity ───────────────────────────────────────────────────────────

    @property
    def namespace(self) -> str:
        return self._namespace

    @property
    def websocket_enabled(self) -> bool:
        return self._enable_websocket

    # ── Histogram (request latency) ────────────────────────────────────────

    def record_request(
        self,
        operation: str,
        status: str,
        latency_ms: float,
    ) -> None:
        """Observe one request latency sample under ``(operation, status)``.

        ``status`` must be one of :data:`VALID_STATUSES`. Negative latency
        is clamped to 0 (clock skew defensive — never raises).
        """
        if status not in VALID_STATUSES:
            raise ValueError(
                f'invalid status {status!r}; expected one of {sorted(VALID_STATUSES)}'
            )
        sample = max(0.0, float(latency_ms))
        key = (operation, status)
        with self._lock:
            hist = self._histograms.get(key)
            if hist is None:
                hist = _Histogram(self._buckets_ms)
                self._histograms[key] = hist
            hist.observe(sample)

    # ── Scrape-time refresh hooks ───────────────────────────────────────────

    def add_scrape_hook(self, hook) -> None:
        """Call ``hook()`` at the start of every :meth:`render`.

        ⚠️ **Why a push gauge cannot answer "how old is this".** A value written
        only when something happens is, between happenings, a *copy* of a past
        observation — and for a freshness gauge that is exactly wrong: the number
        stops advancing at the moment the answer starts going stale. Adversarial
        review measured it on a live stack: an observation-age gauge stayed
        bit-identical across 150 s of wall clock, then jumped 194 s when an
        unrelated request — one the axis deliberately does **not** count —
        happened to trigger a republish. Which value an operator read therefore
        depended on traffic the axis states it ignores.

        A hook moves the computation to the moment of the question, which is the
        only moment at which "now" is defined. Hooks are total: a raising hook is
        skipped rather than allowed to fail the scrape, because ``/metrics``
        returning 500 loses **every** series, not just the broken one.
        """
        with self._lock:
            if hook not in self._scrape_hooks:
                self._scrape_hooks.append(hook)

    def _run_scrape_hooks(self) -> None:
        with self._lock:
            hooks = list(self._scrape_hooks)
        for hook in hooks:
            try:
                hook()
            except Exception:  # noqa: BLE001 — a scrape must not fail wholesale
                pass

    # ── Declared gauge families (generic, refreshed at scrape time) ──────────

    def declare_gauge_families(
        self, families: Iterable['GaugeFamily'],
    ) -> None:
        """Add gauge families after construction. **Idempotent and additive.**

        ⚠️ **Why this exists** (2026-08-23). Constructor-only declaration means
        the *composition* must know every metric its components will publish, so
        a component that needs a gauge has to be remembered in each of the three
        surface compositions — and in every test that builds a registry. The
        peer-axis observation is exactly that shape: it is installed by shared
        middleware wiring, not by a per-surface collector. Forgetting one site
        does not fail loudly at that site; it fails inside ``set_gauge`` later,
        which is the wrong place to learn about it.

        So a component may declare what it publishes, next to the code that
        publishes it. That is the same ownership rule the counter/gauge family
        SSOTs already follow — the *name* belongs to the module that emits it.

        ⚠️ **Re-declaring the identical family is a no-op; re-declaring the same
        NAME with a different definition raises.** Silently accepting the second
        definition would let two components disagree about a metric's labels and
        leave whichever ran last as the winner — a drift that only shows up as a
        rejected ``set_gauge`` label at runtime.

        ⚠️ **A gauge name may not collide with a counter name**, mirroring the
        constructor's check: one exposition cannot carry both TYPEs for a name.
        """
        # ⚠️ **Materialise before touching state.** A generator that raises
        # mid-iteration would otherwise leave a partially-declared registry —
        # some families present, some absent, and no exception the caller can
        # act on beyond the one it already got (adversarial review, 2026-08-23).
        declared = tuple(families)
        with self._lock:
            for family in declared:
                if not isinstance(family, GaugeFamily):
                    raise TypeError(
                        'declare_gauge_families expects GaugeFamily values'
                    )
                existing = self._gauge_families.get(family.name)
                if existing is not None:
                    if existing != family:
                        raise ValueError(
                            f'gauge family {family.name!r} is already declared '
                            f'with a different definition ({existing!r} vs '
                            f'{family!r}) — two owners of one metric name.'
                        )
                    continue
                if family.name in self._counter_families:
                    raise ValueError(
                        f'{family.name!r} is already a counter family; counter '
                        'and gauge family names must be unique'
                    )
                self._gauge_families[family.name] = family
                for label_value in (family.label_values or ('',)):
                    self._gauge_values.setdefault((family.name, label_value), 0.0)

    def set_gauge(self, name: str, value: float, *, label_value: str = '') -> None:
        """Set a declared gauge family series value.

        ``name`` must be a declared :class:`GaugeFamily` (constructor). For a
        labeled family, ``label_value`` must be one of its declared
        ``label_values``. Unknown name/label raises (no silent metric drift).
        """
        family = self._gauge_families.get(name)
        if family is None:
            raise ValueError(
                f'gauge family {name!r} not declared; declared: '
                f'{sorted(self._gauge_families)}'
            )
        key_label = label_value if family.label_key else ''
        if family.label_key and label_value not in (family.label_values or ()):
            raise ValueError(
                f'gauge {name!r} label {label_value!r} not in declared '
                f'{family.label_values!r}'
            )
        with self._lock:
            self._gauge_values[(name, key_label)] = float(value)

    # ── Declared counter families (generic, bounded labels) ────────────────

    def inc_counter(
        self,
        name: str,
        *,
        labels: Mapping[str, str] | None = None,
        amount: int = 1,
    ) -> None:
        """Increment one declared counter series.

        The family and every allowed label tuple are declared at composition
        time.  Runtime callers cannot create a new label value or family.
        """
        family = self._counter_families.get(name)
        if family is None:
            raise ValueError(
                f'counter family {name!r} not declared; declared: '
                f'{sorted(self._counter_families)}'
            )
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError('counter amount must be a positive integer')
        supplied = dict(labels or {})
        if set(supplied) != set(family.label_names):
            raise ValueError(
                f'counter {name!r} labels must be exactly '
                f'{family.label_names!r}'
            )
        label_values = tuple(supplied[label] for label in family.label_names)
        if any(not isinstance(value, str) for value in label_values):
            raise TypeError('counter label values must be strings')
        allowed = family.label_values or ((),)
        if label_values not in allowed:
            raise ValueError(
                f'counter {name!r} labels {supplied!r} are not declared'
            )
        with self._lock:
            key = (name, label_values)
            self._counter_values[key] = self._counter_values.get(key, 0) + amount

    def counter_value(
        self,
        name: str,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> int:
        """Return one declared counter series without creating a new series."""
        family = self._counter_families.get(name)
        if family is None:
            raise ValueError(f'counter family {name!r} not declared')
        supplied = dict(labels or {})
        if set(supplied) != set(family.label_names):
            raise ValueError(
                f'counter {name!r} labels must be exactly '
                f'{family.label_names!r}'
            )
        label_values = tuple(supplied[label] for label in family.label_names)
        if label_values not in (family.label_values or ((),)):
            raise ValueError(f'counter {name!r} labels {supplied!r} are not declared')
        with self._lock:
            return self._counter_values.get((name, label_values), 0)

    # ── Gauge (WS connection count by state) ───────────────────────────────

    def inc_ws_connection(self, state: str = WS_STATE_OPEN) -> None:
        """Increment a WS state gauge. Raises if WebSocket support disabled."""
        if not self._enable_websocket:
            raise RuntimeError(
                f'WebSocket metrics disabled for namespace {self._namespace!r} '
                '— composition root must enable_websocket=True'
            )
        if state not in VALID_WS_STATES:
            raise ValueError(
                f'invalid WS state {state!r}; expected one of {sorted(VALID_WS_STATES)}'
            )
        with self._lock:
            self._ws_gauge[state] = self._ws_gauge.get(state, 0) + 1

    def dec_ws_connection(self, state: str = WS_STATE_OPEN) -> None:
        if not self._enable_websocket:
            raise RuntimeError(
                f'WebSocket metrics disabled for namespace {self._namespace!r} '
                '— composition root must enable_websocket=True'
            )
        if state not in VALID_WS_STATES:
            raise ValueError(
                f'invalid WS state {state!r}; expected one of {sorted(VALID_WS_STATES)}'
            )
        with self._lock:
            current = self._ws_gauge.get(state, 0)
            self._ws_gauge[state] = max(0, current - 1)

    def inc_ws_closed_total(self, reason: str = WS_CLOSE_REASON_NORMAL) -> None:
        """Cumulative WS disconnect counter. Raises if WS disabled."""
        if not self._enable_websocket:
            raise RuntimeError(
                f'WebSocket metrics disabled for namespace {self._namespace!r} '
                '— composition root must enable_websocket=True'
            )
        if reason not in VALID_WS_CLOSE_REASONS:
            raise ValueError(
                f'invalid WS close reason {reason!r}; expected one of '
                f'{sorted(VALID_WS_CLOSE_REASONS)}'
            )
        with self._lock:
            self._ws_closed_total += 1
            self._ws_closed_by_reason[reason] = (
                self._ws_closed_by_reason.get(reason, 0) + 1
            )

    # ── Read-side ───────────────────────────────────────────────────────────

    def ws_connections(self, state: str = WS_STATE_OPEN) -> int:
        # Read-side is permissive — return 0 when WS disabled rather than
        # raising, so generic dashboards that probe both APIs do not crash.
        if not self._enable_websocket:
            return 0
        with self._lock:
            return self._ws_gauge.get(state, 0)

    def ws_closed_total(self, reason: str | None = None) -> int:
        if not self._enable_websocket:
            return 0
        with self._lock:
            if reason is None:
                return self._ws_closed_total
            if reason not in VALID_WS_CLOSE_REASONS:
                raise ValueError(
                    f'invalid WS close reason {reason!r}; expected one of '
                    f'{sorted(VALID_WS_CLOSE_REASONS)}'
                )
            return self._ws_closed_by_reason.get(reason, 0)

    def request_count(self, operation: str, status: str) -> int:
        with self._lock:
            hist = self._histograms.get((operation, status))
            return hist.count if hist is not None else 0

    def request_sum_ms(self, operation: str, status: str) -> float:
        with self._lock:
            hist = self._histograms.get((operation, status))
            return hist.sum if hist is not None else 0.0

    def reset(self) -> None:
        """Drop all histogram + gauge + counter state."""
        with self._lock:
            self._histograms.clear()
            self._ws_gauge.clear()
            self._ws_closed_total = 0
            self._ws_closed_by_reason.clear()
            for key in self._counter_values:
                self._counter_values[key] = 0

    # ── Prometheus exposition format render ────────────────────────────────

    def render(self) -> str:
        """Return one Prometheus 0.0.4-format text block.

        The block contains:

        - ``{namespace}_request_total`` histogram (HELP + TYPE + buckets +
          _count + _sum for each (operation, status) family observed).
        - ``{namespace}_ws_connections`` gauge (only when WebSocket enabled).
        - ``{namespace}_ws_connections_closed_total`` counter (only when
          WebSocket enabled).
        """
        # ⚠️ Freshness is computed at the moment of the question, not at the
        # moment of the last event — see :meth:`add_scrape_hook`.
        self._run_scrape_hooks()
        ns = self._namespace
        with self._lock:
            hist_snapshot = dict(self._histograms)
            gauge_snapshot = dict(self._ws_gauge)
            closed_by_reason = dict(self._ws_closed_by_reason)
            gauge_values_snapshot = dict(self._gauge_values)
            counter_values_snapshot = dict(self._counter_values)

        out: list[str] = []
        # Histogram block ----------------------------------------------------
        out.append(
            f'# HELP {ns}_request_total API request latency histogram (ms).'
        )
        out.append(f'# TYPE {ns}_request_total histogram')
        for (op, status), hist in sorted(hist_snapshot.items()):
            labels_base = {'operation': op, 'status': status}
            for boundary, cum in hist.cumulative():
                labels = dict(labels_base)
                labels['le'] = _format_le(boundary)
                out.append(
                    f'{ns}_request_total_bucket{_render_labels(labels)} {cum}'
                )
            out.append(
                f'{ns}_request_total_count{_render_labels(labels_base)} {hist.count}'
            )
            out.append(
                f'{ns}_request_total_sum{_render_labels(labels_base)} {hist.sum}'
            )

        # Declared gauge families (generic; emitted regardless of WS support so
        # derived gauges like chamber availability appear on HTTP-only surfaces).
        for fam in sorted(self._gauge_families.values(), key=lambda f: f.name):
            metric = f'{ns}_{fam.name}'
            out.append(f'# HELP {metric} {fam.help}')
            out.append(f'# TYPE {metric} gauge')
            label_values = fam.label_values if fam.label_key else ('',)
            for label_value in label_values:
                key_label = label_value if fam.label_key else ''
                value = gauge_values_snapshot.get((fam.name, key_label), 0.0)
                rendered = _render_labels({fam.label_key: label_value}) if fam.label_key else ''
                out.append(f'{metric}{rendered} {_format_gauge(value)}')

        # Declared counter families (generic; every bounded series is emitted).
        for fam in sorted(self._counter_families.values(), key=lambda f: f.name):
            metric = f'{ns}_{fam.name}'
            out.append(f'# HELP {metric} {fam.help}')
            out.append(f'# TYPE {metric} counter')
            label_tuples = fam.label_values or ((),)
            for label_values in label_tuples:
                labels = dict(zip(fam.label_names, label_values))
                value = counter_values_snapshot.get((fam.name, label_values), 0)
                out.append(f'{metric}{_render_labels(labels)} {value}')

        # WS section omitted entirely when disabled (HTTP-only API).
        if not self._enable_websocket:
            return '\n'.join(out) + '\n'

        # Gauge block --------------------------------------------------------
        out.append(
            f'# HELP {ns}_ws_connections Active WebSocket connections by lifecycle state.'
        )
        out.append(f'# TYPE {ns}_ws_connections gauge')
        for state in (WS_STATE_CONNECTING, WS_STATE_OPEN, WS_STATE_CLOSING):
            if state not in gauge_snapshot:
                gauge_snapshot[state] = 0
        for state in sorted(gauge_snapshot.keys()):
            out.append(
                f'{ns}_ws_connections{_render_labels({"state": state})} {gauge_snapshot[state]}'
            )

        # Counter block ------------------------------------------------------
        out.append(
            f'# HELP {ns}_ws_connections_closed_total '
            'Cumulative WebSocket disconnect count by close reason.'
        )
        out.append(f'# TYPE {ns}_ws_connections_closed_total counter')
        for reason in sorted(VALID_WS_CLOSE_REASONS):
            count = closed_by_reason.get(reason, 0)
            out.append(
                f'{ns}_ws_connections_closed_total'
                f'{_render_labels({"reason": reason})} {count}'
            )

        return '\n'.join(out) + '\n'


def _normalize_buckets(buckets_ms: Iterable[float]) -> tuple[float, ...]:
    boundaries = tuple(sorted(float(value) for value in buckets_ms))
    if not boundaries:
        raise ValueError('buckets_ms must contain at least one boundary')
    for value in boundaries:
        if not math.isfinite(value) or value <= 0:
            raise ValueError('buckets_ms boundaries must be positive and finite')
    if len(set(boundaries)) != len(boundaries):
        raise ValueError('buckets_ms must not contain duplicate boundaries')
    return boundaries
