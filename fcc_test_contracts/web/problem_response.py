"""RFC 9457 ``application/problem+json`` rendering for the web surfaces — B1.

The route boundaries (headless / platform) raise ``HTTPException`` whose
``detail`` is a :class:`ProblemDetails` dict. FastAPI's default ``HTTPException``
handler would wrap that as ``{"detail": {...}}`` (nested, non-RFC). This module
installs an exception handler that, for a problem-shaped ``detail``, renders the
dict at the JSON top level with the ``application/problem+json`` media type —
and otherwise delegates to the legacy ``{"detail": ...}`` shape so any
non-problem ``HTTPException`` is unaffected.

**This module imports no web framework.** The exception class it registers for
and the response constructor it renders with are *parameters*, supplied by the
three ``create_*_app`` factories — the composition edge that already resolves
FastAPI inside a guarded ``try``. That is what lets the dependency-free
contracts lane own it (2026-08-15, platform-provider-crossing-closure): all
three surfaces read this file, so provider ownership forced the platform route
boundary to import across the lane boundary, and platform ownership would only
have reversed that crossing. Declaring ``fastapi`` an optional extra of the
contracts lane was measured and rejected — it turns three cross-lane imports
into three staged import violations on a lane whose baseline is 0, which is the
same coupling moved to a different counter.

The framework still arrives no earlier than it used to: the callers resolve it
at app-construction time inside the same ``try``/``except ImportError`` that
already raises ``RuntimeError('FastAPI is required …')``, so importing this
module — or any module that imports it — still needs no web dependency.
"""
from __future__ import annotations

from collections.abc import Mapping

from fcc_test_contracts.common.api_error_codes import PROBLEM_JSON_MEDIA_TYPE


def _is_problem_detail(detail: object) -> bool:
    """True when ``detail`` is a ProblemDetails-shaped mapping.

    A problem body always carries both the RFC 9457 ``type`` standard member and
    the ``code`` extension; a legacy string detail (or any other HTTPException)
    has neither, so it falls through to the default rendering.
    """
    return isinstance(detail, Mapping) and 'code' in detail and 'type' in detail


def install_problem_details_handler(app, *, http_exception, json_response) -> None:
    """Register the problem+json ``HTTPException`` handler on a FastAPI ``app``.

    ``http_exception`` is the framework's HTTP exception class (the handler is
    registered for it) and ``json_response`` its JSON response constructor.
    Both are required keyword arguments rather than imports: see the module
    docstring. A default that lazily imported FastAPI would put the dependency
    back in this file with an extra indirection.

    Idempotent per app (FastAPI keeps the last handler registered for a class).
    """

    async def _problem_details_exception_handler(_request, exc):
        detail = exc.detail
        headers = getattr(exc, 'headers', None)
        if _is_problem_detail(detail):
            return json_response(
                status_code=exc.status_code,
                content=dict(detail),
                media_type=PROBLEM_JSON_MEDIA_TYPE,
                headers=headers,
            )
        # Non-problem HTTPException — preserve the historical {"detail": ...} body.
        return json_response(
            status_code=exc.status_code,
            content={'detail': detail},
            headers=headers,
        )

    app.add_exception_handler(http_exception, _problem_details_exception_handler)
