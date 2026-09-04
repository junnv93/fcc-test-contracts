"""OpenAPI 3.1 schema SSOT for the Headless / Platform API surface.

⚠️ **이 모듈은 2026-09-04 에 모노레포에서 여기로 이사했다, 그리고 그 이사가 수리다.**
``check_headless_provider_registry.py`` 가 2026-08-31 에 같은 이유로 이사한 것과 같은
형태다(KC 판정문 §6.4: *"체커가 contracts 로 이사 — 그 move 가 fix 다"*).

무엇이 문제였나 — 이 조립기가 필요로 하는 것은 **전부 이 레인 소유**다:
``openapi_schema_builder`` (변환) · ``api_contracts`` 의 표 아홉 · ``api_error_codes``.
모노레포 의존은 ``TYPE_CHECKING`` 아래 타입 힌트 하나뿐이었고 런타임 의존은 **0** 이었다.
그런데 **발행 진입점만 모노레포에 남아** 있어서, SSOT 와 변환기를 가진 레인이 **자기
발행물을 재생성하지 못했다.**

그 결과가 실측으로 드러났다(2026-09-04): 계약이 ``v0.1.17`` 인데 모노레포는 ``v0.1.12``
를 핀하고, ``headless-api.openapi.json`` **다섯 사본**(모노레포 1 · 계약 2 · 플랫폼 2)이
byte 동일하게 **다 같이 낡아** 있었다. 사본이 서로 어긋난 것이 아니라 **생산자가 SSOT 를
따라가지 못한 것**이다.

⚠️ 모노레포의 ``src/application/headless/api_schema.py`` 는 이제 **삭제 대기 중복**이다.
그 레포가 계약 핀을 올리는 날 이 모듈을 import 하고 자기 사본을 지운다.

Dependency-free 모듈. 외부 FastAPI app 없이도 ``HEADLESS_API_ROUTES`` +
``HEADLESS_API_OPERATIONS`` + ``HEADLESS_API_SCHEMAS`` + ``HEADLESS_API_PATH_PARAMS``
+ ``HEADLESS_API_PERMISSION_DESCRIPTIONS`` SSOT (모두 ``api_contracts.py`` 정의)
로부터 OpenAPI 3.1 document 를 결정론적으로 생성한다.

설계 원칙 (F-2-D3 ``application.session.api_schema`` 패턴 차용):

- 모든 schema 값은 ``api_contracts.py`` 상수에서 파생 (route/operation/schema/
  path-param/permission-description literal 중복 0).
- AuthZ 헤더 이름은 ``HttpAuthConfig.auth_permissions_header`` SSOT 경유
  (caller 가 ``HeadlessApiConfig`` 를 주입; 기본은 SSOT default).
- ``/headless/sessions/{session_id}/reports`` (POST submit_report_request) 와
  ``/headless/reports/{request_id}/outputs`` (GET list_report_outputs) 의 경로
  구분은 ``HEADLESS_API_ROUTES`` SSOT 그대로 보존 — 생성 vs 산출물 구분 유지.
- Schema artifact (``docs/api/headless-api.openapi.json``) 와
  ``build_headless_openapi_schema(config)`` 결과가 byte-identical 해야 한다 (CI
  drift gate — ``TestHeadlessApiSchemaSsot`` invariant).

OpenAPI 3.1 specific notes:

- ``components.schemas`` 는 ``HEADLESS_API_SCHEMAS`` 를 그대로 풀어내되 내부
  ``$ref`` 경로 ``#/schemas/`` → ``#/components/schemas/`` 로 정규화.
- ``nullable: true`` (Swagger 2 잔재) 는 OpenAPI 3.1 ``["type", "null"]`` 로
  정규화.
- 매 operation 은 ``x-fcc-permission`` extension 으로 ``HEADLESS_API_PERMISSIONS``
  토큰을 노출 — frontend client/SDK 가 401/403 분기에 사용.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol

from fcc_test_contracts.common.api_error_codes import ApiSurface, surface_error_codes
from fcc_test_contracts.common.openapi_schema_builder import (
    apply_operation_error_responses,
    build_components_schemas,
    iter_path_param_names,
    multipart_file_request_body,
    problem_details_component_schemas,
    problem_error_response,
)
from fcc_test_contracts.headless.api_contracts import (
    API_CONTRACT_VERSION,
    API_COMPATIBILITY_MAJOR,
    DEFAULT_PROVIDER_METADATA,
    HEADLESS_API_OPERATIONS,
    HEADLESS_API_PATH_PARAMS,
    HEADLESS_API_PERMISSIONS,
    HEADLESS_API_PERMISSION_DESCRIPTIONS,
    HEADLESS_API_ROUTES,
    HEADLESS_API_SCHEMAS,
)

#: ⚠️ **구조적 타입이지 특정 클래스가 아니다.** 옮기기 전 이 자리는 모노레포의
#: ``application.headless.runtime_config.HeadlessApiConfig`` 를 ``TYPE_CHECKING``
#: 아래에서 가져왔다 — 런타임 의존은 0 이었고, 실제로 쓰이는 것은
#: ``config.auth.auth_permissions_header`` 하나다. 그 하나를 이름으로 적는 것이
#: 클래스를 빌려오는 것보다 정직하다: 이 레인은 그 클래스를 알 필요가 없고, 알면
#: 바닥 레인이 소비자를 아는 방향이 된다.
class _HasAuthPermissionsHeader(Protocol):  # pragma: no cover — 타입 전용
    auth: Any


__all__ = [
    'HEADLESS_API_TITLE',
    'build_headless_openapi_schema',
    'iter_path_param_names',
]


HEADLESS_API_TITLE: str = 'FCC Headless API'


# Per-operation natural-language summary derived from operation id. Keeping
# these here (not in api_contracts.py) preserves api_contracts.py as a
# dependency-free *machine* contract and isolates human-readable copy for SPA
# documentation widgets. Coverage is sealed by invariant
# ``test_operation_summary_covers_every_operation``.
_OPERATION_SUMMARIES: dict[str, str] = {
    'health_check': 'Liveness probe — no AuthZ required.',
    'headless_status': 'Aggregate measurement job + worker + report-automation snapshot.',
    'provider_capabilities': 'Provider capability descriptor (job/technology/artifact types).',
    'provider_ui_descriptor': 'Provider-owned UI descriptor (test plan / equipment / reference / correction schema-first render contract).',
    'list_measurement_jobs': 'List measurement jobs filtered by status.',
    'get_measurement_job': 'Fetch a single measurement job by id.',
    'submit_measurement_job': 'Submit a measurement job to the headless queue.',
    'stop_measurement_job': 'Request graceful stop for a running measurement job.',
    'list_session_results': 'List measurement result envelopes for a session.',
    'list_session_artifacts': 'List artifact metadata for a session (plots / screenshots / traces).',
    'list_session_attempts': 'List append-only measurement attempt history for a session (per-condition results / margin / verdict / provenance).',
    'export_session_results': (
        'Download the session\'s measurement results as an .xlsx workbook. The '
        'format is owned by this service (a versioned template manifest), not by '
        'a workbook the tester opened: the response is a render of the stored '
        'rows, so verdicts, margins and units are reproduced verbatim and never '
        'recomputed. 422 when the session measured nothing.'
    ),
    'submit_report_request': (
        'Enqueue a report-automation request for the session — creates a request '
        '(distinct from list_report_outputs which lists generated outputs).'
    ),
    'get_report_preflight': (
        'Dry-run a report preflight for a measurement session — per-technology '
        'completeness + data-quality warnings before docx generation (read-only, '
        'no side effects, advisory not blocking).'
    ),
    'get_report_request': 'Fetch a single report-automation request by id.',
    'list_report_outputs': (
        'List generated output files for a report-automation request — '
        'distinct from submit_report_request creation route.'
    ),
    'create_report_output_download': (
        'Issue a signed, short-TTL download grant for one report output '
        '(self-authorizing URL — browser navigation needs no RBAC header).'
    ),
    'stream_report_output_download': (
        'Stream a report output file for a valid signed download token '
        '(token-authorized; no RBAC header — presigned model).'
    ),
    'report_automation_stats': 'Report automation queue counts + oldest-queued request id.',
    'cancel_report_automation_request': 'Cancel a queued/running report-automation request.',
    'headless_api_contract': 'Self-describing API contract document (routes/schemas/permissions).',
    'create_test_plan_draft': (
        'Create a manually-authored empty test-plan draft. The current '
        'generation operations own generated rows; Excel import remains a '
        'separate authoring surface (project_id boundary enforced).'
    ),
    'get_test_plan_draft': 'Fetch a test-plan draft with its rows (stable draft_row_id handles).',
    'add_test_plan_draft_row': 'Append a manual row to a draft (returns the new draft_row_id handle).',
    'remove_test_plan_draft_row': (
        'Remove a draft row by its stable draft_row_id handle (idempotent; '
        'generated or manual).'
    ),
    'replace_test_plan_draft_rows': (
        'Replace ALL rows in a draft with a new set in one transaction (bulk '
        'edit) — the editor sends the full desired row set; a partial failure '
        'rolls back so rows are never lost. 404 missing/cross-project; 409 '
        'not-DRAFT (terminal row freeze).'
    ),
    'validate_test_plan_draft': (
        'Re-validate a draft against its scope snapshot + capability matrix — '
        'returns issues (errors/warnings are body data, HTTP 200).'
    ),
    'publish_test_plan_draft': (
        'Publish a draft — materialize condition_hash rows + atomic CAS publish '
        '(DRAFT→PUBLISHED), returning 200 PublishedTestPlanView. Idempotent: '
        're-publishing an already-published draft returns the existing '
        'publication. 404 missing/cross-project; 422 empty draft; 409 not-DRAFT '
        '(e.g. archived) / duplicate measurement condition / concurrent '
        'transition race.'
    ),
    'list_test_plan_drafts': (
        'List a project\'s draft summaries (metadata + row_count, no rows) '
        'ordered created_at DESC, draft_id ASC. Optional status filter; an '
        'unknown project yields an empty list (200, not 404).'
    ),
    'archive_test_plan_draft': (
        'Archive a draft (DRAFT→ARCHIVED, terminal). Idempotent re-archive '
        'returns 200; archiving a non-draft (e.g. published) returns 409.'
    ),
    'list_published_test_plans': (
        'List a project\'s published-plan summaries (identity + row_count + '
        'provenance, no rows) ordered published_at DESC, plan_id ASC — the '
        'authoritative source for plan selection. Optional limit clamped to '
        '[1, 1000]; an unknown project yields an empty list (200, not 404).'
    ),
    'get_published_test_plan': (
        'Read one immutable published plan by its opaque plan_id, rows included '
        '(condition_hash + the display fields the Test Plan cells are rendered '
        'from). The chamber-facing counterpart of the publish response — a node '
        'measuring a browser-authored plan has no local copy to seed from. Not '
        'project-scoped: the caller is a machine principal with no project '
        'membership. 404 when no publication carries that id.'
    ),
    'import_test_plan': (
        'Import a test-plan from an uploaded Excel workbook (multipart/form-data) '
        '— parse → capability-map → IMPORTED draft, returning the import outcome '
        '(draft_id when rows were accepted + honest audit accounting + blocking '
        'issues + observable exclusions).'
    ),
    'export_test_plan_draft': (
        'Download a test-plan draft as an Excel (.xlsx) workbook — an idempotent '
        'read of an existing draft (application/octet-stream attachment). 404 '
        'missing/cross-project; 422 empty draft (no rows to export).'
    ),
    'list_test_plan_generation_catalogue': (
        'List the provider-neutral generation catalogue derived from the '
        'registered provider/policy vocabulary.'
    ),
    'preview_test_plan_generation': (
        'Preview a full test-plan generation: bounded production estimate plus '
        'a separate representative sample and freshness fingerprint.'
    ),
    'submit_test_plan_generation': (
        'Queue a durable full test-plan generation job. Always returns 202 and '
        'requires the preview proof plus a project-scoped Idempotency-Key.'
    ),
    'get_test_plan_generation': (
        'Read full-generation job status and the generated draft handle without '
        'materializing all rows.'
    ),
    'get_test_plan_generation_metadata': (
        'Read the validated, immutable generation provenance envelope for a draft.'
    ),
    'list_test_plan_generation_rows': (
        'Read generated draft rows through stable-id keyset paging; OFFSET is not used.'
    ),
}


def _operation_summary(name: str) -> str:
    return _OPERATION_SUMMARIES.get(name, name.replace('_', ' '))


def _ref_object(schema_name: str) -> dict[str, Any]:
    return {'$ref': f'#/components/schemas/{schema_name}'}


def _path_parameters_for(path: str) -> list[dict[str, Any]]:
    """Extract OpenAPI path parameter descriptors from ``HEADLESS_API_PATH_PARAMS``.

    Every ``{name}`` placeholder in ``path`` must have a matching SSOT entry
    in ``HEADLESS_API_PATH_PARAMS``; the missing case raises immediately so
    schema generation fails loudly (vs silently emitting an integer guess).
    """
    parameters: list[dict[str, Any]] = []
    for name in iter_path_param_names(path):
        if name not in HEADLESS_API_PATH_PARAMS:
            raise KeyError(
                f"Path parameter '{name}' (in '{path}') has no entry in "
                f"HEADLESS_API_PATH_PARAMS — declare it in "
                f"`application.headless.api_contracts` SSOT."
            )
        parameters.append({
            'name': name,
            'in': 'path',
            'required': True,
            'schema': dict(HEADLESS_API_PATH_PARAMS[name]),
        })
    return parameters


def _query_parameters_for(name: str) -> list[dict[str, Any]]:
    """Emit ``in: query`` parameters from the operation's ``query_params`` SSOT.

    Only operations that declare ``query_params`` in ``HEADLESS_API_OPERATIONS``
    contribute any — every other operation produces an empty list so its
    serialized schema stays byte-identical (the artifact drift gate relies on
    this). Query params are optional by REST convention (``required: False``).
    """
    declared = HEADLESS_API_OPERATIONS[name].get('query_params')
    if not declared:
        return []
    parameters: list[dict[str, Any]] = []
    for param in declared:
        entry: dict[str, Any] = {
            'name': param['name'],
            'in': 'query',
            'required': False,
        }
        if param.get('description'):
            entry['description'] = param['description']
        entry['schema'] = dict(param['schema'])
        parameters.append(entry)
    return parameters


def _header_parameters_for(name: str) -> list[dict[str, Any]]:
    """Emit request headers declared by the operation contract SSOT."""
    declared = HEADLESS_API_OPERATIONS[name].get('header_params')
    if not declared:
        return []
    parameters: list[dict[str, Any]] = []
    for param in declared:
        entry: dict[str, Any] = {
            'name': param['name'],
            'in': 'header',
            'required': bool(param.get('required', False)),
        }
        if param.get('description'):
            entry['description'] = param['description']
        entry['schema'] = dict(param['schema'])
        parameters.append(entry)
    return parameters


def _build_responses_for(name: str) -> dict[str, Any]:
    operation = HEADLESS_API_OPERATIONS[name]
    if operation.get('binary_response'):
        # File download — OpenAPI 3.1 binary body, not JSON. The media type comes
        # from the operation when it declares one (2026-08-11) so the document
        # states what the route actually sends; operations that declare nothing
        # keep the historical octet-stream default byte-identical.
        ok_content = {
            operation.get('binary_media_type', 'application/octet-stream'): {
                'schema': {'type': 'string', 'format': 'binary'},
            },
        }
    else:
        response_schema_name = operation.get('response')
        if response_schema_name and response_schema_name in HEADLESS_API_SCHEMAS:
            ok_schema: dict[str, Any] = _ref_object(response_schema_name)
        else:
            ok_schema = {'type': 'object'}
        ok_content = {'application/json': {'schema': ok_schema}}
    # RFC 9457 (B1): default error responses advertise the shared problem+json
    # ProblemDetails body. Descriptions are byte-preserved; operations may still
    # override a code via ``apply_operation_error_responses`` below.
    success_status = str(operation.get('success_status', 200))
    responses: dict[str, Any] = {
        success_status: {
            'description': 'OK',
            'content': ok_content,
        },
        '400': problem_error_response('Contract validation failed (ApiContractError).'),
        '403': problem_error_response('AuthZ denied (missing required permission).'),
        '404': problem_error_response('Resource not found (missing job/session/report id).'),
        # 2026-08-27 — true of every operation once the boundary stopped calling
        # unclassified exceptions "not found". Leaving it out would keep the
        # artifact asserting that 404 is the worst a client can see, which is the
        # same lie the code just stopped telling.
        '500': problem_error_response('Unclassified server error (INTERNAL_ERROR).'),
    }
    # FE-P6 (2026-05-29): operation-specific error responses (e.g. the download
    # stream's 409 integrity-conflict / 410 expired-grant) via the shared SSOT
    # merge helper — the SAME mechanism the platform builder uses (no divergence).
    # Operations without ``error_responses`` keep the byte-identical default set.
    return apply_operation_error_responses(responses, operation)


def _build_request_body_for(name: str) -> dict[str, Any] | None:
    operation = HEADLESS_API_OPERATIONS[name]
    # Phase 4 L3 (2026-06-22): a multipart/form-data file upload instead of a JSON
    # body. 2026-08-20 — the idiom itself moved to
    # ``application/common/openapi_schema_builder.multipart_file_request_body``
    # when the session workbook upload became its third caller; the emitted
    # document is byte-identical (sealed by the artifact byte-identity tests).
    if operation.get('multipart_request'):
        return multipart_file_request_body()
    request_schema_name = operation.get('request')
    if not request_schema_name or request_schema_name not in HEADLESS_API_SCHEMAS:
        return None
    return {
        'required': bool(operation.get('request_required', False)),
        'content': {
            'application/json': {
                'schema': _ref_object(request_schema_name),
            },
        },
    }


def _http_operation_schema(name: str, method: str, path: str) -> dict[str, Any]:
    operation_doc: dict[str, Any] = {
        'operationId': name,
        'summary': _operation_summary(name),
        'tags': ['headless'],
        'x-fcc-permission': HEADLESS_API_OPERATIONS[name]['permission'],
        'responses': _build_responses_for(name),
    }
    parameters = _path_parameters_for(path)
    parameters = parameters + _query_parameters_for(name) + _header_parameters_for(name)
    if parameters:
        operation_doc['parameters'] = parameters
    request_body = _build_request_body_for(name)
    if request_body is not None:
        operation_doc['requestBody'] = request_body
    return {method.lower(): operation_doc}


def _resolve_permissions_header(config: Optional[_HasAuthPermissionsHeader]) -> str:
    """Resolve the ``x-fcc-permissions`` HTTP header name from the SSOT chain.

    ``HttpAuthConfig`` (``application.common.auth_config``) owns the field and
    its default — schema generation MUST NOT redeclare it. When ``config`` is
    ``None`` (e.g. discovery callers that don't carry a HeadlessApiConfig) we
    fall back to ``HttpAuthConfig()`` directly — the same dataclass that the
    runtime config holds under ``config.auth`` — so the default value flows
    from exactly one definition site.
    """
    if config is not None:
        return config.auth.auth_permissions_header
    # Direct HttpAuthConfig default — avoids constructing a HeadlessApiConfig
    # which requires environment-specific fields (db_path) unrelated to schema.
    from fcc_test_contracts.common.auth_config import HttpAuthConfig
    return HttpAuthConfig().auth_permissions_header


def build_headless_openapi_schema(
    config: Optional[_HasAuthPermissionsHeader] = None,
) -> dict[str, Any]:
    """Build an OpenAPI 3.1 schema for the Headless / Platform API surface.

    The schema is derived from ``HEADLESS_API_OPERATIONS`` + ``HEADLESS_API_ROUTES``
    + ``HEADLESS_API_PATH_PARAMS`` + ``HEADLESS_API_PERMISSION_DESCRIPTIONS`` —
    no hand-curated path table, parameter-type heuristic, or duplicated
    permission descriptor copy. Permissions/operationIds match
    ``api_contracts.py`` SSOT exactly.

    AuthZ header name is sourced from ``config.auth.auth_permissions_header``
    (``HttpAuthConfig`` SSOT) so a deployment that overrides the header propagates
    through the schema artifact + generated TS client without code duplication.

    The two report-related routes preserve their SSOT distinction:

    - ``POST /headless/sessions/{session_id}/reports`` (``submit_report_request``)
      — creates a new report-automation request.
    - ``GET /headless/reports/{request_id}/outputs`` (``list_report_outputs``)
      — lists generated outputs for an existing request.

    OpenAPI 3.1 paths object is constructed in route declaration order so the
    serialized artifact has stable diff semantics.
    """
    paths: dict[str, dict[str, Any]] = {}

    for name, (method, path) in HEADLESS_API_ROUTES.items():
        paths.setdefault(path, {}).update(_http_operation_schema(name, method, path))

    permissions_header = _resolve_permissions_header(config)

    return {
        'openapi': '3.1.0',
        'info': {
            'title': HEADLESS_API_TITLE,
            'version': API_CONTRACT_VERSION,
            'x-fcc-api-compatibility-major': API_COMPATIBILITY_MAJOR,
            'x-fcc-provider': dict(DEFAULT_PROVIDER_METADATA),
            'description': (
                'FCC Headless / Platform measurement + reporting control surface. '
                'Operations group: provider capabilities, measurement job lifecycle, '
                'session result/artifact read model, report-automation request lifecycle. '
                'Authorization uses trusted-header permission tokens (see '
                '``components.securitySchemes.FccHeadlessPermissions``).'
            ),
        },
        'paths': paths,
        'components': {
            # RFC 9457 (B1): merge the shared ProblemDetails + ErrorCode schemas
            # so every error response's $ref resolves and the generated TS bundle
            # carries the machine-readable code enum.
            #
            # Scoped like the platform surface (2026-08-13). This call site used
            # to omit `codes`, and the (now-removed) default published only
            # SHARED_ERROR_CODES — the codes belonging to *no* surface in
            # particular — so a code scoped **to** this surface was the one thing
            # its own artifact could not name. SESSION_RESULTS_EMPTY was exactly
            # that: emitted by export_session_results, described in its 422 prose,
            # and absent from the enum, so no generated client could narrow on it.
            # The sibling call site guarded the mirror direction ("must not leak
            # into the headless artifact") and this one was left at the default.
            # `codes` is now a mandatory argument (openapi_schema_builder.py) so
            # a future surface cannot repeat this by omission, and
            # tests/test_error_code_publication_axis_invariants.py seals the
            # emittable ⊆ published ⊆ scoped axis for every ApiSurface member.
            'schemas': build_components_schemas({
                **problem_details_component_schemas(
                    surface_error_codes(ApiSurface.HEADLESS)
                ),
                **HEADLESS_API_SCHEMAS,
            }),
            'securitySchemes': {
                'FccHeadlessPermissions': {
                    'type': 'apiKey',
                    'in': 'header',
                    'name': permissions_header,
                    'description': (
                        'Comma-separated permission tokens. See the '
                        '``x-fcc-permissions`` catalog for available values.'
                    ),
                },
            },
            'x-fcc-permissions': {
                permission: HEADLESS_API_PERMISSION_DESCRIPTIONS[permission]
                for permission in sorted(set(HEADLESS_API_PERMISSIONS.values()))
            },
        },
    }
