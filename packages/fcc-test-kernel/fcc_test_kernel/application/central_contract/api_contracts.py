"""Platform read API contracts (FE-P0d, 2026-05-27).

Dependency-free DTO/route/schema SSOT for the central read surface
(``/platform/...``) — the FE-P2 project-coverage dashboard and FE-P3 claim-lock
UX read through this contract. Mirrors the ``application.headless.api_contracts``
shape (routes/operations/schemas/permissions/path-params/descriptions) so the
shared OpenAPI builder + codegen chain treat both surfaces uniformly.

These contracts can move to a future ``fcc-test-contracts`` package without
pulling FastAPI / Pydantic / SQL / psycopg with them.

Read surface ownership: coverage source = central ``coverage_by_condition_hash``;
claim source = central ``active_claims``; ``condition_hash`` is the local-propagated
identity (never recomputed centrally). ``{project_id}`` is the central project
uuid — the views key on the uuid ``project_id`` column.

DECOMPOSITION (2026-08-29) — 이 모듈은 **facade** 다: 조립과 재노출만 한다.
route/permission/schema/operation 선언은 ``surface_*`` 모듈이 갖고, 표면 횡단
어휘는 ``api_vocabulary``/``api_parameters``/``api_operation_factory``/
``api_request_validation`` 이 갖는다. 공개 이름은 **하나도 바뀌지 않았다** —
이 파일을 읽는 56개 import 사이트가 그대로 동작하는 것이 분해의 조건이었다.
경계가 「표 종류」가 아니라 「operation 표면」인 이유는
``.claude/exec-plans/completed/2026-08-29-central-contract-decomposition.md`` §1 이 갖는다.
"""
from __future__ import annotations

from typing import Literal, NotRequired, Required, TypedDict

from fcc_test_kernel.application.central_contract.api_parameters import (
    PLATFORM_API_PATH_PARAMS,
    PLATFORM_API_QUERY_PARAMS,
)
from fcc_test_kernel.application.central_contract.api_request_validation import (
    ProjectResultReferenceRequestUnprocessableError,
    validate_project_result_reference_request,
)
from fcc_test_kernel.application.central_contract.api_surfaces import merge_surface_table
from fcc_test_kernel.application.central_contract.api_vocabulary import (
    ARTIFACT_CUSTODY_FINDING_STATUSES,
    ARTIFACT_CUSTODY_REPORT_SCHEMA_VERSION,
    ARTIFACT_CUSTODY_STATUSES,
    CENTRAL_SYNC_READINESS_CODE_VALUES,
    CENTRAL_SYNC_READY_CODE,
    CHAMBER_RESULT_INGESTION_SCHEMA_VERSION,
    PLATFORM_API_COMPATIBILITY_MAJOR,
    PLATFORM_API_CONTRACT_VERSION,
    PLATFORM_API_PERMISSION_DESCRIPTIONS,
    PLATFORM_API_TITLE,
    PLATFORM_INTERNAL_RBAC_ROUTES,
    PLATFORM_NEXT_CURSOR_HEADER,
)

__all__ = [
    'PLATFORM_API_COMPATIBILITY_MAJOR',
    'PLATFORM_API_CONTRACT_VERSION',
    'PLATFORM_API_OPERATIONS',
    'PLATFORM_API_OPERATION_QUERY',
    'PLATFORM_API_OPERATION_QUERY_OVERRIDES',
    'PLATFORM_API_PATH_PARAMS',
    'PLATFORM_API_PERMISSIONS',
    'PLATFORM_API_PERMISSION_DESCRIPTIONS',
    'PLATFORM_API_QUERY_PARAMS',
    'PLATFORM_API_RESPONSE_HEADERS',
    'PLATFORM_API_ROUTES',
    'PLATFORM_INTERNAL_RBAC_ROUTES',
    'PLATFORM_API_SCHEMAS',
    'PLATFORM_API_TITLE',
    'PLATFORM_NEXT_CURSOR_HEADER',
    'CHAMBER_RESULT_INGESTION_SCHEMA_VERSION',
    'CENTRAL_SYNC_READINESS_CODE_VALUES',
    'CENTRAL_SYNC_READY_CODE',
    'ARTIFACT_CUSTODY_REPORT_SCHEMA_VERSION',
    'ARTIFACT_CUSTODY_STATUSES',
    'ARTIFACT_CUSTODY_FINDING_STATUSES',
    'ProjectResultReferenceRequestUnprocessableError',
    'validate_project_result_reference_request',
]


PLATFORM_API_ROUTES: dict[str, tuple[str, str]] = merge_surface_table('ROUTES')


# Permissions. FE-P2 (coverage) and FE-P3 read (claims) are reads of the central
# read model, gated by ``platform:read``. FE-P3-write (acquire/release) MUTATES the
# central claim ledger, so it is gated by a *separate* ``platform:claim`` token —
# a viewer can see coverage/locks without being able to acquire/release them. RBAC
# seed wiring (roles → token) is FE-P8 scope.
PLATFORM_API_PERMISSIONS: dict[str, str] = merge_surface_table('PERMISSIONS')


# operationId → accepted query params. Both read operations are keyset-paginated
# and accept the optional ``technology`` facet filter (coverage narrows the
# matrix; claims fetch only that technology's locks for the overlay).
PLATFORM_API_OPERATION_QUERY: dict[str, tuple[str, ...]] = merge_surface_table(
    'OPERATION_QUERY',
)


# ``status`` is shared by the project directory and sample inventory at the
# wire level, but the two resources have different closed sets. Keep the
# operation-specific narrowing here so generated clients cannot send the
# project-only ``completed`` value to a sample route.
PLATFORM_API_OPERATION_QUERY_OVERRIDES: dict[str, dict[str, dict]] = merge_surface_table(
    'OPERATION_QUERY_OVERRIDES',
)


# operationId → response headers. The paginated reads return the next-page cursor
# in PLATFORM_NEXT_CURSOR_HEADER (body stays a plain array).
PLATFORM_API_RESPONSE_HEADERS: dict[str, dict] = merge_surface_table('RESPONSE_HEADERS')


# Envelope shapes mirror the central view output columns (see
# docs/platform/central_db_schema.v1.json materialized_views/views). The read
# adapter contract test cross-checks every property against the view SELECT
# alias so a renamed column cannot silently drift the contract.
PLATFORM_API_SCHEMAS: dict[str, dict] = merge_surface_table('SCHEMAS')


class OperationSpec(TypedDict):
    """한 operation 의 계약. **필수/선택은 실측이 정한다** (2026-09-06, 80 operation 전수).

    ⚠️ 등장 수가 ``Required``/``NotRequired`` 를 정한다 — 셋만 80/80 이다::

        request                          80/80   필수 (⚠️ 42개가 ``None``)
        response                         80/80   필수
        permission                       80/80   필수
        error_responses                  64/80   선택 — 16개 operation 에 «없다»
        allowed_during_password_change    3/80   선택 (값 집합 ``{True}``)
        response_media_type               1/80   선택

    ⚠️ **간결하게 ``total=True`` 로 줄이지 마라. 그것은 정리가 아니라 회귀다.**
    선택 셋을 필수로 적으면 mypy 가 «없는 키가 있다고 보증»한다 — 아무것도 검사하지
    않는 것보다 나쁘다. 첨자 전환을 켜는 순간 답하는 것은 mypy 가 아니라 런타임이다.

    ■ ⚠️ 이 선언이 «보이려면» 배포판에 ``py.typed`` 가 있어야 한다

    PEP 561: 마커가 없으면 mypy 는 설치된 이 패키지를 «미타입»으로 보고 import 전체를
    ``Any`` 로 만든다. 실측 2026-09-06 — 소비 레인(platform)에서 같은 코드가::

        py.typed 없음   revealed: Any        · 잘못된 대입 0건 · 없는 키 0건  ← 아무것도 안 잡힌다
        py.typed 있음   revealed: OperationSpec · [assignment] · [typeddict-item]

    ⚠️ 그리고 platform 의 ``mypy.ini`` 가 ``ignore_missing_imports = True`` 라
    ``[import-untyped]`` 경고조차 안 뜬다 — **아무 신호 없이 0건 검사된다.**
    그래서 이 파일과 ``py.typed`` 는 **같은 판에 나가야 한다.**

    ■ ⚠️ 소비 쪽에서 mypy 가 «무엇을 검사하고 무엇을 안 하는지» (실측)

    ================================  ==========================  ==================
    형태                              mypy                        런타임
    ================================  ==========================  ==================
    ``spec['permission']``            타입·키 이름 «둘 다» 검사   안전 (80/80)
    ``spec['response_media_type']``   **아무 말도 안 한다**       ★ KeyError 79/80
    ``'x' in spec`` 뒤 ``spec['x']``  좁혀서 검사 (``str``)       안전
    ``spec.get('오타')``              **아무 말도 안 한다**       조용히 ``None``/기본값
    ================================  ==========================  ==================

    ⚠️ **둘째 줄이 함정이다.** 「``.get`` 을 첨자로 바꾸면 검사된다」는 ``NotRequired``
    키에 대해 **거짓**이고, 게다가 런타임 지뢰를 심는다. 선택 키는 ``in`` 가드를 거쳐
    첨자로 읽어라 — 그것만이 검사되면서 안전한 유일한 형태다.
    ⚠️ ``.get`` 은 키 «이름»을 전혀 안 본다. 오타는 영원히 조용하다.
    """

    request: Required[str | None]
    response: Required[str]
    permission: Required[str]
    error_responses: NotRequired[dict[str, str]]
    allowed_during_password_change: NotRequired[Literal[True]]
    response_media_type: NotRequired[str]


PLATFORM_API_OPERATIONS: dict[str, OperationSpec] = merge_surface_table('OPERATIONS')
