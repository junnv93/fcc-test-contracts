"""Headless contract surface — report requests, outputs and the report-automation queue.

Owns every declaration for /headless/reports / /report-automation: the route, the permission,
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
    '/headless/reports',
    '/report-automation',
)


ROUTES = {
    # Pre-generation preflight (report-preflight-precheck B2, 2026-06-24). Static
    # ``preflight`` segment — distinct from the {request_id} dynamic route below.
    # session_id is a query param (the dry-run targets a measurement session, not
    # a persisted report-automation request). The integer path convertor on
    # {request_id} never matches the literal 'preflight', so route order is safe.
    'get_report_preflight': ('GET', '/headless/reports/preflight'),
    'get_report_request': ('GET', '/headless/reports/{request_id}'),
    'list_report_outputs': ('GET', '/headless/reports/{request_id}/outputs'),
    'create_report_output_download': (
        'POST',
        '/headless/reports/{request_id}/outputs/download',
    ),
    'stream_report_output_download': ('GET', '/headless/reports/outputs/download'),
    'report_automation_stats': ('GET', '/report-automation/stats'),
    'cancel_report_automation_request': (
        'POST',
        '/report-automation/requests/{request_id}/cancel',
    ),
}


@dataclass(frozen=True)
class CancelReportAutomationRequest:
    message: str = ''

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> 'CancelReportAutomationRequest':
        body = {} if data is None else require_object(data, 'cancel report automation request')
        return cls(message=_optional_text(body.get('message')))

    def to_dict(self) -> dict:
        return {'message': self.message}


@dataclass(frozen=True)
class ReportOutputMetadata:
    request_id: int
    file_name: str
    relative_path: str
    exists: bool
    byte_size: Optional[int]
    storage_backend: str = 'filesystem'

    @classmethod
    def from_dict(cls, data: dict) -> 'ReportOutputMetadata':
        body = require_object(data, 'report output metadata')
        return cls(
            request_id=int(body.get('request_id') or 0),
            file_name=_optional_text(body.get('file_name')),
            relative_path=_optional_text(body.get('relative_path')),
            exists=bool(body.get('exists')),
            byte_size=_optional_int(body.get('byte_size')),
            storage_backend=_optional_text(body.get('storage_backend')) or 'filesystem',
        )

    def to_dict(self) -> dict:
        return {
            'request_id': self.request_id,
            'file_name': self.file_name,
            'relative_path': self.relative_path,
            'exists': self.exists,
            'byte_size': self.byte_size,
            'storage_backend': self.storage_backend,
        }


@dataclass(frozen=True)
class CreateReportOutputDownloadRequest:
    relative_path: str
    disposition: str = 'attachment'

    @classmethod
    def from_dict(cls, data: dict) -> 'CreateReportOutputDownloadRequest':
        body = require_object(data, 'report output download request')
        relative_path = _optional_text(body.get('relative_path'))
        if not relative_path:
            raise ApiContractError('relative_path is required')
        disposition = _optional_text(body.get('disposition')) or 'attachment'
        if disposition not in ('attachment', 'inline'):
            raise ApiContractError('disposition must be attachment or inline')
        return cls(relative_path=relative_path, disposition=disposition)


@dataclass(frozen=True)
class ReportOutputDownloadGrant:
    download_url: str
    expires_at: str

    def to_dict(self) -> dict:
        return {'download_url': self.download_url, 'expires_at': self.expires_at}


@dataclass(frozen=True)
class CancelReportAutomationResponse:
    request_id: int
    cancelled: bool = True

    def to_dict(self) -> dict:
        return {'request_id': self.request_id, 'cancelled': self.cancelled}


def _optional_int(value) -> Optional[int]:
    if value is None:
        return None
    return int(value)


PERMISSIONS = {
    # Pre-generation preflight (report-preflight-precheck B2, 2026-06-24) — a
    # read-only dry-run of per-technology completeness + data-quality before docx
    # generation. Reuses the existing read token (no new grantable permission).
    'get_report_preflight': 'report_automation:read',
    'get_report_request': 'report_automation:read',
    'list_report_outputs': 'report_automation:read',
    'create_report_output_download': 'report_automation:read',
    # Token-authorized stream (browser navigation carries no RBAC header) — the
    # signed short-TTL token IS the authorization (presigned model). Issued only
    # to a report_automation:read principal at grant time.
    'stream_report_output_download': 'public',
    'report_automation_stats': 'report_automation:read',
    'cancel_report_automation_request': 'report_automation:control',
}


SCHEMAS = {
    'CancelReportAutomationRequest': {
        'type': 'object',
        'required': [],
        'properties': {
            'message': {'type': 'string', 'default': ''},
        },
        'additionalProperties': False,
    },
    # Pre-generation preflight (report-preflight-precheck B2, 2026-06-24). 1:1
    # with reporting.application.report_preflight_dto.report_preflight_summary_to_dict.
    'ReportPreflightSummary': {
        'type': 'object',
        'required': [
            'session_id', 'published_plan_id', 'per_tech', 'data_quality',
            'missing_sources', 'has_incomplete', 'has_data_quality_warnings',
            'has_missing_sources',
        ],
        'properties': {
            'session_id': {'type': 'integer'},
            # null when the session followed no published plan (completeness
            # denominator unknown — every per_tech.kind is 'unknown').
            'published_plan_id': {'type': 'string', 'nullable': True},
            'per_tech': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ReportPreflightPerTech'},
            },
            'data_quality': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ReportPreflightDataQuality'},
            },
            # T2 (missing-sources) — slots that will be empty because the
            # measurement source row is missing / fails the required verdict
            # (NOT "PNG file missing" — that needs network stat, out of scope).
            'missing_sources': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ReportPreflightMissingSource'},
            },
            'has_incomplete': {'type': 'boolean'},
            'has_data_quality_warnings': {'type': 'boolean'},
            'has_missing_sources': {'type': 'boolean'},
        },
        'additionalProperties': False,
    },
    'ReportPreflightMissingSource': {
        'type': 'object',
        'required': ['technology', 'section', 'table_name', 'channel', 'label', 'reason'],
        'properties': {
            'technology': {'type': 'string'},
            'section': {'type': 'string'},
            'table_name': {'type': 'string'},
            # null for table-scoped slots (not channel-specific).
            'channel': {'type': 'string', 'nullable': True},
            'label': {'type': 'string'},
            'reason': {
                'type': 'string',
                'enum': ['missing_row', 'blocked_verdict'],
            },
        },
        'additionalProperties': False,
    },
    'ReportPreflightPerTech': {
        'type': 'object',
        'required': [
            'technology', 'measured_count', 'planned_total', 'kind', 'complete',
        ],
        'properties': {
            'technology': {'type': 'string'},
            'measured_count': {'type': 'integer'},
            # null = total planned count unknown (no published plan) — never a
            # fabricated 0 (wireframe ④ "no fake metrics" principle).
            'planned_total': {'type': 'integer', 'nullable': True},
            'kind': {
                'type': 'string',
                'enum': ['complete', 'incomplete', 'unknown'],
            },
            'complete': {'type': 'boolean'},
        },
        'additionalProperties': False,
    },
    'ReportPreflightDataQuality': {
        'type': 'object',
        'required': ['code', 'message', 'row_order'],
        'properties': {
            'code': {'type': 'string'},
            'message': {'type': 'string'},
            'row_order': {'type': 'integer', 'nullable': True},
        },
        'additionalProperties': False,
    },
    # 1:1 with ``report_automation_store._request_to_dict`` — that builder's
    # output is literally the wire payload (no ``response_model``, no
    # validating middleware between it and FastAPI), so the member set here is
    # not documentation, it is the shape.
    #
    # The string members below are non-nullable **because the builder coerces**:
    # ``output_dir`` / ``generated_by`` / ``assigned_worker_id`` /
    # ``error_message`` are ``row.<col> or ''`` and the timestamps go through
    # ``_dt()``, which yields ``''`` for NULL — even though every one of those
    # columns is nullable in the schema and really does hold NULL (lease expiry
    # writes ``None`` back). Widening them to ``string | null`` on the strength
    # of the column alone would hand every consumer a branch that cannot fire.
    # The coercion is sealed behaviourally by
    # ``tests/test_headless_snapshot_contract_conformance.py``, which drives the
    # real store against real SQLite in both directions — a member declared
    # non-nullable may never arrive as None, and a member declared nullable must
    # actually be reachable as None.
    #
    # Note the deliberate disagreement with ``TestPlanGenerationJobResponse``,
    # whose ``error_message`` *is* ``['string', 'null']``: that sibling's
    # producer passes the column through instead of coercing it, and two
    # ``apps/web`` call sites already depend on the difference. Same concept,
    # two producers, two honest declarations.
    'ReportRequestSnapshot': {
        'type': 'object',
        'required': ['id', 'status'],
        'properties': {
            'id': {'type': 'integer'},
            'job_id': {'type': 'integer', 'nullable': True},
            'session_id': {'type': 'integer', 'nullable': True},
            'template_profile': {'type': 'string'},
            'techs_json': {'type': 'string', 'nullable': True},
            'output_dir': {'type': 'string'},
            'artifact_roots_json': {'type': 'string', 'nullable': True},
            'generated_by': {'type': 'string'},
            # P5-A2 dedup key, echoed back so a caller can confirm which
            # request its key resolved to. Emitted since the key landed;
            # declaring it is what stops the generated TypeScript degrading it
            # to ``unknown`` through the ``additionalProperties`` index.
            'idempotency_key': {'type': 'string'},
            'assigned_worker_id': {'type': 'string'},
            'status': {'type': 'string'},
            'report_run_id': {'type': 'integer', 'nullable': True},
            'generated_paths_json': {'type': 'string', 'nullable': True},
            'warnings_json': {'type': 'string', 'nullable': True},
            'error_message': {'type': 'string'},
            'claimed_at': {'type': 'string'},
            'lease_expires_at': {'type': 'string'},
            'created_at': {'type': 'string'},
            'updated_at': {'type': 'string'},
        },
        # Stays open: providers other than FCC serve this contract too, and
        # narrowing to ``False`` would be a breaking change for them. The three
        # members above were added because the FCC producer already emits them,
        # not because the door was closed.
        'additionalProperties': True,
    },
    'ReportOutputMetadataList': {
        'type': 'array',
        'items': {'$ref': '#/schemas/ReportOutputMetadata'},
    },
    'ReportOutputMetadata': {
        'type': 'object',
        # FE-P6-DL: raw absolute filesystem ``path`` removed — clients reference
        # outputs by ``relative_path`` and download only through the signed grant
        # flow (POST .../outputs/download → GET .../outputs/download?token=).
        'required': [
            'request_id',
            'file_name',
            'relative_path',
            'exists',
            'byte_size',
            'storage_backend',
        ],
        'properties': {
            'request_id': {'type': 'integer'},
            'file_name': {'type': 'string'},
            'relative_path': {'type': 'string'},
            'exists': {'type': 'boolean'},
            'byte_size': {'type': 'integer', 'nullable': True},
            'storage_backend': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'CreateReportOutputDownloadRequest': {
        'type': 'object',
        'required': ['relative_path'],
        'properties': {
            'relative_path': {'type': 'string', 'minLength': 1},
            'disposition': {'type': 'string', 'enum': ['attachment', 'inline']},
        },
        'additionalProperties': False,
    },
    'ReportOutputDownloadGrant': {
        'type': 'object',
        'required': ['download_url', 'expires_at'],
        'properties': {
            # Self-authorizing relative URL (signed token in the query string) —
            # the browser navigates to it without an RBAC header (presigned model).
            'download_url': {'type': 'string'},
            'expires_at': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'CancelReportAutomationResponse': {
        'type': 'object',
        'required': ['request_id', 'cancelled'],
        'properties': {
            'request_id': {'type': 'integer'},
            'cancelled': {'type': 'boolean'},
        },
        'additionalProperties': False,
    },
}


OPERATIONS = {
    # Pre-generation preflight (report-preflight-precheck B2, 2026-06-24). GET
    # (read-only dry-run, no side effects, immediate response — no polling).
    # session_id is the query param target.
    'get_report_preflight': _operation(
        request=None,
        response='ReportPreflightSummary',
        permission=PERMISSIONS['get_report_preflight'],
        feature='report-automation',
        query_params=[
            {
                'name': 'session_id',
                'description': (
                    'Measurement session to dry-run the report preflight for '
                    '(per-technology completeness + data-quality, no docx render).'
                ),
                'schema': {'type': 'integer', 'minimum': 1},
            },
        ],
    ),
    'get_report_request': _operation(
        request=None,
        response='ReportRequestSnapshot',
        permission=PERMISSIONS['get_report_request'],
        feature='report-automation',
    ),
    'list_report_outputs': _operation(
        request=None,
        response='ReportOutputMetadataList',
        permission=PERMISSIONS['list_report_outputs'],
        feature='report-automation',
    ),
    'create_report_output_download': _operation(
        request='CreateReportOutputDownloadRequest',
        response='ReportOutputDownloadGrant',
        permission=PERMISSIONS['create_report_output_download'],
        feature='report-automation',
    ),
    'stream_report_output_download': _operation(
        request=None,
        response='',
        permission=PERMISSIONS['stream_report_output_download'],
        feature='report-automation',
        query_params=[
            {
                'name': 'token',
                'description': 'Signed download token from the grant response.',
                'schema': {'type': 'string'},
            },
        ],
        binary_response=True,
        error_responses={
            '409': (
                'Integrity conflict — the granted file bytes no longer match the '
                'signed sha256 (changed/corrupt on disk; request a fresh grant).'
            ),
            '410': (
                'Gone — the download token/grant has expired (access window '
                'elapsed; request a fresh grant).'
            ),
        },
    ),
    'report_automation_stats': _operation(
        request=None,
        response='ReportAutomationQueueStats',
        permission=PERMISSIONS['report_automation_stats'],
        feature='report-automation',
    ),
    'cancel_report_automation_request': _operation(
        request='CancelReportAutomationRequest',
        response='CancelReportAutomationResponse',
        permission=PERMISSIONS['cancel_report_automation_request'],
        feature='report-automation',
    ),
}
