"""Headless contract surface — measurement job submission and lifecycle.

Owns every declaration for /headless/jobs: the route, the permission,
the path parameters, the operation contract and the schemas only these
operations reach. One operation's contract is one place.

The boundary is measured, not chosen — see
``.claude/evaluations/headless-contract-axis.md``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fcc_test_contracts.headless.api_contract_operation_factory import _operation
from fcc_test_contracts.headless.api_contract_primitives import ApiContractError, _optional_text, require_object


#: Route prefixes this surface owns. Longest match wins, so a more
#: specific prefix in another surface would take precedence -- the
#: partition tests refuse that rather than letting it resolve.
SURFACE_PREFIXES = (
    '/headless/jobs',
)


ROUTES = {
    'list_measurement_jobs': ('GET', '/headless/jobs'),
    'get_measurement_job': ('GET', '/headless/jobs/{job_id}'),
    'submit_measurement_job': ('POST', '/headless/jobs'),
    'stop_measurement_job': ('POST', '/headless/jobs/{job_id}/stop'),
}


@dataclass(frozen=True)
class SubmitMeasurementJobRequest:
    excel_path: str
    requested_by: str = ''
    payload: Optional[dict] = None
    options: Optional[dict] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'SubmitMeasurementJobRequest':
        body = require_object(data, 'submit measurement job request')
        excel_path = _required_text(body, 'excel_path')
        return cls(
            excel_path=excel_path,
            requested_by=_optional_text(body.get('requested_by')),
            payload=_optional_dict(body.get('payload'), 'payload'),
            options=_optional_dict(body.get('options'), 'options'),
        )

    def to_dict(self) -> dict:
        return {
            'excel_path': self.excel_path,
            'requested_by': self.requested_by,
            'payload': self.payload,
            'options': self.options,
        }


@dataclass(frozen=True)
class StopMeasurementJobRequest:
    message: str = ''

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'StopMeasurementJobRequest':
        body = {} if data is None else require_object(data, 'stop measurement job request')
        return cls(message=_optional_text(body.get('message')))

    def to_dict(self) -> dict:
        return {'message': self.message}


@dataclass(frozen=True)
class MeasurementJobSubmitted:
    id: int
    status: str
    excel_path: str
    job_uuid: str = ''

    @classmethod
    def from_row(cls, row: dict) -> 'MeasurementJobSubmitted':
        return cls(
            id=int(row['id']),
            status=str(row.get('status') or ''),
            excel_path=str(row.get('excel_path') or ''),
            job_uuid=str(row.get('job_uuid') or ''),
        )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'status': self.status,
            'excel_path': self.excel_path,
            'job_uuid': self.job_uuid,
        }


@dataclass(frozen=True)
class StopMeasurementJobResponse:
    job_id: int
    stop_requested: bool = True

    def to_dict(self) -> dict:
        return {'job_id': self.job_id, 'stop_requested': self.stop_requested}


def _required_text(data: dict, key: str) -> str:
    value = _optional_text(data.get(key))
    if not value:
        raise ApiContractError(f"{key} is required")
    return value


def _optional_dict(value, key: str) -> Optional[dict]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ApiContractError(f"{key} must be an object")
    return value


PERMISSIONS = {
    'list_measurement_jobs': 'headless:read',
    'get_measurement_job': 'headless:read',
    'submit_measurement_job': 'headless:control',
    'stop_measurement_job': 'headless:control',
}


SCHEMAS = {
    'SubmitMeasurementJobRequest': {
        'type': 'object',
        'required': ['excel_path'],
        'properties': {
            'excel_path': {'type': 'string', 'minLength': 1},
            'requested_by': {'type': 'string', 'default': ''},
            'payload': {'type': 'object', 'nullable': True},
            'options': {'type': 'object', 'nullable': True},
        },
        'additionalProperties': False,
    },
    'StopMeasurementJobRequest': {
        'type': 'object',
        'required': [],
        'properties': {
            'message': {'type': 'string', 'default': ''},
        },
        'additionalProperties': False,
    },
    'MeasurementJobSubmitted': {
        'type': 'object',
        'required': ['id', 'status', 'excel_path', 'job_uuid'],
        'properties': {
            'id': {'type': 'integer'},
            'status': {'type': 'string'},
            'excel_path': {'type': 'string'},
            'job_uuid': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'MeasurementJobList': {
        'type': 'array',
        'items': {'$ref': '#/schemas/MeasurementJobSnapshot'},
    },
    'StopMeasurementJobResponse': {
        'type': 'object',
        'required': ['job_id', 'stop_requested'],
        'properties': {
            'job_id': {'type': 'integer'},
            'stop_requested': {'type': 'boolean'},
        },
        'additionalProperties': False,
    },
}


OPERATIONS = {
    'list_measurement_jobs': _operation(
        request=None,
        response='MeasurementJobList',
        permission=PERMISSIONS['list_measurement_jobs'],
        feature='measurement-jobs',
    ),
    'get_measurement_job': _operation(
        request=None,
        response='MeasurementJobSnapshot',
        permission=PERMISSIONS['get_measurement_job'],
        feature='measurement-jobs',
    ),
    'submit_measurement_job': _operation(
        request='SubmitMeasurementJobRequest',
        response='MeasurementJobSubmitted',
        permission=PERMISSIONS['submit_measurement_job'],
        feature='measurement-jobs',
    ),
    'stop_measurement_job': _operation(
        request='StopMeasurementJobRequest',
        response='StopMeasurementJobResponse',
        permission=PERMISSIONS['stop_measurement_job'],
        feature='measurement-jobs',
    ),
}
