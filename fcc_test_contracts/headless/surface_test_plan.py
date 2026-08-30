"""Headless contract surface — test-plan drafts, publications, imports and generation.

Owns every declaration for /headless/projects / /headless/test-plan: the route, the permission,
the path parameters, the operation contract and the schemas only these
operations reach. One operation's contract is one place.

The boundary is measured, not chosen — see
``.claude/evaluations/headless-contract-axis.md``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fcc_test_contracts.headless.api_contract_constants import XLSX_MEDIA_TYPE
from fcc_test_contracts.headless.api_contract_operation_factory import _operation
from fcc_test_contracts.headless.api_contract_primitives import ApiContractError, _optional_text, require_object


#: Route prefixes this surface owns. Longest match wins, so a more
#: specific prefix in another surface would take precedence -- the
#: partition tests refuse that rather than letting it resolve.
SURFACE_PREFIXES = (
    '/headless/projects',
    '/headless/test-plan',
)


ROUTES = {
    # Test-plan draft authoring surface (IMPL-1, 2026-06-03). Row operations use
    # the stable {draft_row_id} handle (NOT generation_key — manual rows have
    # none). publish is documented but gated (handler raises → 403).
    'create_test_plan_draft': (
        'POST', '/headless/projects/{project_id}/test-plan/drafts',
    ),
    'get_test_plan_draft': (
        'GET', '/headless/projects/{project_id}/test-plan/drafts/{draft_id}',
    ),
    'add_test_plan_draft_row': (
        'POST', '/headless/projects/{project_id}/test-plan/drafts/{draft_id}/rows',
    ),
    'remove_test_plan_draft_row': (
        'DELETE',
        '/headless/projects/{project_id}/test-plan/drafts/{draft_id}/rows/{draft_row_id}',
    ),
    # Bulk row replace (chamber-and-draft-hardening, 2026-06-23) — PUT on the rows
    # collection (shares the path with POST add / GET; method differentiates).
    # PUT = idempotent full-replacement of the collection (RFC semantics).
    'replace_test_plan_draft_rows': (
        'PUT', '/headless/projects/{project_id}/test-plan/drafts/{draft_id}/rows',
    ),
    'validate_test_plan_draft': (
        'POST',
        '/headless/projects/{project_id}/test-plan/drafts/{draft_id}/validate',
    ),
    'publish_test_plan_draft': (
        'POST',
        '/headless/projects/{project_id}/test-plan/drafts/{draft_id}/publish',
    ),
    # Draft list + archive (draft-list-status-transition, 2026-06-03). list
    # shares the collection path with create (GET vs POST); archive is a new
    # action path. DRAFT→ARCHIVED is the only non-publish transition (terminal).
    'list_test_plan_drafts': (
        'GET', '/headless/projects/{project_id}/test-plan/drafts',
    ),
    'archive_test_plan_draft': (
        'POST',
        '/headless/projects/{project_id}/test-plan/drafts/{draft_id}/archive',
    ),
    # Published-plan list (G2, 2026-06-16). Collection of plans already published
    # in the project — distinct path segment from the draft collection.
    'list_published_test_plans': (
        'GET', '/headless/projects/{project_id}/test-plan/publications',
    ),
    # Test-plan Excel import (Phase 4 L3, 2026-06-22). multipart/form-data upload
    # (distinct ``imports`` path segment from ``drafts``/``publications``). POST
    # creates an IMPORTED draft from the workbook + records an import audit row.
    'import_test_plan': (
        'POST', '/headless/projects/{project_id}/test-plan/imports',
    ),
    # Test-plan draft Excel export (test-plan-draft-export, 2026-06-24). GET (an
    # idempotent read of an existing draft) on a new ``export`` action segment
    # under the draft resource — sibling of ``validate``/``publish``/``archive``.
    # No new path params (project_id/draft_id already declared).
    'export_test_plan_draft': (
        'GET',
        '/headless/projects/{project_id}/test-plan/drafts/{draft_id}/export',
    ),
    # Current full-generation API.
    'list_test_plan_generation_catalogue': (
        'GET', '/headless/test-plan/generation/catalogue',
    ),
    'preview_test_plan_generation': (
        'POST', '/headless/projects/{project_id}/test-plan/generation/preview',
    ),
    'submit_test_plan_generation': (
        'POST', '/headless/projects/{project_id}/test-plan/generations',
    ),
    'get_test_plan_generation': (
        'GET',
        '/headless/projects/{project_id}/test-plan/generations/{generation_job_id}',
    ),
    'get_test_plan_generation_metadata': (
        'GET',
        '/headless/projects/{project_id}/test-plan/drafts/{draft_id}/generation-metadata',
    ),
    'list_test_plan_generation_rows': (
        'GET', '/headless/projects/{project_id}/test-plan/drafts/{draft_id}/rows',
    ),
}


def _generation_string_array() -> dict:
    return {
        'type': 'array',
        'items': {'type': 'string', 'minLength': 1},
        'minItems': 1,
    }


def _generation_bands_mapping() -> dict:
    return {
        'type': 'object',
        'minProperties': 1,
        'additionalProperties': _generation_string_array(),
    }


def _generation_request_schema(properties: dict, required: list[str]) -> dict:
    return {
        'type': 'object',
        'required': required,
        'properties': properties,
        'additionalProperties': False,
    }


_GENERATION_COMMON_BANDS = {
    'bands_per_subfamily': _generation_bands_mapping(),
}


_GENERATION_BT_SCHEMA = _generation_request_schema(
    {
        'technology': {'const': 'BT'},
        'packets': _generation_string_array(),
        'modes': _generation_string_array(),
        'test_types': _generation_string_array(),
        'antennas': _generation_string_array(),
        **_GENERATION_COMMON_BANDS,
    },
    ['technology', 'packets', 'modes', 'test_types', 'antennas', 'bands_per_subfamily'],
)


_GENERATION_BLE_SCHEMA = _generation_request_schema(
    {
        'technology': {'const': 'BLE'},
        'sub_families': _generation_string_array(),
        'phys': _generation_string_array(),
        'test_types': _generation_string_array(),
        'antennas': _generation_string_array(),
        'modulations': _generation_string_array(),
        **_GENERATION_COMMON_BANDS,
    },
    [
        'technology', 'sub_families', 'phys', 'test_types', 'antennas',
        'modulations', 'bands_per_subfamily',
    ],
)


_GENERATION_WLAN_COMMON = {
    'technology': {'const': 'WLAN'},
    'stage': {'type': 'string'},
    'technologies': _generation_string_array(),
    'bands': _generation_string_array(),
    'bandwidths': _generation_string_array(),
    'channels': _generation_string_array(),
    'modulations': _generation_string_array(),
    'tests': _generation_string_array(),
    'antennas': _generation_string_array(),
    **_GENERATION_COMMON_BANDS,
}


_GENERATION_WLAN_BASE_SCHEMA = _generation_request_schema(
    {**_GENERATION_WLAN_COMMON, 'stage': {'const': 'base'}},
    [
        'technology', 'stage', 'technologies', 'bands', 'bandwidths', 'channels',
        'modulations', 'tests', 'antennas', 'bands_per_subfamily',
    ],
)


_GENERATION_WLAN_PRETEST_SCHEMA = _generation_request_schema(
    {**_GENERATION_WLAN_COMMON, 'stage': {'const': 'pretest'}},
    [
        'technology', 'stage', 'technologies', 'bands', 'bandwidths', 'channels',
        'modulations', 'tests', 'antennas', 'bands_per_subfamily',
    ],
)


_GENERATION_WLAN_MAIN_SCHEMA = _generation_request_schema(
    {
        **_GENERATION_WLAN_COMMON,
        'stage': {'const': 'main_test'},
        'source_session_id': {'type': 'string', 'minLength': 1},
        'selected_channels': _generation_string_array(),
        'worst_decision_snapshot_revision': {'type': 'string', 'minLength': 1},
    },
    [
        'technology', 'stage', 'technologies', 'bands', 'bandwidths', 'channels',
        'modulations', 'tests', 'antennas', 'bands_per_subfamily',
        'source_session_id', 'selected_channels',
        'worst_decision_snapshot_revision',
    ],
)


def _generation_snapshot_schema() -> dict:
    return {
        'type': 'object',
        'required': ['purpose', 'revision', 'sha256'],
        'properties': {
            'purpose': {'type': 'string'},
            'revision': {'type': 'string'},
            'sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
        },
        'additionalProperties': False,
    }


def _generation_estimate_schema() -> dict:
    return {
        'type': 'object',
        'required': [
            'exact_count', 'lower_bound', 'exceeds_limit',
            'direct_count', 'derived_count',
        ],
        'properties': {
            'exact_count': {'type': ['integer', 'null'], 'minimum': 0},
            'lower_bound': {'type': 'integer', 'minimum': 0},
            'exceeds_limit': {'type': 'boolean'},
            'direct_count': {'type': 'integer', 'minimum': 0},
            'derived_count': {'type': 'integer', 'minimum': 0},
        },
        'additionalProperties': False,
    }


def _generation_row_schema() -> dict:
    nullable_string = {'type': ['string', 'null']}
    return {
        'type': 'object',
        'required': [
            'draft_row_id', 'row_seq', 'capability_path', 'origin',
            'scope_revision', 'generation_key', 'test_type', 'antenna',
            'mode_family', 'tone', 'location', 'packet', 'derived_kind',
            'generated_from_capability', 'condition_hash',
        ],
        'properties': {
            'draft_row_id': {'type': 'integer', 'minimum': 1},
            'row_seq': {'type': 'integer', 'minimum': 0},
            'capability_path': _generation_string_array(),
            'origin': {'type': 'string'},
            'scope_revision': {'type': ['integer', 'null']},
            'generation_key': nullable_string,
            'test_type': nullable_string,
            'antenna': nullable_string,
            'mode_family': nullable_string,
            'tone': nullable_string,
            'location': nullable_string,
            'packet': nullable_string,
            'derived_kind': nullable_string,
            'generated_from_capability': nullable_string,
            'condition_hash': nullable_string,
        },
        'additionalProperties': False,
    }


def _generation_sample_row_schema() -> dict:
    nullable_string = {'type': ['string', 'null']}
    return {
        'type': 'object',
        'required': [
            'capability_path', 'origin', 'scope_revision', 'generation_key',
            'test_type', 'antenna', 'mode_family', 'tone', 'location', 'packet',
            'derived_kind', 'generated_from_capability', 'condition_hash',
        ],
        'properties': {
            'capability_path': _generation_string_array(),
            'origin': {'type': 'string'},
            'scope_revision': {'type': ['integer', 'null']},
            'generation_key': nullable_string,
            'test_type': nullable_string,
            'antenna': nullable_string,
            'mode_family': nullable_string,
            'tone': nullable_string,
            'location': nullable_string,
            'packet': nullable_string,
            'derived_kind': nullable_string,
            'generated_from_capability': nullable_string,
            'condition_hash': nullable_string,
        },
        'additionalProperties': False,
    }


TEST_PLAN_GENERATION_SCHEMAS: dict = {
    'BtGenerationRequest': _GENERATION_BT_SCHEMA,
    'BleGenerationRequest': _GENERATION_BLE_SCHEMA,
    'WlanBaseGenerationRequest': _GENERATION_WLAN_BASE_SCHEMA,
    'WlanPretestGenerationRequest': _GENERATION_WLAN_PRETEST_SCHEMA,
    'WlanMainTestGenerationRequest': _GENERATION_WLAN_MAIN_SCHEMA,
    'TestPlanGenerationRequest': {
        'oneOf': [
            {'$ref': '#/schemas/BtGenerationRequest'},
            {'$ref': '#/schemas/BleGenerationRequest'},
            {'$ref': '#/schemas/WlanBaseGenerationRequest'},
            {'$ref': '#/schemas/WlanPretestGenerationRequest'},
            {'$ref': '#/schemas/WlanMainTestGenerationRequest'},
        ],
    },
    'TestPlanGenerationSubmitRequest': {
        'type': 'object',
        'required': ['request', 'preview'],
        'properties': {
            'request': {'$ref': '#/schemas/TestPlanGenerationRequest'},
            'preview': {'$ref': '#/schemas/TestPlanGenerationPreviewResponse'},
        },
        'additionalProperties': False,
    },
    'TestPlanGenerationCatalogueAxis': {
        'type': 'object',
        'required': ['name', 'values'],
        'properties': {
            'name': {'type': 'string'},
            'values': {'type': 'array', 'items': {'type': 'string'}},
        },
        'additionalProperties': False,
    },
    'TestPlanGenerationLimits': {
        'type': 'object',
        'required': [
            'representative_sample_size', 'hard_row_limit', 'page_size',
            'lease_seconds', 'poll_interval_seconds', 'claim_batch_size',
            'idle_fold_p95_ms', 'keyset_page_p95_ms', 'serialized_page_bytes',
            'initial_payload_row_limit', 'browser_cache_page_limit', 'dom_row_limit',
        ],
        'properties': {
            'representative_sample_size': {'type': 'integer', 'minimum': 1},
            'hard_row_limit': {'type': 'integer', 'minimum': 1},
            'page_size': {'type': 'integer', 'minimum': 1},
            'lease_seconds': {'type': 'integer', 'minimum': 1},
            'poll_interval_seconds': {'type': 'integer', 'minimum': 1},
            'claim_batch_size': {'type': 'integer', 'minimum': 1},
            'idle_fold_p95_ms': {'type': 'integer', 'minimum': 1},
            'keyset_page_p95_ms': {'type': 'integer', 'minimum': 1},
            'serialized_page_bytes': {'type': 'integer', 'minimum': 1},
            'initial_payload_row_limit': {'type': 'integer', 'minimum': 0},
            'browser_cache_page_limit': {'type': 'integer', 'minimum': 1},
            'dom_row_limit': {'type': 'integer', 'minimum': 1},
        },
        'additionalProperties': False,
    },
    'TestPlanGenerationCatalogue': {
        'type': 'object',
        'required': [
            'technology', 'stages', 'axes', 'bands_per_subfamily', 'revision', 'sha256',
            'limits',
        ],
        'properties': {
            'technology': {'type': 'string'},
            'stages': {'type': 'array', 'items': {'type': 'string'}},
            'axes': {
                'type': 'array',
                'items': {'$ref': '#/schemas/TestPlanGenerationCatalogueAxis'},
            },
            'bands_per_subfamily': {
                'type': 'object',
                'additionalProperties': _generation_string_array(),
            },
            'revision': {'type': 'string'},
            'sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
            'limits': {'$ref': '#/schemas/TestPlanGenerationLimits'},
        },
        'additionalProperties': False,
    },
    'TestPlanGenerationCatalogueResponse': {
        'type': 'object',
        'required': ['catalogues'],
        'properties': {
            'catalogues': {
                'type': 'object',
                'additionalProperties': {
                    '$ref': '#/schemas/TestPlanGenerationCatalogue'
                },
            },
        },
        'additionalProperties': False,
    },
    'TestPlanGenerationRowView': _generation_row_schema(),
    'TestPlanGenerationSampleRow': _generation_sample_row_schema(),
    'TestPlanGenerationPreviewResponse': {
        'type': 'object',
        'required': [
            'request_sha256', 'production_matrix', 'production_estimate',
            'representative_matrix', 'representative_sample',
            'catalogue_revision', 'catalogue_sha256', 'policy_revision',
            'policy_sha256', 'fingerprint',
        ],
        'properties': {
            'request_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
            'production_matrix': _generation_snapshot_schema(),
            'production_estimate': _generation_estimate_schema(),
            'representative_matrix': _generation_snapshot_schema(),
            'representative_sample': {
                'type': 'array',
                'items': {'$ref': '#/schemas/TestPlanGenerationSampleRow'},
            },
            'catalogue_revision': {'type': 'string'},
            'catalogue_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
            'policy_revision': {'type': 'string'},
            'policy_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
            'fingerprint': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
        },
        'additionalProperties': False,
    },
    'TestPlanGenerationSubmittedResponse': {
        'type': 'object',
        'required': ['job_id', 'project_id', 'status', 'request_sha256', 'matrix_revision'],
        'properties': {
            'job_id': {'type': 'string'},
            'project_id': {'type': 'string'},
            'status': {'type': 'string'},
            'request_sha256': {'type': 'string'},
            'matrix_revision': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'TestPlanGenerationJobResponse': {
        'type': 'object',
        'required': [
            'job_id', 'project_id', 'status', 'request_sha256',
            'matrix_revision', 'matrix_sha256', 'draft_id',
            'error_code', 'error_message', 'created_at', 'updated_at',
        ],
        'properties': {
            'job_id': {'type': 'string'},
            'project_id': {'type': 'string'},
            'status': {'type': 'string'},
            'request_sha256': {'type': 'string'},
            'matrix_revision': {'type': 'string'},
            'matrix_sha256': {'type': 'string'},
            'draft_id': {'type': ['string', 'null']},
            'error_code': {'type': ['string', 'null']},
            'error_message': {'type': ['string', 'null']},
            'created_at': {'type': ['string', 'null']},
            'updated_at': {'type': ['string', 'null']},
        },
        'additionalProperties': False,
    },
    'TestPlanGenerationMetadataResponse': {
        'type': 'object',
        'required': ['job_id', 'status', 'draft_id', 'metadata'],
        'properties': {
            'job_id': {'type': 'string'},
            'status': {'type': 'string'},
            'draft_id': {'type': ['string', 'null']},
            'metadata': {'type': ['object', 'null']},
        },
        'additionalProperties': False,
    },
    'TestPlanGenerationRowPageResponse': {
        'type': 'object',
        'required': ['draft_id', 'rows', 'next_after_draft_row_id'],
        'properties': {
            'draft_id': {'type': 'string'},
            'rows': {
                'type': 'array',
                'items': {'$ref': '#/schemas/TestPlanGenerationRowView'},
            },
            'next_after_draft_row_id': {'type': ['integer', 'null']},
        },
        'additionalProperties': False,
    },
}


#: One sentence, three operations. All three reach the capability matrix — two
#: through the generation production source and one through the lazy matrix
#: provider — so a missing reference family stops all three the same way, and a
#: per-operation rewording would be three chances to describe it differently.
REFERENCE_DATA_NOT_PROVISIONED_DESCRIPTION = (
    'Reference data is not provisioned — a lookup family this operation needs '
    'has no rows, so the capability matrix cannot be built. An operator must '
    'seed it; retrying does not help.'
)


def _enum_value(value):
    """Return ``value.value`` for an Enum-like, else the value unchanged."""
    return getattr(value, 'value', value)


@dataclass(frozen=True)
class CreateTestPlanDraftRequest:
    created_by: str = ''
    # test_type_policy intentionally absent (IMPL-3 review, 2026-06-03): the
    # generator expects a policy OBJECT with ``specs_for()``, not a JSON dict —
    # exposing a raw ``object`` field would AttributeError (500) on
    # ``{"test_type_policy": {}}``. A real policy decoder is deferred (Phase 2);
    # the route always passes ``test_type_policy=None`` (channel-level default).

    @classmethod
    def from_dict(cls, data: dict) -> 'CreateTestPlanDraftRequest':
        body = require_object(data, 'create test plan draft request')
        removed_fields = sorted(
            field_name
            for field_name in ('scope_profile', 'scope_selection')
            if field_name in body
        )
        if removed_fields:
            raise ApiContractError(
                'generation fields are not accepted by the draft authoring route: '
                + ', '.join(removed_fields),
            )
        return cls(
            created_by=_optional_text(body.get('created_by')),
        )


@dataclass(frozen=True)
class AddTestPlanDraftRowRequest:
    capability_path: tuple[str, ...]
    scope_revision: Optional[int] = None
    # Authoring structural fields (manual-row-structural-fields, 2026-06-03) —
    # re-exposed now that the base TestPlanRow persists them (Option A). origin is
    # server-forced MANUAL; generation_key / generated_from_capability stay hidden.
    test_type: Optional[str] = None
    antenna: Optional[str] = None
    mode_family: Optional[str] = None
    tone: Optional[str] = None
    location: Optional[str] = None
    # Opaque wire token, not the provider enum: the allowed values are Unlicensed
    # authoring vocabulary, and enumerating them here would freeze one provider's
    # words into the shared contract (ADR-0010 D-8). The wire schema has always
    # been a nullable string; the token → enum step belongs to the lane that owns
    # the enum, and rejects an unknown token there with the same 400.
    derived_kind: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'AddTestPlanDraftRowRequest':
        body = require_object(data, 'add test plan draft row request')
        raw_path = body.get('capability_path')
        if not isinstance(raw_path, list) or not raw_path:
            raise ApiContractError('capability_path must be a non-empty array')
        # Each coordinate MUST be a non-empty string — ``[null]``/``[""]``/non-str
        # items are DTO shape failures (400), not silently coerced to ``"None"``
        # and persisted (IMPL-3 review, 2026-06-03).
        capability_path = []
        for item in raw_path:
            if not isinstance(item, str) or not item.strip():
                raise ApiContractError(
                    'capability_path items must be non-empty strings'
                )
            capability_path.append(item)
        return cls(
            capability_path=tuple(capability_path),
            scope_revision=_strict_optional_int(body.get('scope_revision'), 'scope_revision'),
            test_type=_optional_nonempty_str(body.get('test_type'), 'test_type'),
            antenna=_optional_nonempty_str(body.get('antenna'), 'antenna'),
            mode_family=_optional_nonempty_str(body.get('mode_family'), 'mode_family'),
            tone=_optional_nonempty_str(body.get('tone'), 'tone'),
            location=_optional_nonempty_str(body.get('location'), 'location'),
            derived_kind=_optional_nonempty_str(body.get('derived_kind'), 'derived_kind'),
        )


@dataclass(frozen=True)
class ReplaceTestPlanDraftRowsRequest:
    """Replace ALL rows in a draft with a new set (bulk replace, single txn).

    ``rows`` is the full desired row set (each element has the same shape as an
    ``AddTestPlanDraftRowRequest``). An empty array is valid (clear all rows). The
    server forces ``origin=MANUAL`` per row (clients never set origin).
    """

    rows: tuple

    @classmethod
    def from_dict(cls, data: dict) -> 'ReplaceTestPlanDraftRowsRequest':
        body = require_object(data, 'replace test plan draft rows request')
        raw_rows = body.get('rows')
        if not isinstance(raw_rows, list):
            raise ApiContractError('rows must be an array')
        # Reuse the single-row DTO parser so every row gets the identical shape
        # validation (non-empty capability_path, optional structural fields) — no
        # divergent per-row validation for the bulk path.
        parsed = tuple(AddTestPlanDraftRowRequest.from_dict(item) for item in raw_rows)
        return cls(rows=parsed)


@dataclass(frozen=True)
class ReplaceTestPlanDraftRowsResponse:
    """Result of a bulk row replace — the new row set with stable handles."""

    draft_id: str
    replaced_count: int
    rows: list  # list[TestPlanDraftRowView]

    def to_dict(self) -> dict:
        return {
            'draft_id': self.draft_id,
            'replaced_count': self.replaced_count,
            'rows': [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True)
class TestPlanDraftRowView:
    draft_row_id: int
    capability_path: list[str]
    origin: str
    scope_revision: Optional[int] = None
    generation_key: Optional[str] = None
    test_type: Optional[str] = None
    antenna: Optional[str] = None
    mode_family: Optional[str] = None
    tone: Optional[str] = None
    location: Optional[str] = None
    derived_kind: Optional[str] = None

    @classmethod
    def from_handle(cls, handle) -> 'TestPlanDraftRowView':
        """Build from a ``TestPlanDraftRow`` (``draft_row_id`` + authoring ``row``)."""
        row = handle.row
        return cls(
            draft_row_id=int(handle.draft_row_id),
            capability_path=list(row.capability_path),
            origin=str(_enum_value(row.origin)),
            scope_revision=row.scope_revision,
            generation_key=getattr(row, 'generation_key', None),
            test_type=getattr(row, 'test_type', None),
            antenna=getattr(row, 'antenna', None),
            mode_family=getattr(row, 'mode_family', None),
            tone=getattr(row, 'tone', None),
            location=getattr(row, 'location', None),
            derived_kind=(
                getattr(row, 'derived_kind', None).value
                if getattr(row, 'derived_kind', None) is not None
                else None
            ),
        )

    def to_dict(self) -> dict:
        return {
            'draft_row_id': self.draft_row_id,
            'capability_path': self.capability_path,
            'origin': self.origin,
            'scope_revision': self.scope_revision,
            'generation_key': self.generation_key,
            'test_type': self.test_type,
            'antenna': self.antenna,
            'mode_family': self.mode_family,
            'tone': self.tone,
            'location': self.location,
            'derived_kind': self.derived_kind,
        }


@dataclass(frozen=True)
class TestPlanDraftView:
    draft_id: str
    project_id: str
    status: str
    rows: list
    scope_revision: Optional[int] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    # Generation provenance reload surface (bt-draft-metadata-reload-surface,
    # 2026-06-07). Exposed as the **raw opaque snapshot string** (not a decoded
    # options+summary DTO) on purpose: this contract layer is dependency-free
    # (imports no domain/application types) and the draft model holds the field
    # as opaque + tech-neutral — decoding it here would couple a generic draft
    # view to BT-specific schema. The headless client decodes the published
    # deterministic serialization (schema_version) to reproduce the selection
    # conditions. Nullable: legacy / non-BT / scope-only drafts carry None.
    generation_metadata_json: Optional[str] = None

    @classmethod
    def from_domain(cls, draft, row_handles) -> 'TestPlanDraftView':
        """Build from a ``TestPlanDraft`` + its ``TestPlanDraftRow`` handles."""
        created_at = draft.created_at.isoformat() if draft.created_at else None
        return cls(
            draft_id=draft.draft_id,
            project_id=draft.project_id,
            status=str(_enum_value(draft.status)),
            rows=[TestPlanDraftRowView.from_handle(h) for h in row_handles],
            scope_revision=draft.scope_revision,
            created_by=draft.created_by,
            created_at=created_at,
            # getattr keeps this dependency-free + tolerant of a legacy draft
            # object built before the field existed (None pass-through).
            generation_metadata_json=getattr(draft, 'generation_metadata_json', None),
        )

    def to_dict(self) -> dict:
        return {
            'draft_id': self.draft_id,
            'project_id': self.project_id,
            'scope_revision': self.scope_revision,
            'status': self.status,
            'created_by': self.created_by,
            'created_at': self.created_at,
            'generation_metadata_json': self.generation_metadata_json,
            'rows': [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True)
class PublishedTestPlanRowView:
    """A single materialized row of a published plan (condition_hash 확정).

    ``TestPlanDraftRowView`` 의 published 대응 — draft row 가 ``draft_row_id`` (편집
    핸들) + ``condition_hash=None`` 이던 것과 달리, published row 는 measurement
    condition identity (``condition_hash``, 64-hex non-null)가 확정되어 있고 편집
    핸들이 없다 (immutable). 같은 authoring 구조 필드를 노출하되 ``condition_hash``
    를 1급으로 올린다. dependency-free (domain 타입 import 0 — duck-typing).
    """
    condition_hash: str
    capability_path: list[str]
    origin: str
    scope_revision: Optional[int] = None
    generation_key: Optional[str] = None
    test_type: Optional[str] = None
    antenna: Optional[str] = None
    mode_family: Optional[str] = None
    tone: Optional[str] = None
    location: Optional[str] = None
    derived_kind: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> 'PublishedTestPlanRowView':
        """Build from a materialized ``TestPlanRow`` (``condition_hash`` non-None)."""
        derived = getattr(row, 'derived_kind', None)
        return cls(
            condition_hash=str(row.condition_hash),
            capability_path=list(row.capability_path),
            origin=str(_enum_value(row.origin)),
            scope_revision=row.scope_revision,
            generation_key=getattr(row, 'generation_key', None),
            test_type=getattr(row, 'test_type', None),
            antenna=getattr(row, 'antenna', None),
            mode_family=getattr(row, 'mode_family', None),
            tone=getattr(row, 'tone', None),
            location=getattr(row, 'location', None),
            derived_kind=_enum_value(derived) if derived is not None else None,
        )

    def to_dict(self) -> dict:
        return {
            'condition_hash': self.condition_hash,
            'capability_path': self.capability_path,
            'origin': self.origin,
            'scope_revision': self.scope_revision,
            'generation_key': self.generation_key,
            'test_type': self.test_type,
            'antenna': self.antenna,
            'mode_family': self.mode_family,
            'tone': self.tone,
            'location': self.location,
            'derived_kind': self.derived_kind,
        }


@dataclass(frozen=True)
class PublishedTestPlanView:
    """An immutable published test plan — publish 결과 resource (publish-route-wiring).

    draft view (편집 surface) 와 별개 resource: publish 는 server-generated ``plan_id``
    (publication 정체성)와 materialized ``condition_hash`` row 를 만든다 — draft view
    로 응답하면 둘 다 노출되지 않아 client 가 방금 만든 publication 을 참조할 수 없다.
    멱등 publish (같은 draft 재호출)는 같은 ``plan_id`` 를 돌려준다 (route 봉인).
    ``scope_profile_json``/``generation_metadata_json`` 은 publish 시점 draft 스냅샷
    그대로 (감사). 두 스냅샷은 **opt-in** payload 다 — ``to_dict(include_snapshots=...)``
    가 False (기본) 면 ``None`` 으로 비워 응답을 가볍게 유지하고, True 일 때만 원본
    snapshot 을 노출한다 (route 의 ``?include_snapshots=`` 쿼리 게이트가 주입).
    schema 는 두 필드를 nullable + non-required 로 두므로 기본 None 은 계약 비파괴.
    dependency-free (domain ``PublishedTestPlan`` duck-typing).
    """
    __test__ = False  # 'Test' substring — pytest 오수집 차단.

    plan_id: str
    draft_id: str
    project_id: str
    status: str
    rows: list
    scope_revision: Optional[int] = None
    scope_profile_json: Optional[str] = None
    generation_metadata_json: Optional[str] = None
    published_by: Optional[str] = None
    published_at: Optional[str] = None

    # status 는 published plan 의 고정 상태 — published plan 은 정의상 PUBLISHED 다.
    # draft DraftStatus enum 을 import 하지 않으려고 (dependency-free) 리터럴 토큰을
    # DraftStatus.PUBLISHED.value 와 동일하게 둔다 (계약 schema status='published').
    _STATUS_PUBLISHED = 'published'

    @classmethod
    def from_plan(cls, plan) -> 'PublishedTestPlanView':
        """Build from a domain ``PublishedTestPlan`` (publish 결과 value object)."""
        published_at = (
            plan.published_at.isoformat()
            if getattr(plan, 'published_at', None) is not None
            else None
        )
        return cls(
            plan_id=plan.plan_id,
            draft_id=plan.draft_id,
            project_id=plan.project_id,
            status=cls._STATUS_PUBLISHED,
            rows=[PublishedTestPlanRowView.from_row(r) for r in plan.rows],
            scope_revision=plan.scope_revision,
            scope_profile_json=getattr(plan, 'scope_profile_json', None),
            generation_metadata_json=getattr(plan, 'generation_metadata_json', None),
            published_by=getattr(plan, 'published_by', None),
            published_at=published_at,
        )

    def to_dict(self, *, include_snapshots: bool = False) -> dict:
        # ``scope_profile_json`` + ``generation_metadata_json`` are verbatim
        # publish-time audit snapshots — opt-in payload. Default (False) emits
        # them as ``None`` (key present, schema-valid: both nullable + not
        # required) so the response stays lean; the route's ``?include_snapshots=``
        # query gate sets True to surface the originals.
        return {
            'plan_id': self.plan_id,
            'draft_id': self.draft_id,
            'project_id': self.project_id,
            'status': self.status,
            'scope_revision': self.scope_revision,
            'scope_profile_json': self.scope_profile_json if include_snapshots else None,
            'generation_metadata_json': (
                self.generation_metadata_json if include_snapshots else None
            ),
            'published_by': self.published_by,
            'published_at': self.published_at,
            'rows': [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True)
class ValidationIssueView:
    issue_type: str
    severity: str
    message: str
    condition_hash: Optional[str] = None
    capability_path: Optional[list[str]] = None

    @classmethod
    def from_issue(cls, issue) -> 'ValidationIssueView':
        capability_path = issue.capability_path
        return cls(
            issue_type=str(_enum_value(issue.issue_type)),
            severity=str(_enum_value(issue.severity)),
            message=issue.message,
            condition_hash=issue.condition_hash,
            capability_path=list(capability_path) if capability_path is not None else None,
        )

    def to_dict(self) -> dict:
        return {
            'issue_type': self.issue_type,
            'severity': self.severity,
            'message': self.message,
            'condition_hash': self.condition_hash,
            'capability_path': self.capability_path,
        }


@dataclass(frozen=True)
class ValidateTestPlanDraftResponse:
    draft_id: str
    issues: list
    error_count: int
    warning_count: int

    @classmethod
    def from_issues(cls, draft_id: str, issues) -> 'ValidateTestPlanDraftResponse':
        views = [ValidationIssueView.from_issue(issue) for issue in issues]
        error_count = sum(1 for v in views if v.severity == 'error')
        warning_count = sum(1 for v in views if v.severity == 'warning')
        return cls(
            draft_id=draft_id,
            issues=views,
            error_count=error_count,
            warning_count=warning_count,
        )

    def to_dict(self) -> dict:
        return {
            'draft_id': self.draft_id,
            'issues': [issue.to_dict() for issue in self.issues],
            'error_count': self.error_count,
            'warning_count': self.warning_count,
        }


@dataclass(frozen=True)
class RemoveTestPlanDraftRowResponse:
    draft_id: str
    draft_row_id: int
    removed: bool = True

    def to_dict(self) -> dict:
        return {
            'draft_id': self.draft_id,
            'draft_row_id': self.draft_row_id,
            'removed': self.removed,
        }


@dataclass(frozen=True)
class TestPlanDraftSummaryView:
    """Lightweight draft list item — metadata + row_count, NO rows (D4).

    Read from a domain ``DraftSummary`` by duck-typing so this module imports no
    domain types (dependency-free contract layer).
    """
    draft_id: str
    project_id: str
    status: str
    row_count: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_domain(cls, summary) -> 'TestPlanDraftSummaryView':
        return cls(
            draft_id=summary.draft_id,
            project_id=summary.project_id,
            status=str(_enum_value(summary.status)),
            row_count=int(summary.row_count),
            created_at=summary.created_at.isoformat() if summary.created_at else None,
            updated_at=summary.updated_at.isoformat() if summary.updated_at else None,
        )

    def to_dict(self) -> dict:
        return {
            'draft_id': self.draft_id,
            'project_id': self.project_id,
            'status': self.status,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'row_count': self.row_count,
        }


@dataclass(frozen=True)
class ListTestPlanDraftsResponse:
    drafts: list
    # Opaque keyset cursor for the next page, or None on the last page / an
    # uncapped read (draft-list-keyset, 2026-06-13). Additive — existing clients
    # that ignore it see the same ``drafts`` array; backward-compatible
    # ``from_summaries`` callers get ``next_cursor=None``.
    next_cursor: Optional[str] = None

    @classmethod
    def from_summaries(cls, summaries) -> 'ListTestPlanDraftsResponse':
        return cls(
            drafts=[TestPlanDraftSummaryView.from_domain(s) for s in summaries],
        )

    @classmethod
    def from_page(cls, page) -> 'ListTestPlanDraftsResponse':
        """Build from a domain ``DraftListPage`` — encodes ``next_cursor`` to a token.

        The cursor value object is opaque to the contract layer; this boundary
        encodes it into the base64url ``next_cursor`` string the client echoes
        back as the ``cursor`` query param. None cursor → last page.
        """
        return cls(
            drafts=[TestPlanDraftSummaryView.from_domain(s) for s in page.summaries],
            next_cursor=page.next_cursor.encode() if page.next_cursor else None,
        )

    def to_dict(self) -> dict:
        return {
            'drafts': [draft.to_dict() for draft in self.drafts],
            'next_cursor': self.next_cursor,
        }


@dataclass(frozen=True)
class PublishedTestPlanSummaryView:
    """Lightweight published-plan list item — identity + row_count + provenance (G2).

    Read from a domain ``PublishedTestPlanSummary`` by duck-typing so this module
    imports no domain types (dependency-free contract layer). NO rows / scope
    snapshots — a list item is not the full ``PublishedTestPlanView`` resource.
    ``status`` is the fixed ``'published'`` token (a published plan is, by
    definition, PUBLISHED — mirrors ``PublishedTestPlanView._STATUS_PUBLISHED``).
    """
    __test__ = False  # 'Test' substring — pytest 오수집 차단.

    plan_id: str
    draft_id: str
    project_id: str
    status: str
    row_count: int
    published_by: Optional[str] = None
    published_at: Optional[str] = None

    _STATUS_PUBLISHED = 'published'

    @classmethod
    def from_domain(cls, summary) -> 'PublishedTestPlanSummaryView':
        published_at = (
            summary.published_at.isoformat()
            if getattr(summary, 'published_at', None) is not None
            else None
        )
        return cls(
            plan_id=summary.plan_id,
            draft_id=summary.draft_id,
            project_id=summary.project_id,
            status=cls._STATUS_PUBLISHED,
            row_count=int(summary.row_count),
            published_by=getattr(summary, 'published_by', None),
            published_at=published_at,
        )

    def to_dict(self) -> dict:
        return {
            'plan_id': self.plan_id,
            'draft_id': self.draft_id,
            'project_id': self.project_id,
            'status': self.status,
            'row_count': self.row_count,
            'published_by': self.published_by,
            'published_at': self.published_at,
        }


@dataclass(frozen=True)
class ListPublishedTestPlansResponse:
    """Authoritative list of a project's published plans (G2, newest-first).

    Replaces the frontend ``published-plan-registry.ts`` browser-local recency
    cache as the SSOT for plan selection. Keyset cursor pagination is an additive
    P2 follow-up (a ``next_cursor`` key can be added without breaking the
    ``publications`` array — same evolution path as the draft list).
    """
    __test__ = False  # 'Test' substring — pytest 오수집 차단.

    publications: list

    @classmethod
    def from_summaries(cls, summaries) -> 'ListPublishedTestPlansResponse':
        return cls(
            publications=[
                PublishedTestPlanSummaryView.from_domain(s) for s in summaries
            ],
        )

    def to_dict(self) -> dict:
        return {
            'publications': [pub.to_dict() for pub in self.publications],
        }


@dataclass(frozen=True)
class TestPlanImportResponse:
    """Test-plan Excel import outcome (Phase 4 L3, 2026-06-22).

    Serializes the application ``ImportOutcome`` + the persisted ``import_id`` for
    the SPA. Duck-types the domain audit/issue/excluded value objects so this
    dependency-free contract layer imports no domain types. ``draft_id`` is null
    when every source row was an issue/exclusion (no draft was persisted).
    """
    __test__ = False  # 'Test' substring — pytest 오수집 차단.

    import_id: str
    draft_id: Optional[str]
    audit: dict
    issues: list
    excluded: list

    @classmethod
    def from_outcome(cls, outcome, import_id: str) -> 'TestPlanImportResponse':
        audit = outcome.audit
        return cls(
            import_id=import_id,
            draft_id=outcome.draft_id,
            audit={
                'workbook_filename': audit.workbook_filename,
                'workbook_sha256': audit.workbook_sha256,
                'sheet_name': audit.sheet_name,
                'parser_version': audit.parser_version,
                'raw_row_count': audit.raw_row_count,
                'legend_skipped_count': audit.legend_skipped_count,
                'accepted_count': audit.accepted_count,
                'issue_count': audit.issue_count,
                'excluded_count': audit.excluded_count,
                'by_technology': [
                    {
                        'technology': s.technology,
                        'accepted': s.accepted,
                        'issues': s.issues,
                        'excluded': s.excluded,
                    }
                    for s in audit.by_technology
                ],
            },
            issues=[
                {
                    'row_number': i.row_number,
                    'severity': i.severity,
                    'field': i.field,
                    'message': i.message,
                }
                for i in outcome.issues
            ],
            excluded=[
                {
                    'row_number': e.row_number,
                    'reason': e.reason,
                    'detail': e.detail,
                }
                for e in outcome.excluded
            ],
        )

    def to_dict(self) -> dict:
        return {
            'import_id': self.import_id,
            'draft_id': self.draft_id,
            'audit': self.audit,
            'issues': self.issues,
            'excluded': self.excluded,
        }


def _strict_optional_int(value, key: str) -> Optional[int]:
    """Like ``_optional_int`` but a bad value is a contract (400) error.

    ``int('abc')``/``int([])`` raise ``ValueError``/``TypeError``; left unwrapped
    they escape as a bare ``ValueError`` → 404 via the broad route boundary.
    Wrapping in ``ApiContractError`` maps the DTO shape failure to 400.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ApiContractError(f'{key} must be an integer') from exc


def _optional_nonempty_str(value, key: str) -> Optional[str]:
    """Optional authoring field: ``None`` is allowed, a non-empty string passes,
    but a non-string or empty/whitespace-only string is a contract (400) error.

    Empty string is rejected (rather than coerced to None) so the client gets an
    explicit DTO shape failure instead of a silently dropped field.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ApiContractError(f'{key} must be a non-empty string when provided')
    return value


PERMISSIONS = {
    # Test-plan draft authoring surface (IMPL-1, 2026-06-03). read = GET/validate
    # (non-mutating), author = create draft + add/remove draft rows (write).
    'create_test_plan_draft': 'test_plan:author',
    'get_test_plan_draft': 'test_plan:read',
    'add_test_plan_draft_row': 'test_plan:author',
    'remove_test_plan_draft_row': 'test_plan:author',
    # Bulk row replace (chamber-and-draft-hardening, 2026-06-23) — replace ALL
    # rows in one transaction so the editor never loses rows on a partial failure.
    # Same author write token (no RBAC grant-matrix change).
    'replace_test_plan_draft_rows': 'test_plan:author',
    'validate_test_plan_draft': 'test_plan:read',
    # publish authorize passes for an author but the handler is gated (403) —
    # ADR-0005 execution-gated (Phase 2). See HeadlessApiAdapter.publish_*.
    'publish_test_plan_draft': 'test_plan:author',
    # Draft list + archive status transition (draft-list-status-transition,
    # 2026-06-03). list = non-mutating read; archive = DRAFT→ARCHIVED write.
    'list_test_plan_drafts': 'test_plan:read',
    'archive_test_plan_draft': 'test_plan:author',
    # Authoritative published-plan list (G2, 2026-06-16) — non-mutating read of
    # plans already published in a project (replaces the frontend browser-local
    # recency cache as SSOT). read permission (shares test_plan:read).
    'list_published_test_plans': 'test_plan:read',
    # Test-plan Excel import (Phase 4 L3, 2026-06-22). Upload a workbook → parse →
    # capability-map → IMPORTED draft. author = create draft (write surface) so it
    # shares the existing test_plan:author token (no RBAC grant-matrix change).
    'import_test_plan': 'test_plan:author',
    # Test-plan draft Excel export (test-plan-draft-export, 2026-06-24). Download
    # the draft as an .xlsx — a non-mutating read of an existing draft, so it
    # reuses the existing read token (NO new grantable token).
    'export_test_plan_draft': 'test_plan:read',
    # Current provider-neutral full-generation surface.
    'list_test_plan_generation_catalogue': 'test_plan:read',
    'preview_test_plan_generation': 'test_plan:read',
    'submit_test_plan_generation': 'test_plan:author',
    'get_test_plan_generation': 'test_plan:read',
    'get_test_plan_generation_metadata': 'test_plan:read',
    'list_test_plan_generation_rows': 'test_plan:read',
}


SCHEMAS = {
    # ── Test-plan draft authoring (IMPL-1, 2026-06-03) ──────────────────────
    'CreateTestPlanDraftRequest': {
        'type': 'object',
        'properties': {
            'created_by': {'type': 'string', 'default': ''},
            # test_type_policy is NOT exposed: the generator needs a policy object
            # (specs_for()), not a JSON dict — Phase 1 always uses the channel-level
            # default (policy decoder deferred to Phase 2).
        },
        'additionalProperties': False,
    },
    'AddTestPlanDraftRowRequest': {
        'type': 'object',
        'required': ['capability_path'],
        'properties': {
            'capability_path': {'type': 'array', 'items': {'type': 'string'}},
            'scope_revision': {'type': 'integer', 'nullable': True},
            # Authoring structural fields (manual-row-structural-fields, 2026-06-03)
            # — optional; null or a non-empty string (empty string → 400). origin is
            # server-forced MANUAL; generation_key/generated_from_capability hidden.
            'test_type': {'type': 'string', 'nullable': True},
            'antenna': {'type': 'string', 'nullable': True},
            'mode_family': {'type': 'string', 'nullable': True},
            'tone': {'type': 'string', 'nullable': True},
            'location': {'type': 'string', 'nullable': True},
            'derived_kind': {
                'type': 'string',
                'enum': ['afh_occupancy', 'antenna_sum'],
                'nullable': True,
            },
        },
        'additionalProperties': False,
    },
    # Bulk row replace (chamber-and-draft-hardening, 2026-06-23). The request is
    # the full desired row set (reuses the single-row request schema per item so
    # the shape validation is identical). Empty array = clear all rows.
    'ReplaceTestPlanDraftRowsRequest': {
        'type': 'object',
        'required': ['rows'],
        'properties': {
            'rows': {
                'type': 'array',
                'items': {'$ref': '#/schemas/AddTestPlanDraftRowRequest'},
            },
        },
        'additionalProperties': False,
    },
    'ReplaceTestPlanDraftRowsResponse': {
        'type': 'object',
        'required': ['draft_id', 'replaced_count', 'rows'],
        'properties': {
            'draft_id': {'type': 'string'},
            'replaced_count': {'type': 'integer'},
            'rows': {
                'type': 'array',
                'items': {'$ref': '#/schemas/TestPlanDraftRowView'},
            },
        },
        'additionalProperties': False,
    },
    'TestPlanDraftRowView': {
        'type': 'object',
        'required': ['draft_row_id', 'capability_path', 'origin'],
        'properties': {
            # Stable delete/update handle (test_plan_draft_rows.id) — NOT
            # generation_key (which generated rows alone carry).
            'draft_row_id': {'type': 'integer'},
            'capability_path': {'type': 'array', 'items': {'type': 'string'}},
            'origin': {'type': 'string'},
            'scope_revision': {'type': 'integer', 'nullable': True},
            'generation_key': {'type': 'string', 'nullable': True},
            'test_type': {'type': 'string', 'nullable': True},
            'antenna': {'type': 'string', 'nullable': True},
            'mode_family': {'type': 'string', 'nullable': True},
            'tone': {'type': 'string', 'nullable': True},
            'location': {'type': 'string', 'nullable': True},
            'derived_kind': {
                'type': 'string',
                'enum': ['afh_occupancy', 'antenna_sum'],
                'nullable': True,
            },
        },
        'additionalProperties': False,
    },
    'TestPlanDraftView': {
        'type': 'object',
        'required': ['draft_id', 'project_id', 'status', 'rows'],
        'properties': {
            'draft_id': {'type': 'string'},
            'project_id': {'type': 'string'},
            'scope_revision': {'type': 'integer', 'nullable': True},
            'status': {'type': 'string'},
            'created_by': {'type': 'string', 'nullable': True},
            'created_at': {'type': 'string', 'nullable': True},
            # Raw opaque generation-provenance snapshot (bt-draft-metadata-reload-
            # surface, 2026-06-07). A deterministic JSON string the client decodes
            # (schema_version) to reproduce the selection conditions — exposed raw,
            # NOT as a decoded options+summary object, to keep this contract
            # tech-neutral. Nullable: legacy / non-BT / scope-only drafts carry null.
            'generation_metadata_json': {'type': 'string', 'nullable': True},
            'rows': {
                'type': 'array',
                'items': {'$ref': '#/schemas/TestPlanDraftRowView'},
            },
        },
        'additionalProperties': False,
    },
    # Published-plan resource (test-plan-publish-route-wiring, 2026-06-07). The
    # publish route returns this (NOT a draft view): a published plan carries a
    # server-generated plan_id + materialized condition_hash rows that a draft
    # view cannot express. A repeat publish of the same draft returns the same
    # plan_id (idempotent).
    'PublishedTestPlanRowView': {
        'type': 'object',
        'required': ['condition_hash', 'capability_path', 'origin'],
        'properties': {
            # Materialized measurement condition identity — sha256 hexdigest
            # (exactly 64 lowercase hex). Non-null for every published row.
            'condition_hash': {'type': 'string'},
            'capability_path': {'type': 'array', 'items': {'type': 'string'}},
            'origin': {'type': 'string'},
            'scope_revision': {'type': 'integer', 'nullable': True},
            'generation_key': {'type': 'string', 'nullable': True},
            'test_type': {'type': 'string', 'nullable': True},
            'antenna': {'type': 'string', 'nullable': True},
            'mode_family': {'type': 'string', 'nullable': True},
            'tone': {'type': 'string', 'nullable': True},
            'location': {'type': 'string', 'nullable': True},
            'derived_kind': {
                'type': 'string',
                'enum': ['afh_occupancy', 'antenna_sum'],
                'nullable': True,
            },
        },
        'additionalProperties': False,
    },
    'PublishedTestPlanView': {
        'type': 'object',
        'required': ['plan_id', 'draft_id', 'project_id', 'status', 'rows'],
        'properties': {
            'plan_id': {'type': 'string'},
            'draft_id': {'type': 'string'},
            'project_id': {'type': 'string'},
            # Always 'published' for this resource (published plan is terminal).
            'status': {'type': 'string'},
            'scope_revision': {'type': 'integer', 'nullable': True},
            # Immutable publish-time snapshots copied verbatim from the draft
            # (audit) — never re-serialized at publish.
            'scope_profile_json': {'type': 'string', 'nullable': True},
            'generation_metadata_json': {'type': 'string', 'nullable': True},
            'published_by': {'type': 'string', 'nullable': True},
            'published_at': {'type': 'string', 'nullable': True},
            'rows': {
                'type': 'array',
                'items': {'$ref': '#/schemas/PublishedTestPlanRowView'},
            },
        },
        'additionalProperties': False,
    },
    'ValidationIssueView': {
        'type': 'object',
        'required': ['issue_type', 'severity', 'message'],
        'properties': {
            'issue_type': {'type': 'string'},
            'severity': {'type': 'string'},
            'message': {'type': 'string'},
            'condition_hash': {'type': 'string', 'nullable': True},
            'capability_path': {
                'type': 'array',
                'items': {'type': 'string'},
                'nullable': True,
            },
        },
        'additionalProperties': False,
    },
    'ValidateTestPlanDraftResponse': {
        'type': 'object',
        'required': ['draft_id', 'issues', 'error_count', 'warning_count'],
        'properties': {
            'draft_id': {'type': 'string'},
            'issues': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ValidationIssueView'},
            },
            'error_count': {'type': 'integer'},
            'warning_count': {'type': 'integer'},
        },
        'additionalProperties': False,
    },
    'RemoveTestPlanDraftRowResponse': {
        'type': 'object',
        'required': ['draft_id', 'draft_row_id', 'removed'],
        'properties': {
            'draft_id': {'type': 'string'},
            'draft_row_id': {'type': 'integer'},
            # Idempotent delete — True means the row is absent after the call.
            'removed': {'type': 'boolean'},
        },
        'additionalProperties': False,
    },
    # Draft list view (draft-list-status-transition, 2026-06-03). Lightweight
    # summary — metadata + aggregate row_count, NO rows hydrated (the list must
    # not materialize every candidate row just to render a table).
    'TestPlanDraftSummaryView': {
        'type': 'object',
        'required': ['draft_id', 'project_id', 'status', 'row_count'],
        'properties': {
            'draft_id': {'type': 'string'},
            'project_id': {'type': 'string'},
            'status': {'type': 'string'},
            'created_at': {'type': 'string', 'nullable': True},
            'updated_at': {'type': 'string', 'nullable': True},
            'row_count': {'type': 'integer'},
        },
        'additionalProperties': False,
    },
    'ListTestPlanDraftsResponse': {
        'type': 'object',
        'required': ['drafts'],
        'properties': {
            'drafts': {
                'type': 'array',
                'items': {'$ref': '#/schemas/TestPlanDraftSummaryView'},
            },
            # Opaque keyset cursor (draft-list-keyset, 2026-06-13). Non-null →
            # more pages exist (echo it back as the ``cursor`` query param); null
            # → last page / uncapped read. Additive (not required) so existing
            # array-only clients stay compatible.
            'next_cursor': {'type': 'string', 'nullable': True},
        },
        'additionalProperties': False,
    },
    # Published-plan list (G2, 2026-06-16). Authoritative source for "which plans
    # has this project published" — identity + row_count + provenance, NO rows.
    'PublishedTestPlanSummaryView': {
        'type': 'object',
        'required': ['plan_id', 'draft_id', 'project_id', 'status', 'row_count'],
        'properties': {
            'plan_id': {'type': 'string'},
            'draft_id': {'type': 'string'},
            'project_id': {'type': 'string'},
            'status': {'type': 'string', 'enum': ['published']},
            'row_count': {'type': 'integer'},
            'published_by': {'type': 'string', 'nullable': True},
            'published_at': {'type': 'string', 'nullable': True},
        },
        'additionalProperties': False,
    },
    'ListPublishedTestPlansResponse': {
        'type': 'object',
        'required': ['publications'],
        'properties': {
            'publications': {
                'type': 'array',
                'items': {'$ref': '#/schemas/PublishedTestPlanSummaryView'},
            },
        },
        'additionalProperties': False,
    },
    # ── Test-plan Excel import (Phase 4 L3, 2026-06-22) ─────────────────────
    # Per-technology honest accounting (R1): accepted/issues/excluded counts.
    'ImportTechnologySummaryView': {
        'type': 'object',
        'required': ['technology', 'accepted', 'issues', 'excluded'],
        'properties': {
            'technology': {'type': 'string'},
            'accepted': {'type': 'integer'},
            'issues': {'type': 'integer'},
            'excluded': {'type': 'integer'},
        },
        'additionalProperties': False,
    },
    # Workbook provenance + honest row accounting
    # (raw == legend_skipped + accepted + issue + excluded).
    'ImportAuditView': {
        'type': 'object',
        'required': [
            'workbook_filename', 'workbook_sha256', 'sheet_name', 'parser_version',
            'raw_row_count', 'legend_skipped_count', 'accepted_count',
            'issue_count', 'excluded_count', 'by_technology',
        ],
        'properties': {
            'workbook_filename': {'type': 'string'},
            'workbook_sha256': {'type': 'string'},
            'sheet_name': {'type': 'string'},
            'parser_version': {'type': 'string'},
            'raw_row_count': {'type': 'integer'},
            'legend_skipped_count': {'type': 'integer'},
            'accepted_count': {'type': 'integer'},
            'issue_count': {'type': 'integer'},
            'excluded_count': {'type': 'integer'},
            'by_technology': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ImportTechnologySummaryView'},
            },
        },
        'additionalProperties': False,
    },
    # Blocking issue — a source row that could not be mapped to the taxonomy.
    'ImportIssueView': {
        'type': 'object',
        'required': ['row_number', 'severity', 'field', 'message'],
        'properties': {
            'row_number': {'type': 'integer'},
            'severity': {'type': 'string'},
            'field': {'type': 'string'},
            'message': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    # Observable exclusion — an intentionally-skipped row (CS / BT AFH derived).
    'ExcludedImportRowView': {
        'type': 'object',
        'required': ['row_number', 'reason', 'detail'],
        'properties': {
            'row_number': {'type': 'integer'},
            'reason': {'type': 'string'},
            'detail': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'TestPlanImportResponse': {
        'type': 'object',
        'required': ['import_id', 'draft_id', 'audit', 'issues', 'excluded'],
        'properties': {
            'import_id': {'type': 'string'},
            # null when every row was an issue/exclusion (no draft persisted).
            'draft_id': {'type': 'string', 'nullable': True},
            'audit': {'$ref': '#/schemas/ImportAuditView'},
            'issues': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ImportIssueView'},
            },
            'excluded': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ExcludedImportRowView'},
            },
        },
        'additionalProperties': False,
    },
    **TEST_PLAN_GENERATION_SCHEMAS,
}


OPERATIONS = {
    # ── Test-plan draft authoring (IMPL-1, 2026-06-03) ──────────────────────
    'create_test_plan_draft': _operation(
        request='CreateTestPlanDraftRequest',
        response='TestPlanDraftView',
        permission=PERMISSIONS['create_test_plan_draft'],
    ),
    'get_test_plan_draft': _operation(
        request=None,
        response='TestPlanDraftView',
        permission=PERMISSIONS['get_test_plan_draft'],
    ),
    'add_test_plan_draft_row': _operation(
        request='AddTestPlanDraftRowRequest',
        response='TestPlanDraftRowView',
        permission=PERMISSIONS['add_test_plan_draft_row'],
    ),
    'remove_test_plan_draft_row': _operation(
        request=None,
        response='RemoveTestPlanDraftRowResponse',
        permission=PERMISSIONS['remove_test_plan_draft_row'],
    ),
    # Bulk row replace (chamber-and-draft-hardening, 2026-06-23) — replace ALL rows
    # in one atomic transaction (PUT on the rows collection). The editor sends the
    # full desired row set; the server deletes existing rows + inserts the new set
    # in one transaction so a partial failure can never lose rows.
    'replace_test_plan_draft_rows': _operation(
        request='ReplaceTestPlanDraftRowsRequest',
        response='ReplaceTestPlanDraftRowsResponse',
        permission=PERMISSIONS['replace_test_plan_draft_rows'],
        error_responses={
            '404': (
                'Draft not found, or it belongs to a different project '
                '(cross-project existence is hidden behind the project scope).'
            ),
            '409': (
                'Row replace conflict — the draft is not DRAFT (archived/published, '
                'terminal row freeze) or a DB integrity constraint was violated.'
            ),
        },
    ),
    'validate_test_plan_draft': _operation(
        request=None,
        response='ValidateTestPlanDraftResponse',
        permission=PERMISSIONS['validate_test_plan_draft'],
        error_responses={'503': REFERENCE_DATA_NOT_PROVISIONED_DESCRIPTION},
    ),
    'publish_test_plan_draft': _operation(
        request=None,
        response='PublishedTestPlanView',
        permission=PERMISSIONS['publish_test_plan_draft'],
        # P2 cleanup (test-plan-publish-route-p2-cleanup, 2026-06-07) — the
        # verbatim publish-time audit snapshots are opt-in payload so the default
        # response stays lean (they are large/audit-only). Omitted/false →
        # scope_profile_json + generation_metadata_json are null in the response.
        query_params=[
            {
                'name': 'include_snapshots',
                'description': (
                    'Include the verbatim publish-time audit snapshots '
                    '(scope_profile_json + generation_metadata_json) in the '
                    'response. Omitted/false (default) returns them as null to '
                    'keep the response lean.'
                ),
                'schema': {'type': 'boolean', 'default': False},
            },
        ],
        # Publish wiring (test-plan-publish-route-wiring, 2026-06-07) — the draft
        # is materialized (condition_hash 확정) and transitioned to an immutable
        # PublishedTestPlan. Idempotent: re-publishing the same draft returns the
        # same plan_id (200). Error taxonomy documented for SDK clients (the 404
        # description is operation-specific — the generic default mentions
        # job/session/report ids which do not apply to a draft publish):
        error_responses={
            '403': 'AuthZ denied (missing test_plan:author).',
            '404': (
                'Draft not found, or it belongs to a different project '
                '(cross-project existence is hidden behind the project scope).'
            ),
            '409': (
                'Publish conflict — the draft is not DRAFT (e.g. archived), a '
                'concurrent transition won the race, or materialize found a '
                'duplicate measurement condition (ADR-0005 Decision A reject).'
            ),
            '422': 'Draft is unpublishable (no rows — an empty plan has no meaning).',
        },
    ),
    # Draft list + archive status transition (draft-list-status-transition,
    # 2026-06-03). list = read summary collection; archive = DRAFT→ARCHIVED.
    'list_test_plan_drafts': _operation(
        request=None,
        response='ListTestPlanDraftsResponse',
        permission=PERMISSIONS['list_test_plan_drafts'],
        query_params=[
            {
                'name': 'status',
                'description': (
                    'Filter by draft status (draft|archived). Omitted = all '
                    'statuses. An unknown value is a 422 (unprocessable).'
                ),
                'schema': {'type': 'string'},
            },
            {
                'name': 'limit',
                'description': (
                    'Maximum number of draft summaries per page. Omitted = '
                    'uncapped (single page, returns all matching drafts).'
                ),
                'schema': {'type': 'integer', 'minimum': 1},
            },
            # draft-list-keyset (2026-06-13). Keyset (seek) pagination — echo the
            # prior response's ``next_cursor`` to fetch the next page. Omit for
            # the first page. Never OFFSET (no skipped-row scan / page-depth cost).
            {
                'name': 'cursor',
                'description': (
                    'Opaque keyset cursor from a prior response\'s '
                    '``next_cursor``. Omit for the first page. A malformed cursor '
                    'is a 400.'
                ),
                'schema': {'type': 'string'},
            },
        ],
    ),
    'archive_test_plan_draft': _operation(
        request=None,
        response='TestPlanDraftView',
        permission=PERMISSIONS['archive_test_plan_draft'],
        error_responses={
            '409': (
                'Draft cannot be archived from its current status (e.g. '
                'published) or a concurrent transition conflicted. Re-archiving '
                'an already-archived draft is idempotent (200, not 409).'
            ),
        },
    ),
    # Published-plan list (G2, 2026-06-16). Authoritative source for plan
    # selection — replaces the frontend browser-local recency cache. An unknown
    # project yields 200 [] (no 404 for the collection). newest-first ordering.
    'list_published_test_plans': _operation(
        request=None,
        response='ListPublishedTestPlansResponse',
        permission=PERMISSIONS['list_published_test_plans'],
        query_params=[
            {
                'name': 'limit',
                'description': (
                    'Maximum number of published-plan summaries to return. '
                    'Omitted = all publications for the project (publications '
                    'per project are bounded), newest first. A supplied value '
                    'is clamped to [1, 1000].'
                ),
                'schema': {'type': 'integer', 'minimum': 1},
            },
        ],
    ),
    # Test-plan Excel import (Phase 4 L3, 2026-06-22). multipart/form-data upload
    # (``request`` is None — the body is a file, not a JSON schema). Returns the
    # import outcome (draft_id when rows were accepted + honest audit accounting +
    # blocking issues + observable exclusions).
    'import_test_plan': _operation(
        request=None,
        response='TestPlanImportResponse',
        permission=PERMISSIONS['import_test_plan'],
        multipart_request=True,
        error_responses={
            '422': (
                'Workbook unprocessable — the parsed rows fail the draft write '
                'gate (out-of-scope sub_family / capability taxonomy violation).'
            ),
        },
    ),
    # Test-plan draft Excel export (test-plan-draft-export, 2026-06-24). Binary
    # download (``binary_response`` reuses the octet-stream 200 seam proven by
    # stream_report_output_download — no schema-builder fork). ``request`` is None
    # (a GET read) and ``response`` is '' (the body is the binary workbook, not a
    # JSON schema ref). Operation-specific error taxonomy: 404 missing/cross-
    # project; 422 empty draft (no rows to export).
    'export_test_plan_draft': _operation(
        request=None,
        response='',
        permission=PERMISSIONS['export_test_plan_draft'],
        binary_response=True,
        binary_media_type=XLSX_MEDIA_TYPE,
        error_responses={
            '404': (
                'Draft not found, or it belongs to a different project '
                '(cross-project existence is hidden behind the project scope).'
            ),
            '422': 'Draft has no rows — an empty plan has nothing to export.',
        },
    ),
    # Current provider-neutral full-generation surface.  The router and
    # OpenAPI builder both consume this table, keeping status/header/query
    # behavior in one contract SSOT.
    'list_test_plan_generation_catalogue': _operation(
        request=None,
        response='TestPlanGenerationCatalogueResponse',
        permission=PERMISSIONS['list_test_plan_generation_catalogue'],
    ),
    'preview_test_plan_generation': _operation(
        request='TestPlanGenerationRequest',
        response='TestPlanGenerationPreviewResponse',
        permission=PERMISSIONS['preview_test_plan_generation'],
        request_required=True,
        error_responses={
            # Pre-existing contract defect fixed in passing (2026-08-27): the
            # handler has always been able to raise the three Generation*
            # conflicts, and its sibling ``submit`` declared 409 while this one
            # did not. Wording kept symmetric with that sibling.
            '409': (
                'Conflict — the production matrix cannot produce rows for this '
                'request, the preview is stale, or a staged WLAN request has '
                'missing, stale, or empty production input.'
            ),
            '503': REFERENCE_DATA_NOT_PROVISIONED_DESCRIPTION,
        },
    ),
    'submit_test_plan_generation': _operation(
        request='TestPlanGenerationSubmitRequest',
        response='TestPlanGenerationSubmittedResponse',
        permission=PERMISSIONS['submit_test_plan_generation'],
        header_params=[
            {
                'name': 'Idempotency-Key',
                'description': (
                    'Project-scoped retry key. Reusing it with a different '
                    'canonical request returns 409.'
                ),
                'required': True,
                'schema': {'type': 'string', 'minLength': 1},
            },
        ],
        success_status=202,
        request_required=True,
        error_responses={
            '409': (
                'Conflict — the preview is stale, the idempotency key was '
                'reused with a different request, or a staged WLAN request '
                'has missing, stale, or empty production input.'
            ),
            '503': REFERENCE_DATA_NOT_PROVISIONED_DESCRIPTION,
        },
    ),
    'get_test_plan_generation': _operation(
        request=None,
        response='TestPlanGenerationJobResponse',
        permission=PERMISSIONS['get_test_plan_generation'],
    ),
    'get_test_plan_generation_metadata': _operation(
        request=None,
        response='TestPlanGenerationMetadataResponse',
        permission=PERMISSIONS['get_test_plan_generation_metadata'],
    ),
    'list_test_plan_generation_rows': _operation(
        request=None,
        response='TestPlanGenerationRowPageResponse',
        permission=PERMISSIONS['list_test_plan_generation_rows'],
        query_params=[
            {
                'name': 'after_draft_row_id',
                'description': 'Seek position from the preceding page.',
                'schema': {'type': 'integer', 'minimum': 1},
            },
            {
                'name': 'limit',
                'description': (
                    'Requested page size. The server applies the configured '
                    'TestPlanGenerationLimits.page_size ceiling.'
                ),
                'schema': {'type': 'integer', 'minimum': 1},
            },
        ],
    ),
}
