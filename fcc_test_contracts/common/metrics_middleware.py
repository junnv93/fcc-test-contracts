"""OBS-2 phase 3 follow-up (2026-05-23) — shared ASGI metrics middleware factory.

Session/Headless 양 router 가 동일 ~30 line ``_metrics_middleware`` body
(perf_counter_ns 측정 + path → operation lookup + status_token 매핑 +
``record_request`` 호출) 를 인라인으로 보유하던 중복 SSOT 위반 정공법 해소.

Design contract
---------------
- **stdlib only** — ``time.perf_counter_ns`` + ``typing`` 만 사용.
  ``application.common.metrics_registry`` 위임 (status_token + namespace).
- **caller-injected lookup** — Session/Headless 가 자기 route 매핑
  (각 ``build_route_pattern_index(SESSION_API_ROUTES)`` /
  ``build_route_pattern_index(HEADLESS_API_ROUTES)``) 으로 closure 한
  ``Callable[[str], Optional[str]]`` 을 주입. Generic middleware 본문은
  route 의 출처를 모름 — only "path → operation" contract.
- **None registry / None operation = no-op** — production composition root
  가 registry 주입, closed-network / 단위 테스트 는 ``registry=None``.
  ``lookup_operation`` 가 ``None`` 반환 시 self-referential signal (예:
  ``/headless/metrics`` 자체) skip.
- **never raise** — record_request 실패는 미들웨어 swallow (best-effort,
  ``pragma: no cover`` 보호). HTTP request 가 metric 결함으로 실패 X.
- **FastAPI app.middleware('http') 호환** — return value 는
  ``async (request, call_next) -> response`` 시그니처 — ``@app.middleware('http')``
  데코레이터 또는 ``app.middleware('http')(mw)`` 직접 등록 모두 지원.
- **dependency-free purity** — ``TestApplicationCommonPurity`` 봉인.
  infrastructure/FastAPI/Starlette/PySide6 import 0.
"""
from __future__ import annotations

import time
from typing import Awaitable, Callable, Optional

from fcc_test_contracts.common.metrics_registry import (
    ApiMetricsRegistry,
    status_token_from_http_code,
)


__all__ = ['MetricsMiddleware', 'create_metrics_middleware']


# Type aliases for the ASGI middleware contract.
LookupOperation = Callable[[str], Optional[str]]
# ``request`` and ``response`` are intentionally typed as ``object`` so this
# module does not import FastAPI/Starlette types — ``TestLayerPurity`` keeps
# application/common dependency-free. The duck-typed protocol is:
# - ``request.url.path`` (str)
# - ``response.status_code`` (int)
# - ``call_next(request) -> Awaitable[response]``
MetricsMiddleware = Callable[[object, Callable[[object], Awaitable[object]]], Awaitable[object]]


def create_metrics_middleware(
    *,
    registry: Optional[ApiMetricsRegistry],
    lookup_operation: LookupOperation,
) -> MetricsMiddleware:
    """Build an ASGI middleware callable that records request latency.

    Args:
        registry: Shared :class:`ApiMetricsRegistry` instance, or ``None`` to
            skip observation (closed-network deployment / unit tests). When
            ``None``, the middleware degrades to a pass-through —
            ``perf_counter_ns`` calls are skipped entirely after the registry
            check to keep the no-op fast path at zero overhead.
        lookup_operation: Closure ``(request_path) -> operation_name | None``.
            Caller builds it from its route SSOT via
            :func:`build_route_pattern_index`. ``None`` return value
            deliberately skips observation (e.g. ``/headless/metrics`` is not
            in the route map → self-referential signal excluded).

    Returns:
        Async middleware function compatible with FastAPI
        ``@app.middleware('http')`` registration.
    """
    async def middleware(request, call_next):  # type: ignore[no-untyped-def]
        # Fast path — when no registry is wired, the middleware is a pure
        # pass-through (no perf_counter cost). Path lookup is the
        # second-cheapest skip (closure call, no regex iteration triggered
        # until operation is needed).
        if registry is None:
            return await call_next(request)

        start_ns = time.perf_counter_ns()
        response = await call_next(request)
        operation = lookup_operation(request.url.path)
        if operation is None:
            # Not in the route SSOT — self-referential signals (e.g. the
            # ``/metrics`` endpoint itself) or unknown paths fall here.
            return response

        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        status_token = status_token_from_http_code(response.status_code)
        try:
            registry.record_request(operation, status_token, elapsed_ms)
        except Exception:  # pragma: no cover — never fail a request on metric
            pass
        return response

    return middleware
