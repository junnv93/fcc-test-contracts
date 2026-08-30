"""Neutral authenticated internal RBAC HTTP route contract.

The gateway-backed headless resolver and the platform API composition both need
the method/path for the internal effective-permissions boundary.  This contract
lives in the approved shared contracts lane so neither surface imports the
other surface's application package, and the route literal has one owner.
"""
from __future__ import annotations

from typing import Final


__all__ = ['INTERNAL_RBAC_ROUTES']


INTERNAL_RBAC_ROUTES: Final[dict[str, tuple[str, str]]] = {
    'effective_project_permissions': (
        'GET', '/platform/internal/projects/{project_id}/effective-permissions',
    ),
}
