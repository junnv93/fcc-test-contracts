"""Headless contract — surface registry and table merge.

The ``HEADLESS_API_*`` tables the facade exposes are the union of the same-named
tables declared by the surface modules. The merge **does not silently overwrite
a duplicate key**: two surfaces declaring the same operation id or schema name
fail loudly at import. A silent overwrite loses one contract entirely while
turning no gate red — the artifact still builds, the route still resolves, and
the only witness is a payload that stopped matching a screen nobody ran.

Why the surface modules are listed rather than discovered: the list is the
registry, and a ``surface_*.py`` that is never registered contributes nothing —
which the partition tests catch, because its operations then go missing from the
merged routes table and the totality check names them.
"""
from __future__ import annotations

from types import ModuleType

# Fully qualified on purpose. ``from application.headless import surface_jobs``
# names the PACKAGE, and this package's __init__ belongs to the provider lane —
# so that spelling makes the contracts lane import a module it does not own,
# which the extraction boundary counts as a crossing even though the module it
# actually reads is contracts-owned. The sibling central surface can use the
# short form because its whole directory is contracts-owned; this one cannot.
import fcc_test_contracts.headless.surface_jobs as surface_jobs
import fcc_test_contracts.headless.surface_meta as surface_meta
import fcc_test_contracts.headless.surface_provider as surface_provider
import fcc_test_contracts.headless.surface_reports as surface_reports
import fcc_test_contracts.headless.surface_sessions as surface_sessions
import fcc_test_contracts.headless.surface_test_plan as surface_test_plan
from fcc_test_contracts.headless.api_contract_features import (
    HEADLESS_FEATURES,
    validate_feature_membership,
)
from fcc_test_contracts.headless.api_contract_shared_schemas import SHARED_SCHEMAS


class DuplicateContractKeyError(KeyError):
    """Two surfaces declared the same key — the shape a merge loses one in."""


#: Declaration order is merge order and carries no meaning: generated artifacts
#: are dumped with ``sort_keys=True`` and the router resolves by name.
SURFACE_MODULES: tuple[ModuleType, ...] = (
    surface_meta,
    surface_provider,
    surface_jobs,
    surface_sessions,
    surface_reports,
    surface_test_plan,
)


def merge_surface_table(
    attribute: str,
    modules: tuple[ModuleType, ...] = SURFACE_MODULES,
    extra: dict | None = None,
) -> dict:
    """Union the ``attribute`` table across surfaces; overlapping keys raise.

    ``extra`` carries entries that belong to no single surface — schemas that
    two surfaces both reach. Ownership of those is derived, not chosen: see
    ``api_contract_shared_schemas``.
    """
    merged: dict = {}
    owner: dict = {}
    sources: list[tuple[str, dict]] = [
        (module.__name__, getattr(module, attribute, None) or {})
        for module in modules
    ]
    if extra:
        sources.append((f'{__name__}.extra', extra))
    for name, table in sources:
        for key, value in table.items():
            if key in merged:
                raise DuplicateContractKeyError(
                    f'{attribute}[{key!r}] declared by both {owner[key]} and {name}'
                )
            merged[key] = value
            owner[key] = name
    return merged


def surface_prefixes() -> dict[str, tuple[str, ...]]:
    """Module leaf name -> the route prefixes that module owns."""
    return {
        module.__name__.rsplit('.', 1)[-1]: module.SURFACE_PREFIXES
        for module in SURFACE_MODULES
    }


HEADLESS_API_ROUTES = merge_surface_table('ROUTES')
HEADLESS_API_PERMISSIONS = merge_surface_table('PERMISSIONS')
HEADLESS_API_OPERATIONS = merge_surface_table('OPERATIONS')
HEADLESS_API_SCHEMAS = merge_surface_table('SCHEMAS', extra=SHARED_SCHEMAS)

#: Feature properties, keyed by the ids the operations above claim. Exposed from
#: here (rather than only from ``api_contract_features``) so that a caller
#: holding the merged operation table holds the vocabulary that explains it.
HEADLESS_API_FEATURES = dict(HEADLESS_FEATURES)

# ⚠️ Import time, not test time — same reason ``DuplicateContractKeyError`` is
# raised at import. An operation whose feature is missing or misspelled still
# builds an artifact and still resolves a route; the only witness would be a
# provider judged against a feature nobody declared.
validate_feature_membership(HEADLESS_API_OPERATIONS)
