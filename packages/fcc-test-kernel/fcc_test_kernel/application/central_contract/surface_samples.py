"""중앙 플랫폼 계약 — 시료 인벤토리 (프로젝트 스코프 · 전역 · system 내보내기).

``api_contracts`` facade 가 이 모듈의 표를 병합해 ``PLATFORM_API_*`` 로 재노출한다.
모듈 경계는 **표 종류가 아니라 operation 표면**이다 — git 이력 실측에서 계약 변경
커밋의 92%(52 중 48)가 정확히 한 표면만 만졌고, 표 종류로 자르면 엔드포인트 하나
추가가 항상 다섯 표를 동시에 만진다(네 표가 같은 operationId 키로 병렬 배열돼 있다).
"""
from __future__ import annotations

from fcc_test_kernel.application.central_contract.api_operation_factory import (
    _PROJECT_NOT_FOUND_404,
    _operation,
)
from fcc_test_kernel.application.central_contract.api_vocabulary import (
    _SAMPLE_INTAKE_PROPERTIES,
    _SAMPLE_STATUS_VALUES,
    _SAMPLE_TEXT_PROPERTIES,
)
from fcc_test_kernel.domain.models.sample_inventory import (
    CUSTODY_EVENT_FIELDS,
    SampleCustodyEventType,
)

# PM 축 반입/반출 사건의 필드 어휘 (ADR-0002). `api_vocabulary` 가 아니라 여기 사는
# 이유는 이 모듈의 경계 규칙 그대로다 — **표 종류가 아니라 operation 표면**이 경계이고,
# custody 는 시료 표면 하나만 쓴다. 위의 셋처럼 도메인 튜플에서 파생하므로 도메인과
# 계약이 갈라질 수 없다.
#
# event_type 만 enum 으로 좁힌다: 닫힌 어휘이고 보유 상태 계산의 입력이라, 자유 문자열을
# 허용하면 계산이 오류 없이 조용히 틀린다.
_SAMPLE_CUSTODY_EVENT_TYPE_VALUES = [
    event_type.value for event_type in SampleCustodyEventType
]
_SAMPLE_CUSTODY_PROPERTIES = {
    field: (
        {'type': 'string', 'enum': _SAMPLE_CUSTODY_EVENT_TYPE_VALUES}
        if field == 'event_type'
        else {'type': 'string', 'nullable': True}
    )
    for field in CUSTODY_EVENT_FIELDS
}

#: 이 모듈이 소유하는 route path prefix. 분할은 **선언이 아니라 판정 대상**이다 —
#: ``tests/test_central_contract_decomposition_axis.py`` 가 prefix 집합이 쌍마다
#: 서로소이고 ``PLATFORM_API_ROUTES`` 의 모든 경로를 덮는지, 그리고 각 operation 이
#: 자기 경로의 **최장 일치** prefix 를 소유한 모듈에 물리적으로 선언돼 있는지 파생
#: 판정한다. 새 엔드포인트가 어느 모듈로 가야 하는지 사람이 기억하지 않는다.
SURFACE_PREFIXES: tuple[str, ...] = (
    '/platform/projects/{project_id}/samples',
    '/platform/projects/{project_id}/sample-inventory',
    '/platform/sample-inventory',
    '/platform/system/sample-inventory',
)


ROUTES: dict[str, tuple[str, str]] = {
    # Web-owned sample inventory. All field/status changes are server-side CRUD;
    # list/export share the same project/team/status/as-of filter vocabulary.
    'list_sample_inventory': ('GET', '/platform/sample-inventory'),
    'create_sample': ('POST', '/platform/projects/{project_id}/samples'),
    'get_sample': ('GET', '/platform/projects/{project_id}/samples/{sample_id}'),
    'patch_sample': ('PATCH', '/platform/projects/{project_id}/samples/{sample_id}'),
    'change_sample_status': (
        'POST', '/platform/projects/{project_id}/samples/{sample_id}/status',
    ),
    'delete_sample': ('DELETE', '/platform/projects/{project_id}/samples/{sample_id}'),
    'hard_delete_sample': ('DELETE', '/platform/system/sample-inventory/{sample_id}'),
    'list_sample_history': (
        'GET', '/platform/projects/{project_id}/samples/{sample_id}/history',
    ),
    # 시험 실무자 축의 1:N 입고 이력. 시료 상세는 `latest_intake` 한 건만 실어 왔고,
    # 「반출됐다 반입되면 다시 기록」한 과거 행들을 읽을 창이 없었다 (ADR-0002).
    'list_sample_intakes': (
        'GET', '/platform/projects/{project_id}/samples/{sample_id}/intakes',
    ),
    # PM 축의 반입/반출 사건 (ADR-0002). 정정 수단은 PATCH 가 아니라 DELETE 다 —
    # 수정은 흔적 없이 과거를 바꾸지만 삭제는 보이고, 다시 적으면 새 행위자가 붙는다.
    'list_sample_custody_events': (
        'GET', '/platform/projects/{project_id}/samples/{sample_id}/custody-events',
    ),
    'append_sample_custody_event': (
        'POST', '/platform/projects/{project_id}/samples/{sample_id}/custody-events',
    ),
    'delete_sample_custody_event': (
        'DELETE',
        '/platform/projects/{project_id}/samples/{sample_id}/custody-events/{event_id}',
    ),
    'export_sample_inventory': (
        'GET', '/platform/projects/{project_id}/sample-inventory/exports/{template}',
    ),
}


PERMISSIONS: dict[str, str] = {
    # Web-owned sample inventory. PM and test engineers deliberately share one
    # whole-record write permission; the former PM/RF upload split is retired.
    'list_sample_inventory': 'platform:read',
    'create_sample': 'platform:sample-write',
    'get_sample': 'platform:read',
    'patch_sample': 'platform:sample-write',
    'change_sample_status': 'platform:sample-write',
    'delete_sample': 'platform:sample-write',
    'hard_delete_sample': 'platform:sample-hard-delete',
    'list_sample_history': 'platform:read',
    'list_sample_intakes': 'platform:read',
    'list_sample_custody_events': 'platform:read',
    'append_sample_custody_event': 'platform:sample-write',
    'delete_sample_custody_event': 'platform:sample-write',
    'export_sample_inventory': 'platform:read',
}


OPERATION_QUERY: dict[str, tuple[str, ...]] = {
    'list_sample_inventory': (
        'project_id', 'team', 'status', 'as_of', 'after', 'limit', 'include_deleted',
    ),
    'get_sample': ('as_of',),
    'list_sample_history': ('after', 'limit'),
    'export_sample_inventory': ('team', 'status', 'as_of', 'include_deleted'),
}


OPERATION_QUERY_OVERRIDES: dict[str, dict[str, dict]] = {
    'list_sample_inventory': {
        'status': {'type': 'string', 'enum': [*_SAMPLE_STATUS_VALUES, 'all']},
    },
    'export_sample_inventory': {
        'status': {'type': 'string', 'enum': [*_SAMPLE_STATUS_VALUES, 'all']},
    },
}


SCHEMAS: dict[str, dict] = {
    # Web sample inventory CRUD. Field vocabulary is derived from the pure domain
    # model so PM, tester, API, and export cannot grow separate column lists.
    'SampleInventoryItem': {
        'type': 'object',
        'required': [
            'sample_id', 'project_id', 'status', 'row_version',
            'latest_intake', 'intake_count',
        ],
        'properties': {
            'sample_id': {'type': 'string', 'format': 'uuid'},
            'project_id': {'type': 'string', 'format': 'uuid'},
            **_SAMPLE_TEXT_PROPERTIES,
            'status': {'type': 'string', 'enum': _SAMPLE_STATUS_VALUES},
            'row_version': {'type': 'integer', 'minimum': 1},
            'deleted_at': {'type': 'string', 'nullable': True},
            'deleted_by': {'type': 'string', 'nullable': True},
            'latest_intake': {
                'anyOf': [
                    {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'string', 'nullable': True},
                            'sample_id': {'type': 'string', 'nullable': True},
                            **_SAMPLE_INTAKE_PROPERTIES,
                        },
                        'additionalProperties': False,
                    },
                    {'type': 'null'},
                ],
            },
            'intake_count': {'type': 'integer', 'minimum': 0},
            # 파생값 — 사람이 편집하지 않으므로 create/patch 요청에는 없다.
            # 규칙(가장 최근 사건이 received 면 보유 중)은 커널의 custody_state()
            # 한 자리에만 산다. 클라이언트는 판정하지 않고 결과를 읽는다.
            'custody_state': {
                'type': 'string', 'nullable': True,
                'enum': ['in_custody', 'released', None],
            },
            'latest_custody_occurred_on': {'type': 'string', 'nullable': True},
            'custody_event_count': {'type': 'integer', 'minimum': 0},
            'created_at': {'type': 'string', 'nullable': True},
            'updated_at': {'type': 'string', 'nullable': True},
        },
        'additionalProperties': False,
    },
    'SampleInventoryPage': {
        'type': 'object',
        'required': ['items', 'next_cursor', 'filters'],
        'properties': {
            'items': {
                'type': 'array',
                'items': {'$ref': '#/schemas/SampleInventoryItem'},
            },
            'next_cursor': {'type': 'string', 'nullable': True},
            'as_of': {'type': 'string', 'nullable': True},
            'filters': {'type': 'object', 'additionalProperties': True},
        },
        'additionalProperties': False,
    },
    'SampleCreateRequest': {
        'type': 'object',
        'required': ['sample_number'],
        'properties': {
            **_SAMPLE_TEXT_PROPERTIES,
            'latest_intake': {
                'type': 'object',
                'properties': _SAMPLE_INTAKE_PROPERTIES,
                'additionalProperties': False,
            },
        },
        'additionalProperties': False,
    },
    'SamplePatchRequest': {
        'type': 'object',
        'required': ['expected_version'],
        'properties': {
            'expected_version': {'type': 'integer', 'minimum': 1},
            **_SAMPLE_TEXT_PROPERTIES,
            'latest_intake': {
                'type': 'object',
                'properties': _SAMPLE_INTAKE_PROPERTIES,
                'additionalProperties': False,
            },
        },
        'additionalProperties': False,
    },
    'SampleStatusRequest': {
        'type': 'object',
        'required': ['status', 'expected_version'],
        'properties': {
            'status': {'type': 'string', 'enum': _SAMPLE_STATUS_VALUES},
            'expected_version': {'type': 'integer', 'minimum': 1},
        },
        'additionalProperties': False,
    },
    'SampleVersionRequest': {
        'type': 'object',
        'required': ['expected_version'],
        'properties': {
            'expected_version': {'type': 'integer', 'minimum': 1},
        },
        'additionalProperties': False,
    },
    'SampleRevisionEnvelope': {
        'type': 'object',
        'required': [
            'revision_id', 'sample_id', 'project_id', 'revision_number',
            'event_type', 'snapshot', 'changed_fields', 'actor_subject',
            'occurred_at',
        ],
        'properties': {
            'revision_id': {'type': 'string', 'format': 'uuid'},
            'sample_id': {'type': 'string', 'format': 'uuid'},
            'project_id': {'type': 'string', 'format': 'uuid'},
            'revision_number': {'type': 'integer', 'minimum': 1},
            'event_type': {'type': 'string'},
            'snapshot': {'type': 'object', 'additionalProperties': True},
            'changed_fields': {'type': 'array', 'items': {'type': 'string'}},
            'actor_subject': {'type': 'string'},
            'occurred_at': {'type': 'string'},
            'created_at': {'type': 'string', 'nullable': True},
        },
        'additionalProperties': False,
    },
    'SampleHistoryPage': {
        'type': 'object',
        'required': ['items', 'next_cursor'],
        'properties': {
            'items': {
                'type': 'array',
                'items': {'$ref': '#/schemas/SampleRevisionEnvelope'},
            },
            'next_cursor': {'type': 'string', 'nullable': True},
        },
        'additionalProperties': False,
    },
    # ⚠️ 이름이 `SampleIntakeEnvelope` 가 아닌 이유: 그 키는 이미 `surface_projects`
    # 가 프로젝트 상세용으로 소유하고 있고, 그쪽은 `sample_intake_id` 키에 tech_group
    # 없이 좁은 모양이다. 계약 파사드가 키 중복을 DuplicateContractKeyError 로 거부해
    # 두 표면이 같은 이름으로 다른 모양을 기르는 것을 구조적으로 막는다. 두 모양을
    # 하나로 합치는 것은 프로젝트 상세 계약을 바꾸는 별개의 일이다.
    'SampleIntakeHistoryEnvelope': {
        'type': 'object',
        'required': ['intake_id', 'sample_id', 'project_id'],
        'properties': {
            'intake_id': {'type': 'string', 'format': 'uuid'},
            'sample_id': {'type': 'string', 'format': 'uuid'},
            'project_id': {'type': 'string', 'format': 'uuid'},
            # sample_number 와 test_category 는 일부러 없다 — 그것은 입고 행의 값이
            # 아니라 **시료**의 값이고, 호출자는 이미 어느 시료를 물었는지 안다.
            # 읽기 어댑터의 list_intakes 가 그 둘을 join 해 오는 것은 엑셀 export 가
            # 여러 시료를 한 번에 훑기 때문이며, 이 엔드포인트가 물려받을 이유가 없다.
            **_SAMPLE_INTAKE_PROPERTIES,
            'created_at': {'type': 'string', 'nullable': True},
            'updated_at': {'type': 'string', 'nullable': True},
        },
        'additionalProperties': False,
    },
    'SampleIntakeHistoryList': {
        'type': 'object',
        'required': ['items'],
        'properties': {
            'items': {
                'type': 'array',
                'items': {'$ref': '#/schemas/SampleIntakeHistoryEnvelope'},
            },
        },
        'additionalProperties': False,
    },
    'SampleCustodyEventEnvelope': {
        'type': 'object',
        'required': [
            'custody_event_id', 'sample_id', 'project_id', 'event_type',
            'actor_subject',
        ],
        'properties': {
            'custody_event_id': {'type': 'string', 'format': 'uuid'},
            'sample_id': {'type': 'string', 'format': 'uuid'},
            'project_id': {'type': 'string', 'format': 'uuid'},
            **_SAMPLE_CUSTODY_PROPERTIES,
            'actor_subject': {'type': 'string'},
            'created_at': {'type': 'string', 'nullable': True},
            'updated_at': {'type': 'string', 'nullable': True},
        },
        'additionalProperties': False,
    },
    'SampleCustodyEventList': {
        'type': 'object',
        'required': ['items'],
        'properties': {
            'items': {
                'type': 'array',
                'items': {'$ref': '#/schemas/SampleCustodyEventEnvelope'},
            },
        },
        'additionalProperties': False,
    },
    'SampleCustodyEventRequest': {
        'type': 'object',
        # event_type 만 필수다 — 나머지는 PM 이 아는 만큼만 적는다. 실제 엑셀에도
        # 날짜만 있고 상대방이 없는 행, 반입증만 있고 날짜가 없는 행이 섞여 있다.
        'required': ['event_type'],
        'properties': dict(_SAMPLE_CUSTODY_PROPERTIES),
        'additionalProperties': False,
    },
    'SampleCustodyEventDeleteReceipt': {
        'type': 'object',
        'required': ['custody_event_id', 'deleted'],
        'properties': {
            'custody_event_id': {'type': 'string', 'format': 'uuid'},
            'deleted': {'type': 'boolean', 'const': True},
        },
        'additionalProperties': False,
    },
    'SampleInventoryExport': {
        'type': 'string',
        'format': 'binary',
        'description': 'An XLSX workbook in the requested PM or RF template shape.',
    },
    'HardDeleteReceipt': {
        'type': 'object',
        'required': ['sample_id', 'hard_deleted'],
        'properties': {
            'sample_id': {'type': 'string', 'format': 'uuid'},
            'hard_deleted': {'type': 'boolean', 'const': True},
        },
        'additionalProperties': False,
    },
}


OPERATIONS: dict[str, dict] = {
    # Web-owned sample inventory CRUD/history/export.
    'list_sample_inventory': _operation(
        request=None,
        response='SampleInventoryPage',
        permission=PERMISSIONS['list_sample_inventory'],
        error_responses={'400': 'The inventory filter or cursor is malformed.'},
    ),
    'create_sample': _operation(
        request='SampleCreateRequest',
        response='SampleInventoryItem',
        permission=PERMISSIONS['create_sample'],
        error_responses={'400': 'The sample payload is invalid.', '404': _PROJECT_NOT_FOUND_404,
                         '409': 'A sample with the same sample_number already exists in this project.'},
    ),
    'get_sample': _operation(
        request=None,
        response='SampleInventoryItem',
        permission=PERMISSIONS['get_sample'],
        error_responses={'404': 'Sample not found in this project.'},
    ),
    'patch_sample': _operation(
        request='SamplePatchRequest',
        response='SampleInventoryItem',
        permission=PERMISSIONS['patch_sample'],
        error_responses={'400': 'The sample patch is invalid.', '404': 'Sample not found in this project.',
                         '409': 'The sample changed since it was loaded; reload before saving.'},
    ),
    'change_sample_status': _operation(
        request='SampleStatusRequest',
        response='SampleInventoryItem',
        permission=PERMISSIONS['change_sample_status'],
        error_responses={'400': 'The sample status transition is invalid.', '404': 'Sample not found in this project.',
                         '409': 'The sample changed since it was loaded; reload before saving.'},
    ),
    'delete_sample': _operation(
        request='SampleVersionRequest',
        response='SampleInventoryItem',
        permission=PERMISSIONS['delete_sample'],
        error_responses={'404': 'Sample not found in this project.',
                         '409': 'The sample changed since it was loaded; reload before deleting.'},
    ),
    'hard_delete_sample': _operation(
        request=None,
        response='HardDeleteReceipt',
        permission=PERMISSIONS['hard_delete_sample'],
        error_responses={'403': 'Only a global system_admin may hard-delete samples.',
                         '404': 'Sample not found.',},
    ),
    'list_sample_history': _operation(
        request=None,
        response='SampleHistoryPage',
        permission=PERMISSIONS['list_sample_history'],
        error_responses={'404': 'Sample not found in this project.'},
    ),
    'list_sample_intakes': _operation(
        request=None,
        response='SampleIntakeHistoryList',
        permission=PERMISSIONS['list_sample_intakes'],
        error_responses={'404': 'Sample not found in this project.'},
    ),
    'list_sample_custody_events': _operation(
        request=None,
        response='SampleCustodyEventList',
        permission=PERMISSIONS['list_sample_custody_events'],
        error_responses={'404': 'Sample not found in this project.'},
    ),
    'append_sample_custody_event': _operation(
        request='SampleCustodyEventRequest',
        response='SampleCustodyEventEnvelope',
        permission=PERMISSIONS['append_sample_custody_event'],
        error_responses={'400': 'The custody event is invalid (event_type is required).',
                         '404': 'Sample not found in this project.'},
    ),
    'delete_sample_custody_event': _operation(
        request=None,
        response='SampleCustodyEventDeleteReceipt',
        permission=PERMISSIONS['delete_sample_custody_event'],
        error_responses={'404': 'Custody event not found for this sample.'},
    ),
    'export_sample_inventory': _operation(
        request=None,
        response='SampleInventoryExport',
        permission=PERMISSIONS['export_sample_inventory'],
        response_media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        error_responses={'400': 'The export template or filter is invalid.',
                         '404': _PROJECT_NOT_FOUND_404,
                         '422': 'The selected records cannot be represented in the requested template.'},
    ),
}
