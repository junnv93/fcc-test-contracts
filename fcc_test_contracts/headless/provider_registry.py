"""The *shape* of a headless provider registry document.

⚠️ **Format lives here; content lives in the platform.** *"Which providers are
registered"* is an operating fact the platform owns. *"What a registry document
must look like, and whether it agrees with the contract artifact it names"* is a
contract question, and it belongs beside the artifacts and the compatibility
checker that answer it.

This module used to sit in ``fcc_test_platform``. The split then cut the check
in half: the script that runs it needs the contract artifacts and the batch
checker, and **both are contracts-owned**, so in the delivered platform box the
entry point died at its first import (measured 2026-08-31:
``ModuleNotFoundError: No module named 'contract_cli'``). ⚠️ The old module's
own docstring predicted exactly that -- *"this file spans two repositories"* --
and nothing ever turned the prediction red. **Prose warnings are not checks.**

It stays dependency-free, which is what let it move at all: ``fcc-test-contracts``
declares ``dependencies = []`` and this module keeps that true (stdlib only).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


__all__ = [
    'ProviderRegistry',
    'ProviderRegistryEntry',
    'ProviderRegistryError',
    'load_provider_registry',
    'validate_registry_contract_identities',
    'validate_registry_naming',
]


FORBIDDEN_REGISTRY_KEYS = frozenset({'routes', 'schemas', 'operations'})
REQUIRED_PROVIDER_KEYS = (
    'provider_id',
    'product_line',
    'contract_family',
    'contract_artifact',
)


class ProviderRegistryError(ValueError):
    """Raised when a provider registry document is invalid."""


@dataclass(frozen=True)
class ProviderRegistryEntry:
    provider_id: str
    product_line: str
    contract_family: str
    contract_artifact: str
    resolved_contract_artifact: Path

    def to_dict(self) -> dict:
        return {
            'provider_id': self.provider_id,
            'product_line': self.product_line,
            'contract_family': self.contract_family,
            'contract_artifact': self.contract_artifact,
            'resolved_contract_artifact': str(self.resolved_contract_artifact),
        }

    def validate_contract_identity(self) -> None:
        contract = json.loads(self.resolved_contract_artifact.read_text(encoding='utf-8'))
        if not isinstance(contract, dict):
            raise ProviderRegistryError(
                f'{self.provider_id} contract artifact must be a JSON object'
            )
        provider = contract.get('provider')
        if not isinstance(provider, dict):
            raise ProviderRegistryError(
                f'{self.provider_id} contract artifact is missing provider metadata'
            )
        _require_matching_provider_field(self, provider, 'provider_id')
        _require_matching_provider_field(self, provider, 'product_line')
        _require_matching_provider_field(self, provider, 'contract_family')


@dataclass(frozen=True)
class ProviderRegistry:
    registry_version: int
    providers: tuple[ProviderRegistryEntry, ...]

    @property
    def artifact_paths(self) -> list[str]:
        return [str(provider.resolved_contract_artifact) for provider in self.providers]

    def to_dict(self) -> dict:
        return {
            'registry_version': self.registry_version,
            'providers': [provider.to_dict() for provider in self.providers],
        }


def load_provider_registry(registry_path: Path, project_root: Path) -> ProviderRegistry:
    """Load and validate a provider registry JSON file."""
    registry_path = Path(registry_path)
    if not registry_path.is_absolute():
        registry_path = Path(project_root) / registry_path

    document = json.loads(registry_path.read_text(encoding='utf-8'))
    return _parse_registry(document, registry_path, Path(project_root))


def validate_registry_contract_identities(registry: ProviderRegistry) -> None:
    """Ensure registry identities match each referenced contract artifact."""
    for provider in registry.providers:
        provider.validate_contract_identity()


# -- naming axis --------------------------------------------------------------
#
# ⚠️ **Nothing enforced these names, and the three that exist already disagree.**
# Measured 2026-08-31: `fcc-unlicensed-conducted` has no `-headless`,
# `fcc-mmwave-headless` pairs with a single-token `mmwave`, and
# `fcc-licensed-headless` pairs with `licensed-conducted` whose first token is
# not `fcc`. Three entries, three different shapes -- because the only thing
# saying what the shape should be was habit.
#
# KC settled the rule (operator, 2026-08-31):
#
#     provider_id  = <scheme>-<test-kind>-headless
#     product_line = <scheme>-<test-kind>-<method>
#
# The first token is the **certification scheme** (`fcc`, `kc`, ...) and the two
# fields must agree on it. Lowercase kebab throughout: these strings must match
# the artifact byte-for-byte and are unique columns in the central database, so
# one capital letter is a mismatch nobody sees until an insert fails.
#
# ⚠️ **This is a ratchet, not a rewrite.** Renaming a live provider is not a
# naming change -- measurement rows hang off `provider_id`, so it is a data
# migration. The three below are recorded as predating the rule; the direction
# is for this set to SHRINK, never grow. A fourth provider does not get in here.
NAMING_GRANDFATHERED = frozenset({
    'fcc-unlicensed-conducted',
    'fcc-mmwave-headless',
    'fcc-licensed-headless',
})

_PROVIDER_ID_SHAPE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)+-headless$')
_PRODUCT_LINE_SHAPE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)+$')


def validate_registry_naming(registry: 'ProviderRegistry') -> None:
    """Refuse a NEW provider whose identity does not follow the settled shape.

    Grandfathered entries are skipped by name -- see ``NAMING_GRANDFATHERED``.
    """
    for entry in registry.providers:
        if entry.provider_id in NAMING_GRANDFATHERED:
            continue
        if not _PROVIDER_ID_SHAPE.match(entry.provider_id):
            raise ProviderRegistryError(
                f'{entry.provider_id!r} does not match '
                '<scheme>-<test-kind>-headless (lowercase kebab)'
            )
        if not _PRODUCT_LINE_SHAPE.match(entry.product_line):
            raise ProviderRegistryError(
                f'{entry.product_line!r} does not match '
                '<scheme>-<test-kind>-<method> (lowercase kebab)'
            )
        scheme = entry.provider_id.split('-', 1)[0]
        line_scheme = entry.product_line.split('-', 1)[0]
        if scheme != line_scheme:
            raise ProviderRegistryError(
                f'{entry.provider_id!r} and {entry.product_line!r} disagree on the '
                f'certification scheme ({scheme!r} vs {line_scheme!r})'
            )


def _parse_registry(
    document: object,
    registry_path: Path,
    project_root: Path,
) -> ProviderRegistry:
    if not isinstance(document, dict):
        raise ProviderRegistryError('provider registry must be a JSON object')

    _reject_forbidden_keys(document.keys(), 'registry')

    providers = document.get('providers')
    if not isinstance(providers, list) or not providers:
        raise ProviderRegistryError('provider registry is empty')

    entries = tuple(
        _parse_provider(provider, index, registry_path, project_root)
        for index, provider in enumerate(providers)
    )
    _reject_duplicates(entries)

    return ProviderRegistry(
        registry_version=int(document.get('registry_version', 1)),
        providers=entries,
    )


def _parse_provider(
    provider: object,
    index: int,
    registry_path: Path,
    project_root: Path,
) -> ProviderRegistryEntry:
    if not isinstance(provider, dict):
        raise ProviderRegistryError(f'providers[{index}] must be an object')

    _reject_forbidden_keys(provider.keys(), f'providers[{index}]')
    for key in REQUIRED_PROVIDER_KEYS:
        if not _text(provider.get(key)):
            raise ProviderRegistryError(f'providers[{index}].{key} is required')

    contract_artifact = _text(provider['contract_artifact'])
    resolved = _resolve_artifact_path(registry_path, project_root, contract_artifact)
    if not resolved.exists():
        raise ProviderRegistryError(
            f'providers[{index}].contract_artifact does not exist: {resolved}'
        )

    return ProviderRegistryEntry(
        provider_id=_text(provider['provider_id']),
        product_line=_text(provider['product_line']),
        contract_family=_text(provider['contract_family']),
        contract_artifact=contract_artifact,
        resolved_contract_artifact=resolved,
    )


def _reject_forbidden_keys(keys: Iterable[str], label: str) -> None:
    forbidden = sorted(FORBIDDEN_REGISTRY_KEYS.intersection(keys))
    if forbidden:
        raise ProviderRegistryError(
            f"{label} must not duplicate contract details: {', '.join(forbidden)}"
        )


def _reject_duplicates(entries: tuple[ProviderRegistryEntry, ...]) -> None:
    _reject_duplicate_value(entries, 'provider_id')
    _reject_duplicate_value(entries, 'product_line')


def _reject_duplicate_value(
    entries: tuple[ProviderRegistryEntry, ...],
    field_name: str,
) -> None:
    seen: set[str] = set()
    for entry in entries:
        value = getattr(entry, field_name)
        if value in seen:
            raise ProviderRegistryError(f'duplicate provider registry {field_name}: {value}')
        seen.add(value)


def _require_matching_provider_field(
    entry: ProviderRegistryEntry,
    provider: dict,
    field_name: str,
) -> None:
    expected = getattr(entry, field_name)
    actual = _text(provider.get(field_name))
    if actual != expected:
        raise ProviderRegistryError(
            f'{entry.provider_id}.{field_name} mismatch: '
            f'expected {expected!r}, got {actual!r}'
        )


def _resolve_artifact_path(
    registry_path: Path,
    project_root: Path,
    artifact: str,
) -> Path:
    path = Path(artifact)
    if path.is_absolute():
        return path
    candidate = project_root / path
    if candidate.exists():
        return candidate
    return registry_path.parent / path


def _text(value: object) -> str:
    if value is None:
        return ''
    return str(value).strip()
