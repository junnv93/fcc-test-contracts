"""Headless contract surface — api contract snapshot."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from fcc_test_contracts.headless.api_contract_constants import (API_COMPATIBILITY_MAJOR, API_CONTRACT_VERSION, DEFAULT_PROVIDER_METADATA)
from fcc_test_contracts.headless.api_contract_surfaces import (HEADLESS_API_OPERATIONS, HEADLESS_API_ROUTES, HEADLESS_API_SCHEMAS)


@dataclass(frozen=True)
class ApiContractSnapshot:
    version: str = API_CONTRACT_VERSION
    compatibility_major: int = API_COMPATIBILITY_MAJOR
    provider: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_PROVIDER_METADATA)
    )
    routes: dict[str, tuple[str, str]] = field(default_factory=lambda: dict(HEADLESS_API_ROUTES))
    operations: dict[str, dict] = field(
        default_factory=lambda: _copy_contract_dict(HEADLESS_API_OPERATIONS)
    )
    schemas: dict[str, dict] = field(
        default_factory=lambda: _copy_contract_dict(HEADLESS_API_SCHEMAS)
    )

    def to_dict(self) -> dict:
        return {
            'version': self.version,
            'compatibility_major': self.compatibility_major,
            'provider': self.provider,
            'routes': {
                name: {'method': method, 'path': path}
                for name, (method, path) in self.routes.items()
            },
            'operations': self.operations,
            'schemas': self.schemas,
        }


def _copy_contract_dict(value: dict) -> dict:
    copied = {}
    for key, item in value.items():
        if isinstance(item, dict):
            copied[key] = _copy_contract_dict(item)
        elif isinstance(item, list):
            copied[key] = list(item)
        else:
            copied[key] = item
    return copied
