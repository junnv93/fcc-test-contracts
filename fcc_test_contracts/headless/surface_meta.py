"""Headless contract surface — health, backend status and the self-describing contract document.

Owns every declaration for /health / /headless/status / /headless/api-contract: the route, the permission,
the path parameters, the operation contract and the schemas only these
operations reach. One operation's contract is one place.

The boundary is measured, not chosen — see
``.claude/evaluations/headless-contract-axis.md``.
"""
from __future__ import annotations

from dataclasses import dataclass

from fcc_test_contracts.headless.api_contract_operation_factory import _operation


#: Route prefixes this surface owns. Longest match wins, so a more
#: specific prefix in another surface would take precedence -- the
#: partition tests refuse that rather than letting it resolve.
SURFACE_PREFIXES = (
    '/health',
    '/headless/status',
    '/headless/api-contract',
)


ROUTES = {
    'health_check': ('GET', '/health'),
    'headless_status': ('GET', '/headless/status'),
    'headless_api_contract': ('GET', '/headless/api-contract'),
}


@dataclass(frozen=True)
class HealthCheckResponse:
    status: str = 'ok'

    def to_dict(self) -> dict:
        return {'status': self.status}


PERMISSIONS = {
    'health_check': 'public',
    'headless_api_contract': 'public',
    'headless_status': 'headless:read',
}


SCHEMAS = {
    'HealthCheckResponse': {
        'type': 'object',
        'required': ['status'],
        'properties': {
            'status': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'HeadlessBackendStatusSnapshot': {
        'type': 'object',
        # ⚠️ ``report_automation`` is OPTIONAL (2026-09-05). This operation is
        # core — every provider must answer it, because without it central
        # cannot ask what the backend is doing — but the report-automation
        # queue is a feature a provider may not have at all.
        #
        # While the field was required, a provider without that queue had to
        # send one anyway, and KC sent five zeros. Those zeros then meant two
        # different things — "the queue is empty" and "there is no such queue" —
        # with nothing on the wire to tell them apart. That is the defect class
        # this repository has named repeatedly: absence and a legitimate value
        # sharing one representation.
        #
        # Optional restores the distinction: absent means no such queue, present
        # means a queue that currently holds these counts.
        'required': ['measurement_jobs', 'workers'],
        'properties': {
            'measurement_jobs': {'$ref': '#/schemas/MeasurementJobStatusSummary'},
            'workers': {
                'type': 'array',
                'items': {'$ref': '#/schemas/MeasurementWorkerSnapshot'},
            },
            'report_automation': {'$ref': '#/schemas/ReportAutomationQueueStats'},
        },
        'additionalProperties': False,
    },
    'MeasurementJobStatusSummary': {
        'type': 'object',
        'required': ['counts', 'recent'],
        'properties': {
            'counts': {
                'type': 'object',
                'required': ['queued', 'running', 'completed', 'failed', 'cancelled'],
                'properties': {
                    'queued': {'type': 'integer'},
                    'running': {'type': 'integer'},
                    'completed': {'type': 'integer'},
                    'failed': {'type': 'integer'},
                    'cancelled': {'type': 'integer'},
                },
                'additionalProperties': False,
            },
            'recent': {
                'type': 'array',
                'items': {'$ref': '#/schemas/MeasurementJobSnapshot'},
            },
        },
        'additionalProperties': False,
    },
    'MeasurementWorkerSnapshot': {
        'type': 'object',
        'required': ['worker_id', 'status'],
        'properties': {
            'worker_id': {'type': 'string'},
            'test_pc_id': {'type': 'string'},
            'hostname': {'type': 'string'},
            'status': {'type': 'string'},
            'capabilities_json': {'type': 'string', 'nullable': True},
            'last_heartbeat_at': {'type': 'string'},
            'created_at': {'type': 'string'},
            'updated_at': {'type': 'string'},
        },
        'additionalProperties': True,
    },
    'ApiContractDocument': {
        'type': 'object',
        'required': [
            'version',
            'compatibility_major',
            'provider',
            'routes',
            'operations',
            'schemas',
            'features',
        ],
        'properties': {
            'version': {'type': 'string'},
            'compatibility_major': {'type': 'integer'},
            'provider': {'$ref': '#/schemas/ApiProviderMetadata'},
            'routes': {'type': 'object'},
            'operations': {'type': 'object'},
            'schemas': {'type': 'object'},
            'features': {'type': 'object'},
        },
        'additionalProperties': False,
    },
    'ApiProviderMetadata': {
        'type': 'object',
        'required': ['provider_id', 'product_line', 'contract_family'],
        'properties': {
            'provider_id': {'type': 'string'},
            'product_line': {'type': 'string'},
            'contract_family': {'type': 'string'},
        },
        'additionalProperties': False,
    },
}


OPERATIONS = {
    'health_check': _operation(
        request=None,
        response='HealthCheckResponse',
        permission=PERMISSIONS['health_check'],
        feature='core',
    ),
    'headless_status': _operation(
        request=None,
        response='HeadlessBackendStatusSnapshot',
        permission=PERMISSIONS['headless_status'],
        feature='core',
    ),
    'headless_api_contract': _operation(
        request=None,
        response='ApiContractDocument',
        permission=PERMISSIONS['headless_api_contract'],
        feature='core',
    ),
}
