"""Headless contract surface — per-session results, artifacts and attempt history.

Owns every declaration for /headless/sessions: the route, the permission,
the path parameters, the operation contract and the schemas only these
operations reach. One operation's contract is one place.

The boundary is measured, not chosen — see
``.claude/evaluations/headless-contract-axis.md``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fcc_test_contracts.headless.api_contract_constants import (DEFAULT_ATTEMPTS_PAGE_LIMIT, MAX_ATTEMPTS_PAGE_LIMIT, XLSX_MEDIA_TYPE)
from fcc_test_contracts.headless.api_contract_operation_factory import _operation
from fcc_test_contracts.headless.api_contract_primitives import ApiContractError, _optional_text, require_object


#: Route prefixes this surface owns. Longest match wins, so a more
#: specific prefix in another surface would take precedence -- the
#: partition tests refuse that rather than letting it resolve.
SURFACE_PREFIXES = (
    '/headless/sessions',
)


ROUTES = {
    'list_session_results': ('GET', '/headless/sessions/{session_id}/results'),
    'list_session_artifacts': ('GET', '/headless/sessions/{session_id}/artifacts'),
    'list_session_attempts': ('GET', '/headless/sessions/{session_id}/attempts'),
    # Measurement-result workbook export (2026-08-11). GET (idempotent render of
    # existing rows) on an ``export`` action segment under the results resource —
    # sibling of the draft export's shape. No new path params.
    'export_session_results': (
        'GET', '/headless/sessions/{session_id}/results/export',
    ),
    'submit_report_request': ('POST', '/headless/sessions/{session_id}/reports'),
}


#: ``MeasurementAttemptEnvelope.result`` payload properties.
#:
#: The authoritative producer is ``session_service._attempt_envelope``'s
#: ``result`` dict; every key below mirrors one of its ``Col.*``-sourced entries.
#: It is spelled out here rather than *derived* from that function because
#: ``session_service`` imports ``api_contracts``, which re-exports this module —
#: importing back would close a cycle, and this module is contractually
#: dependency-free besides the provider-descriptor schema.
#:
#: The duplication is therefore deliberate, and it is **sealed rather than
#: trusted**: ``tests/test_api_contract_artifact_phase25.py::
#: TestMeasurementAttemptResultSchemaMatchesProducer`` calls the real producer
#: and asserts its key set equals this mapping's, so adding a result column
#: without describing it here is a red test rather than a silently stale
#: contract.
#:
#: Every value is a string — the producer runs each column through ``_text``.
#: The three ``*_unit`` members are the measurement-unit metadata (dBm / kHz /
#: msec …). They were already on the wire but absent from this schema, so the
#: generated TypeScript typed ``result`` as an empty object and the operator saw
#: a bare ``"22.0"`` with no way to tell dBm from kHz from msec.
MEASUREMENT_ATTEMPT_RESULT_PROPERTIES: dict = {
    'result1': {'type': 'string'},
    'result2': {'type': 'string'},
    'result_sum': {'type': 'string'},
    'result1_unit': {'type': 'string'},
    'result2_unit': {'type': 'string'},
    'result_sum_unit': {'type': 'string'},
    'margin': {'type': 'string'},
    'dccf': {'type': 'string'},
}


@dataclass(frozen=True)
class SubmitReportRequest:
    """A report submission as it crosses the *shared* provider boundary.

    ⚠️ ``template_profile`` is DELIBERATELY unset by default -- ``''`` means
    *"the caller did not choose"*. It used to default to ``'fcc-default'``: a
    provider literal in the lane every provider shares, whose failure was
    silent (an omitted field rendered **FCC's template** for a KC or mmWave
    report, with nothing reporting a fault). Its siblings ``provider_id`` /
    ``output_dir`` / ``generated_by`` all default to ``''``; this one was the
    exception, and the exception was the defect. Resolving an unset profile
    belongs to the provider that owns the templates -- the ``SessionOrigin``
    discipline, where the value is declared by the side that knows it.
    """

    provider_id: str = ''
    report_types: Optional[list[str]] = None
    output_formats: Optional[list[str]] = None
    output_dir: str = ''
    template_profile: str = ''
    artifact_roots: Optional[list[str]] = None
    generated_by: str = ''
    idempotency_key: str = ''

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'SubmitReportRequest':
        body = {} if data is None else require_object(data, 'submit report request')
        return cls(
            provider_id=_optional_text(body.get('provider_id')),
            report_types=_optional_text_list(body.get('report_types'), 'report_types'),
            output_formats=_optional_text_list(body.get('output_formats'), 'output_formats'),
            output_dir=_optional_text(body.get('output_dir')),
            template_profile=_optional_text(body.get('template_profile')),
            artifact_roots=_optional_text_list(body.get('artifact_roots'), 'artifact_roots'),
            generated_by=_optional_text(body.get('generated_by')),
            idempotency_key=_optional_text(body.get('idempotency_key')),
        )

    def to_dict(self) -> dict:
        return {
            'provider_id': self.provider_id,
            'report_types': self.report_types,
            'output_formats': self.output_formats,
            'output_dir': self.output_dir,
            'template_profile': self.template_profile,
            'artifact_roots': self.artifact_roots,
            'generated_by': self.generated_by,
            'idempotency_key': self.idempotency_key,
        }


@dataclass(frozen=True)
class ReportRequestSubmitted:
    request_id: int
    session_id: int
    status: str = 'queued'

    def to_dict(self) -> dict:
        return {
            'request_id': self.request_id,
            'session_id': self.session_id,
            'status': self.status,
        }


def _optional_text_list(value, key: str) -> Optional[list[str]]:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ApiContractError(f"{key} must be an array")
    return [_optional_text(item) for item in value if _optional_text(item)]


PERMISSIONS = {
    'list_session_results': 'headless:read',
    'list_session_artifacts': 'headless:read',
    'list_session_attempts': 'headless:read',
    # Measurement-result workbook export (2026-08-11). Rendering the session's
    # rows into the workbook format we own is a non-mutating read of results the
    # caller can already list one by one, so it reuses the existing read token
    # (NO new grantable permission — RBAC bijection unchanged).
    'export_session_results': 'headless:read',
    'submit_report_request': 'report_automation:control',
}


SCHEMAS = {
    'MeasurementResultEnvelopeList': {
        'type': 'array',
        'items': {'$ref': '#/schemas/MeasurementResultEnvelope'},
    },
    'MeasurementResultEnvelope': {
        'type': 'object',
        'required': ['provider_id', 'session_id', 'result_id'],
        'properties': {
            'provider_id': {'type': 'string'},
            'session_id': {'type': 'string'},
            'result_id': {'type': 'string'},
            'test_name': {'type': 'string'},
            'technology': {'type': 'string'},
            'condition': {'type': 'object'},
            'result': {'type': 'object'},
            'verdict': {'type': 'string'},
            'measured_at': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'MeasurementAttemptPage': {
        'type': 'object',
        'required': ['items', 'next_cursor'],
        'properties': {
            'items': {
                'type': 'array',
                'items': {'$ref': '#/schemas/MeasurementAttemptEnvelope'},
            },
            # Opaque keyset cursor. Non-null → more pages exist (echo it back as
            # the ``cursor`` query param); null → last page. FE-P4-PAGE.
            'next_cursor': {'type': 'string', 'nullable': True},
        },
        'additionalProperties': False,
    },
    'MeasurementAttemptEnvelope': {
        'type': 'object',
        'required': ['provider_id', 'session_id', 'attempt_id', 'condition_hash'],
        'properties': {
            'provider_id': {'type': 'string'},
            'session_id': {'type': 'string'},
            'attempt_id': {'type': 'string'},
            'condition_hash': {'type': 'string'},
            'sheet_name': {'type': 'string'},
            'row_order': {'type': 'integer', 'nullable': True},
            'technology': {'type': 'string'},
            'attempt_number': {'type': 'integer', 'nullable': True},
            'result': {
                'type': 'object',
                'properties': MEASUREMENT_ATTEMPT_RESULT_PROPERTIES,
                'additionalProperties': False,
            },
            'verdict': {'type': 'string'},
            'status': {'type': 'string'},
            'recorded_by': {'type': 'string'},
            'measured_at': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'ArtifactMetadataList': {
        'type': 'array',
        'items': {'$ref': '#/schemas/ArtifactMetadata'},
    },
    'ArtifactMetadata': {
        'type': 'object',
        'required': [
            'provider_id',
            'session_id',
            'artifact_type',
            'relative_path',
            'storage_backend',
        ],
        'properties': {
            'provider_id': {'type': 'string'},
            'session_id': {'type': 'string'},
            'result_id': {'type': 'string'},
            'artifact_type': {'type': 'string'},
            'relative_path': {'type': 'string'},
            'original_filename': {'type': 'string'},
            'sha256': {'type': 'string'},
            'byte_size': {'type': 'integer', 'nullable': True},
            'storage_backend': {'type': 'string'},
            'created_at': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'SubmitReportRequest': {
        'type': 'object',
        'required': [],
        'properties': {
            'provider_id': {'type': 'string'},
            'report_types': {
                'type': 'array',
                'items': {'type': 'string'},
                'nullable': True,
            },
            'output_formats': {
                'type': 'array',
                'items': {'type': 'string'},
                'nullable': True,
            },
            'output_dir': {'type': 'string'},
            'template_profile': {'type': 'string'},
            'artifact_roots': {
                'type': 'array',
                'items': {'type': 'string'},
                'nullable': True,
            },
            'generated_by': {'type': 'string', 'default': ''},
            'idempotency_key': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'ReportRequestSubmitted': {
        'type': 'object',
        'required': ['request_id', 'session_id', 'status'],
        'properties': {
            'request_id': {'type': 'integer'},
            'session_id': {'type': 'integer'},
            'status': {'type': 'string'},
        },
        'additionalProperties': False,
    },
}


OPERATIONS = {
    'list_session_results': _operation(
        request=None,
        response='MeasurementResultEnvelopeList',
        permission=PERMISSIONS['list_session_results'],
        feature='session-results',
    ),
    'list_session_artifacts': _operation(
        request=None,
        response='ArtifactMetadataList',
        permission=PERMISSIONS['list_session_artifacts'],
        feature='session-results',
    ),
    # Measurement-result workbook export (2026-08-11). The workbook format is ours
    # (``measurement_result_template.v1.json``), so this is a render of rows the
    # caller can already read one by one — hence the existing read token and a GET.
    # 404 = unknown session (the generic headless not-found row); 422 = the session
    # exists but measured nothing, which is a DIFFERENT fact from an empty draft.
    'export_session_results': _operation(
        request=None,
        response='',
        permission=PERMISSIONS['export_session_results'],
        feature='session-results',
        binary_response=True,
        binary_media_type=XLSX_MEDIA_TYPE,
        error_responses={
            '422': (
                'The session has no measurement rows — there is nothing to render '
                'into a result workbook (SESSION_RESULTS_EMPTY).'
            ),
        },
    ),
    'list_session_attempts': _operation(
        request=None,
        response='MeasurementAttemptPage',
        permission=PERMISSIONS['list_session_attempts'],
        feature='session-results',
        query_params=[
            {
                'name': 'cursor',
                'description': (
                    'Opaque keyset cursor from a prior response\'s '
                    '``next_cursor``. Omit for the first page.'
                ),
                'schema': {'type': 'string'},
            },
            {
                'name': 'limit',
                'description': 'Maximum attempts per page (clamped to the server max).',
                'schema': {
                    'type': 'integer',
                    'minimum': 1,
                    'maximum': MAX_ATTEMPTS_PAGE_LIMIT,
                    'default': DEFAULT_ATTEMPTS_PAGE_LIMIT,
                },
            },
            {
                'name': 'row_order',
                'description': 'Drill down to a single test-plan condition.',
                'schema': {'type': 'integer', 'minimum': 0},
            },
        ],
    ),
    'submit_report_request': _operation(
        request='SubmitReportRequest',
        response='ReportRequestSubmitted',
        permission=PERMISSIONS['submit_report_request'],
        feature='report-automation',
    ),
}
