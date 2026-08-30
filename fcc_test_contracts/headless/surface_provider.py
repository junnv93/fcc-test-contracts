"""Headless contract surface — provider capabilities and the UI descriptor.

Owns every declaration for /headless/capabilities / /headless/ui-descriptor: the route, the permission,
the path parameters, the operation contract and the schemas only these
operations reach. One operation's contract is one place.

The boundary is measured, not chosen — see
``.claude/evaluations/headless-contract-axis.md``.
"""
from __future__ import annotations

from fcc_test_contracts.common.provider_ui_descriptor_schema import PROVIDER_UI_DESCRIPTOR_SCHEMAS
from dataclasses import dataclass
from typing import Optional

from fcc_test_contracts.headless.api_contract_constants import DEFAULT_PROVIDER_METADATA
from fcc_test_contracts.headless.api_contract_operation_factory import _operation


#: Route prefixes this surface owns. Longest match wins, so a more
#: specific prefix in another surface would take precedence -- the
#: partition tests refuse that rather than letting it resolve.
SURFACE_PREFIXES = (
    '/headless/capabilities',
    '/headless/ui-descriptor',
)


ROUTES = {
    'provider_capabilities': ('GET', '/headless/capabilities'),
    'provider_ui_descriptor': ('GET', '/headless/ui-descriptor'),
}


@dataclass(frozen=True)
class ProviderCapabilitiesResponse:
    provider_id: str
    product_line: str
    supported_job_types: tuple[str, ...] = ('measurement', 'report_generation')
    supported_technologies: tuple[str, ...] = ('BT', 'BLE', 'DTS', 'UNII')
    supported_artifact_types: tuple[str, ...] = ('plot_png', 'screenshot_png', 'trace_csv')
    supports_cancel: bool = True
    supports_offline_queue: bool = True
    runtime_limits: Optional[dict] = None

    @classmethod
    def default(cls, provider: Optional[dict] = None) -> 'ProviderCapabilitiesResponse':
        metadata = provider or DEFAULT_PROVIDER_METADATA
        return cls(
            provider_id=str(metadata.get('provider_id') or ''),
            product_line=str(metadata.get('product_line') or ''),
        )

    def to_dict(self) -> dict:
        return {
            'provider_id': self.provider_id,
            'product_line': self.product_line,
            'supported_job_types': list(self.supported_job_types),
            'supported_technologies': list(self.supported_technologies),
            'supported_artifact_types': list(self.supported_artifact_types),
            'supports_cancel': self.supports_cancel,
            'supports_offline_queue': self.supports_offline_queue,
            'runtime_limits': dict(self.runtime_limits or {}),
        }


PERMISSIONS = {
    'provider_capabilities': 'headless:read',
    'provider_ui_descriptor': 'headless:read',  # WEB-PROVIDER-UI-0 (read)
}


SCHEMAS = {
    'ProviderCapabilitiesResponse': {
        'type': 'object',
        'required': [
            'provider_id',
            'product_line',
            'supported_job_types',
            'supported_technologies',
            'supported_artifact_types',
            'supports_cancel',
            'supports_offline_queue',
        ],
        'properties': {
            'provider_id': {'type': 'string'},
            'product_line': {'type': 'string'},
            'supported_job_types': {
                'type': 'array',
                'items': {'type': 'string'},
            },
            'supported_technologies': {
                'type': 'array',
                'items': {'type': 'string'},
            },
            'supported_artifact_types': {
                'type': 'array',
                'items': {'type': 'string'},
            },
            'supports_cancel': {'type': 'boolean'},
            'supports_offline_queue': {'type': 'boolean'},
            'runtime_limits': {'type': 'object'},
        },
        'additionalProperties': False,
    },
    **PROVIDER_UI_DESCRIPTOR_SCHEMAS,  # WEB-PROVIDER-UI-0 shared descriptor schemas
}


OPERATIONS = {
    'provider_capabilities': _operation(
        request=None,
        response='ProviderCapabilitiesResponse',
        permission=PERMISSIONS['provider_capabilities'],
    ),
    'provider_ui_descriptor': _operation(
        request=None,
        response='ProviderUiDescriptor',
        permission=PERMISSIONS['provider_ui_descriptor'],
    ),
}
