"""Liveness / readiness probe policy — pure domain SSOT (2026-07-20).

The three web surfaces disagreed about what "health" means. Session exposes one
``GET /session/health`` whose own docstring calls it a
"Liveness/readiness probe", Headless exposes ``health_check``, and Platform — the
one surface that is actually containerized in
``infra/docker-compose.central.yml`` and the one that owns a hard external
dependency (the central PostgreSQL) — exposed **nothing**, so its compose
healthcheck had to borrow the auth-exempt ``/platform/metrics`` endpoint.

Conflating the two probes is not cosmetic. An orchestrator uses them for two
*opposite* actions:

* **liveness** answers "is this process wedged?" → a failure means **restart me**.
  It must therefore never consult a dependency: if the central DB blips, a
  dependency-aware liveness probe restarts every API replica at once, which
  removes the capacity that would have absorbed the blip and turns a degraded
  minute into an outage.
* **readiness** answers "can I serve a request right now?" → a failure means
  **stop routing to me**, not restart me. This one *must* consult the
  dependency, otherwise a container that cannot reach the DB still receives
  traffic and every request 503s at the route boundary instead of at the load
  balancer.

This module owns the *decision* half — statuses, dependency names, the freshness
rule for the cached dependency verdict, and which paths are probe paths — as a
pure value object. The application layer owns the clock and the actual dependency
I/O (mirror of :mod:`domain.services.rate_limit_policy`: decision here, counters
in the limiter; and :mod:`domain.services.outbox_retry_policy`: decision here,
persistence in the store). No ``os``, no clock, no I/O — ``domain/`` purity is
AST-sealed by ``TestDomainPurity``.

Why the readiness verdict is cached (``READINESS_CACHE_TTL_SECONDS``)
---------------------------------------------------------------------
A readiness probe is polled by every orchestrator, every load balancer and every
uptime checker that can reach the port, and it is auth-exempt. Hitting the
central DB once per request would make the *health check itself* a load source
on the dependency it is trying to protect — and, because it is unauthenticated,
a free amplification primitive (one cheap HTTP request → one DB connection).
Caching the verdict for a short TTL bounds the dependency touch rate to
``1 / TTL`` per process **regardless of the inbound request rate**, while still
turning around fast enough that an orchestrator notices a real outage within one
or two poll intervals.

Why the response body is a fixed vocabulary
-------------------------------------------
An auth-exempt endpoint is an information-disclosure surface. The body is
restricted to a dependency *name* → one of two constant status tokens: never a
DSN, host, port, driver version, build id, or exception text (a psycopg
connection error message embeds the host and user). ``ReadinessSnapshot.as_dict``
is the only renderer, so there is one place where that could ever regress and
one place the seal tests have to watch.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


__all__ = [
    'DEPENDENCY_CENTRAL_DB',
    'LIVENESS_PATH_SUFFIX',
    'PROBE_PATH_SUFFIXES',
    'READINESS_CACHE_TTL_SECONDS',
    'READINESS_DEPENDENCIES_KEY',
    'READINESS_PATH_SUFFIX',
    'READINESS_UNAVAILABLE_DETAIL',
    'STATUS_KEY',
    'STATUS_OK',
    'STATUS_UNAVAILABLE',
    'ReadinessSnapshot',
    'is_probe_path',
    'liveness_payload',
    'normalize_probe_path',
]


#: Path suffix of the liveness probe. ``/{surface}/health`` is the shape the
#: Session surface already publishes, so Platform mirrors it rather than
#: inventing ``/healthz``: an operator who knows one surface knows all three.
LIVENESS_PATH_SUFFIX = '/health'

#: Path suffix of the readiness probe. A sibling of the liveness path rather
#: than a child (``/health/ready``) so a prefix-matching gateway rule written for
#: ``/health`` cannot silently swallow readiness too.
READINESS_PATH_SUFFIX = '/ready'

#: Every probe path suffix. Ordering is irrelevant — used as a membership test.
PROBE_PATH_SUFFIXES: tuple[str, ...] = (LIVENESS_PATH_SUFFIX, READINESS_PATH_SUFFIX)

#: The two status tokens a probe may ever emit. Constants (not inline literals)
#: so the wire vocabulary has one owner; ``'ok'`` matches the pre-existing
#: ``HealthCheckResponse.status`` default, keeping the Headless body identical.
STATUS_OK = 'ok'
STATUS_UNAVAILABLE = 'unavailable'

#: JSON member names of a probe body.
STATUS_KEY = 'status'
READINESS_DEPENDENCIES_KEY = 'dependencies'

#: Dependency identifier for the central PostgreSQL read/write model. A logical
#: name — never the DSN, host or database name (see module docstring).
DEPENDENCY_CENTRAL_DB = 'central_db'

#: How long a readiness verdict stays authoritative, in seconds. 5 s is below the
#: compose probe interval (15 s) so consecutive orchestrator polls are never
#: served the same cached verdict — the cache exists to absorb *bursts* (many
#: pollers, retries, an unauthenticated flood), not to slow the orchestrator's
#: own detection down.
READINESS_CACHE_TTL_SECONDS = 5.0

#: RFC 9457 ``detail`` for a not-ready response. Deliberately says nothing about
#: *which* dependency failed or why — that belongs in the process log, not in an
#: unauthenticated response body.
READINESS_UNAVAILABLE_DETAIL = 'Service dependencies are not ready.'


def normalize_probe_path(path: str) -> str:
    """Strip the query string and any trailing slash from ``path``.

    Mirror of ``RateLimitPolicy.rule_for``'s normalization so ``/platform/ready/``
    and ``/platform/ready?x=1`` cannot be used to route around a probe-path
    decision made on the bare suffix.
    """
    return str(path or '').split('?', 1)[0].rstrip('/')


def is_probe_path(path: str) -> bool:
    """True when ``path`` addresses a liveness or readiness probe.

    Suffix matching keeps this policy free of per-surface path literals — the
    same rule covers ``/session/health``, ``/headless/health``,
    ``/platform/health`` and ``/platform/ready``.
    """
    normalized = normalize_probe_path(path)
    return any(normalized.endswith(suffix) for suffix in PROBE_PATH_SUFFIXES)


def liveness_payload() -> dict:
    """The liveness body: a constant, dependency-free ``{'status': 'ok'}``.

    A function (not a module-level dict) so a caller mutating the returned dict
    cannot poison every later response.
    """
    return {STATUS_KEY: STATUS_OK}


@dataclass(frozen=True)
class ReadinessSnapshot:
    """A dated readiness verdict: per-dependency statuses + the time observed.

    Immutable and clock-free — ``checked_at`` is supplied by the caller, and
    :meth:`is_fresh` compares it against a caller-supplied ``now``, so the whole
    freshness rule is unit-testable without patching time.
    """

    dependencies: Mapping[str, str]
    checked_at: float

    def __post_init__(self) -> None:
        # A snapshot whose statuses are outside the vocabulary would render an
        # undocumented token onto an auth-exempt endpoint. Fail loud at
        # construction instead of leaking it.
        unknown = {
            value for value in self.dependencies.values()
            if value not in (STATUS_OK, STATUS_UNAVAILABLE)
        }
        if unknown:
            raise ValueError(
                f'dependency status must be one of {STATUS_OK!r}/{STATUS_UNAVAILABLE!r}; '
                f'got {sorted(unknown)!r}'
            )
        # Freeze the mapping so a caller holding the original dict cannot mutate
        # a cached snapshot after the fact.
        object.__setattr__(self, 'dependencies', dict(self.dependencies))

    @property
    def ready(self) -> bool:
        """True when every declared dependency is reachable.

        A snapshot with **no** declared dependencies is ready — that is the
        "nothing to check" case (an embedder that composed the surface without a
        dependency probe), not a silent pass over a failed check.
        """
        return all(value == STATUS_OK for value in self.dependencies.values())

    def is_fresh(self, *, now: float, ttl: float = READINESS_CACHE_TTL_SECONDS) -> bool:
        """True when this verdict may still be served without re-probing.

        A ``now`` earlier than ``checked_at`` (clock stepped backwards) is
        treated as stale rather than fresh-forever — the conservative direction.
        """
        elapsed = float(now) - float(self.checked_at)
        return 0.0 <= elapsed < float(ttl)

    def as_dict(self) -> dict:
        """Render the readiness body — the ONLY renderer (see module docstring)."""
        return {
            STATUS_KEY: STATUS_OK if self.ready else STATUS_UNAVAILABLE,
            READINESS_DEPENDENCIES_KEY: dict(self.dependencies),
        }
