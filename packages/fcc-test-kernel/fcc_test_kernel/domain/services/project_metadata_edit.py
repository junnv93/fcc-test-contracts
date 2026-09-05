"""Project 성적서 메타 부분 편집 정책 (W3 백엔드, 2026-07-28).

프로젝트(=모델) 진입층의 성적서 표지 메타는 지금까지 **생성 시에만** 쓸 수
있었다(``CreateProjectRequest``). FCC ID·applicant 는 프로젝트 개시 뒤에 확정되는
것이 정상 업무 흐름이라, 오타나 후행 확정을 되돌릴 경로가 없다는 것이 결함이었다.

본 모듈은 그 ``PATCH`` 경로의 **판단**만 소유한다 (영속은 어댑터):

1. **편집 가능 필드 SSOT** — :data:`EDITABLE_PROJECT_META_FIELDS`. 어댑터의
   ``SET`` 컬럼 목록, OpenAPI 스키마, 봉인 테스트가 전부 이 튜플에서 파생한다
   (컬럼명 인라인 리터럴 0).
2. **소속 테이블 분할** — ``manufacturer`` 만 ``device_models`` 소속이고 나머지가
   ``projects`` 소속이다(central_db_schema.v1.json SSOT). 두 테이블을 건드리므로
   어댑터는 **하나의 트랜잭션**에서 갱신해야 한다(부분 성공 금지).
3. **부분 갱신 semantics** — 요청에 **없는 키 = 무변경**, 명시적 ``null`` = **삭제**.
   ``COALESCE(EXCLUDED, existing)`` 머지를 채택하지 **않는다**: 그 선택은 sample
   inventory upsert 에서 이미 "PM 명시적 값 삭제 워크플로우 미지원" 부작용으로
   기록된 함정이다. 따라서 파서는 ``key in body`` 로 키 존재를 먼저 판정하고
   **존재하는 키만** 반환한다 — ``body.get(key)`` 로 읽으면 두 경우가 ``None`` 으로
   뭉개져 계약이 그 자리에서 깨진다.
4. **범위 밖 필드의 loud 거부** — ``status`` 는 ``complete_project`` /
   ``reopen_project`` 액션 서브리소스가 상태 전이 SSOT 이고, ``model_name`` /
   ``project_code`` 는 로컬 측정 DB 파일명까지 전파되는 정체성(ADR-0005 재키잉)이다.
   둘 다 조용히 무시하지 않고 ``ValueError`` (→ 400) 로 거부한다 — 조용한 무시는
   "보냈는데 반영 안 됨"이라는 더 나쁜 실패 모드다.

## 개정 (2026-09-04) — **채우는 시점**이 필드 집합의 축이 된다

메타 8칸은 지금까지 한 덩어리였고, 그래서 생성 폼이 8칸을 한 번에 물었다. 그런데
그 8칸은 **확정되는 시점이 다르다**: 관리번호·신청자는 접수 때 이미 있고,
grantee code·EUT 설명·시험 규격은 성적서를 쓸 때가 되어야 확정된다. 시점이 다른
칸을 한 폼에 세우면 사용자는 "지금 알 수 없는 값"을 앞에 두고 멈추고, 그 칸들은
결국 영구 공란으로 남는다(이 결함이 실제로 그렇게 관측되었다).

그래서 집합을 **하나 더 쪼개는 대신 축을 하나 세운다** — 필드마다 소속 테이블을
:data:`PROJECT_META_FIELD_TABLES` 가 말하듯, 채우는 시점을
:data:`PROJECT_META_FIELD_STAGES` 가 말한다. ``EDITABLE_PROJECT_META_FIELDS`` 는
두 스테이지의 **합**으로 파생되므로 PATCH 계약은 조금도 좁아지지 않는다(어느
스테이지의 칸이든 언제나 편집 가능하다 — 스테이지는 **어느 화면이 그 칸을 먼저
묻는가**이지 권한이 아니다).

선례: ``domain/models/sample_inventory.py`` 의 ``SAMPLE_EDITABLE_FIELDS`` /
``INTAKE_FIELDS`` 가 같은 모양이다 — 한 행의 칸을 "언제 관측되는가"로 나눠 두 개의
튜플로 두고, 화면이 그 튜플을 골라 렌더한다.

## 개정 (2026-09-04) — ``customer`` 폐기, 값은 ``applicant_name`` 으로 합류

``customer``(고객사)와 ``applicant_name``(신청자)은 FCC 성적서 표지에서 같은 주체를
가리켰다. 두 칸을 나란히 세워 두면 둘 중 어디에 적을지가 매번 판단거리가 되고,
결국 같은 회사가 두 이름으로 갈라져 검색이 그만큼 새는 결과가 된다(검색 축이
``customer`` 였으므로 신청자 칸에만 적힌 회사는 검색되지 않았다 — 실제 결함).

폐기된 이름은 :data:`RETIRED_PROJECT_META_FIELDS` 가 **후임 필드와 함께** 들고
있다가 전용 메시지로 거절한다. "unknown field" 로 뭉개지 않는 이유는, 원인이 다르면
고치는 방법도 다르기 때문이다 — 오타는 철자를 고쳐야 하고, 폐기는 **다른 칸으로
옮겨** 적어야 한다. 후자를 전자처럼 말하면 호출자는 없는 철자를 찾아 헤맨다.

도메인 순수: stdlib 만 import (infrastructure / psycopg / openpyxl / pandas /
PySide6 무의존).
"""
from __future__ import annotations

from collections.abc import Mapping as _MappingABC
from types import MappingProxyType
from typing import Mapping, Optional


__all__ = [
    'APPLICANT_IDENTITY_FIELD',
    'APPLICANT_SUGGESTION_FIELDS',
    'CREATE_PROJECT_IDENTITY_FIELD',
    'CREATE_PROJECT_REQUIRED_FIELDS',
    'DEVICE_MODEL_META_FIELDS',
    'EDITABLE_PROJECT_META_FIELDS',
    'IMMUTABLE_PROJECT_FIELDS',
    'INTAKE_STAGE',
    'PROJECT_INTAKE_META_FIELDS',
    'PROJECT_META_FIELD_STAGES',
    'PROJECT_META_FIELD_TABLES',
    'PROJECT_TABLE_META_FIELDS',
    'REPORT_STAGE',
    'REPORT_STAGE_META_FIELDS',
    'RETIRED_PROJECT_META_FIELDS',
    'UNIQUE_PROJECT_META_FIELDS',
    'device_model_table_updates',
    'parse_project_create_request',
    'parse_project_metadata_update',
    'project_table_updates',
    'stage_meta_fields',
]


#: 스테이지 토큰 — 필드를 **누가 먼저 묻는가**. 값 공간이 둘뿐이라 Enum 을 두지
#: 않는다(이 모듈 밖으로 나가는 것은 OpenAPI 설명문과 프론트 폼 배치뿐이다).
INTAKE_STAGE = 'intake'
REPORT_STAGE = 'report'


#: **접수 스테이지** — 프로젝트를 개설하는 시점에 이미 확정되어 있는 칸.
#: 생성 폼이 노출하는 집합이 정확히 이것이다(+ 정체성인 ``model_name``).
#:
#: 순서는 접수증을 읽는 순서다: 번호 → 신청 주체 → 그 주소 → 제조사.
PROJECT_INTAKE_META_FIELDS: tuple[str, ...] = (
    'management_number',
    'applicant_name',
    'applicant_address',
    'manufacturer',
)

#: **성적서 스테이지** — 성적서를 쓰는 시점에야 확정되는 칸. 생성 폼은 이 칸을
#: 묻지 않는다(그 시점에 답이 없는 질문이기 때문이다). 성적서 화면이 묻는다.
#:
#: ``fcc_grantee_code`` 가 여기 있는 것이 중요하다 — 파생값 ``fcc_id`` 의 재료라
#: "프로젝트 개시 = FCC ID 확정" 처럼 보이지만, grantee code 는 인증 신청이
#: 진행되어야 나오는 값이다. 개시 시점에 물으면 대부분 공란으로 남는다.
REPORT_STAGE_META_FIELDS: tuple[str, ...] = (
    'fcc_grantee_code',
    'eut_description',
    'test_standard',
)

#: 프로젝트마다 **유일**해야 하는 메타 칸 (중앙 스키마의 UNIQUE 제약과 1:1 —
#: ``ux_projects_management_number``). 유일성은 이 칸이 다른 프로젝트에서 값을
#: **물려받을 수 없다**는 뜻이기도 하다: 물려받는 순간 그 자리에서 409 다.
UNIQUE_PROJECT_META_FIELDS: tuple[str, ...] = (
    'management_number',
)

#: 신청자 제안(자동 채움)의 **식별 칸**. 같은 신청자를 가리키는 표기는 대소문자만
#: 다를 수 있으므로, 조회 어댑터는 이 칸을 정규화(lower)해 그룹 키로 쓴다.
APPLICANT_IDENTITY_FIELD = 'applicant_name'

#: 신청자를 고르면 **함께 따라오는** 칸 (SSOT) — 접수 스테이지 메타에서 유일 제약이
#: 걸린 칸을 뺀 나머지로 **파생**한다.
#:
#: 손으로 고른 목록이 아니라는 점이 핵심이다. "왜 관리번호는 자동으로 안 채워지는가"의
#: 답이 :data:`UNIQUE_PROJECT_META_FIELDS` 에 이미 있으므로(유일한 값은 물려받을 수
#: 없다), 그 답을 두 번째 목록으로 다시 적으면 한쪽만 바뀌는 날 자동 채움이 409 를
#: 만들어내기 시작한다. 접수 칸이 늘면 자동 채움 대상도 함께 늘어나는 것이 옳다.
APPLICANT_SUGGESTION_FIELDS: tuple[str, ...] = tuple(
    field for field in PROJECT_INTAKE_META_FIELDS
    if field not in UNIQUE_PROJECT_META_FIELDS
)

#: 프로젝트 **정체성** 필드. 메타가 아니라 프로젝트 그 자체의 이름이므로
#: ``EDITABLE_PROJECT_META_FIELDS`` 에 들어가지 않는다(편집은 재키잉 문제 —
#: :data:`IMMUTABLE_PROJECT_FIELDS`). 생성 요청에서만 필수로 나타난다.
CREATE_PROJECT_IDENTITY_FIELD = 'model_name'

#: 생성 시점에 **반드시** 있어야 하는 칸 (SSOT).
#:
#: 왜 이 셋인가 — 각각이 없으면 **뒤의 워크플로우가 성립하지 않는다**:
#: - ``model_name``: 프로젝트 정체성 그 자체(ADR-0017 D1, project_code == 모델명).
#: - ``management_number``: 성적서 번호 ``S-{management_number}-{edition}`` 의
#:   유일한 재료(report_number_policy SSOT). 없으면 성적서 화면이 번호를 만들지
#:   못하고 "왜 비었는지"만 설명하게 된다.
#: - ``applicant_name``: 성적서 표지의 신청 주체이자 프로젝트 디렉터리의 검색 축.
#:   없으면 그 프로젝트는 이름 말고는 **찾을 방법이 없다**.
#:
#: 나머지 접수 칸(주소·제조사)은 선택이다 — 없어도 위 셋의 기능이 성립한다.
#: 성적서 스테이지 칸은 생성 시점에 답이 없으므로 당연히 선택이다.
#:
#: 이 튜플이 OpenAPI ``required``, 서버 400, 화면의 필수 표시(``*``)를 **함께**
#: 구동한다. 셋 중 하나만 고치는 경로가 없다.
CREATE_PROJECT_REQUIRED_FIELDS: tuple[str, ...] = (
    CREATE_PROJECT_IDENTITY_FIELD,
    'management_number',
    'applicant_name',
)

#: 편집 가능한 성적서 메타 필드 (SSOT) — 두 스테이지의 **합**으로 파생한다.
#: PATCH 계약은 스테이지로 좁아지지 않는다: 어느 칸이든 언제나 편집 가능하고,
#: 스테이지는 "어느 화면이 먼저 묻는가"만 말한다.
EDITABLE_PROJECT_META_FIELDS: tuple[str, ...] = (
    PROJECT_INTAKE_META_FIELDS + REPORT_STAGE_META_FIELDS
)

#: 필드 → 스테이지. 위 두 튜플에서 파생하므로 손으로 유지되는 세 번째 목록이 아니다.
PROJECT_META_FIELD_STAGES: Mapping[str, str] = MappingProxyType({
    **{field: INTAKE_STAGE for field in PROJECT_INTAKE_META_FIELDS},
    **{field: REPORT_STAGE for field in REPORT_STAGE_META_FIELDS},
})

#: 폐기된 필드 → **후임 필드**. 값이 후임으로 합류했으므로 "모르는 칸"이 아니라
#: "옮겨 간 칸"이다. 파서가 이 표를 들고 전용 메시지로 거절한다(§개정 2026-09-04).
RETIRED_PROJECT_META_FIELDS: Mapping[str, str] = MappingProxyType({
    'customer': 'applicant_name',
})

#: PATCH 로 절대 바뀌지 않는 필드 → loud ``ValueError``.
#: - ``status``: 상태 전이 SSOT 는 complete/reopen 액션 서브리소스. PATCH 에 넣으면
#:   전이 경로가 둘이 되어 그 결정이 무효화된다.
#: - ``model_name`` / ``project_code``: ADR-0017 D1 의 1:1 정체성 키. 편집은 메타
#:   수정이 아니라 재키잉(ADR-0005) 문제다.
IMMUTABLE_PROJECT_FIELDS: tuple[str, ...] = (
    'status',
    'model_name',
    'project_code',
)

_PROJECTS_TABLE = 'projects'
_DEVICE_MODELS_TABLE = 'device_models'

#: 필드 → 소속 테이블. central_db_schema.v1.json 의 컬럼 배치와 1:1
#: (``manufacturer`` 만 device_models, 나머지는 projects).
PROJECT_META_FIELD_TABLES: Mapping[str, str] = MappingProxyType({
    'management_number': _PROJECTS_TABLE,
    'applicant_name': _PROJECTS_TABLE,
    'applicant_address': _PROJECTS_TABLE,
    'manufacturer': _DEVICE_MODELS_TABLE,
    'fcc_grantee_code': _PROJECTS_TABLE,
    'eut_description': _PROJECTS_TABLE,
    'test_standard': _PROJECTS_TABLE,
})

#: 테이블별 필드 튜플 (선언 순서 보존 — 어댑터 SET 절 순서가 결정적이어야
#: SQL 상수를 import 시점에 사전 생성할 수 있다).
PROJECT_TABLE_META_FIELDS: tuple[str, ...] = tuple(
    field for field in EDITABLE_PROJECT_META_FIELDS
    if PROJECT_META_FIELD_TABLES[field] == _PROJECTS_TABLE
)
DEVICE_MODEL_META_FIELDS: tuple[str, ...] = tuple(
    field for field in EDITABLE_PROJECT_META_FIELDS
    if PROJECT_META_FIELD_TABLES[field] == _DEVICE_MODELS_TABLE
)


def stage_meta_fields(stage: str) -> tuple[str, ...]:
    """스테이지에 속한 편집 필드를 선언 순서로 돌려준다.

    화면(생성 폼 / 성적서 폼)이 자기 칸 목록을 **파생**하는 지점이다. 화면이
    ``('management_number', …)`` 를 손으로 적으면 그것이 두 번째 SSOT 가 되고,
    스테이지가 바뀌어도 조용히 옛 목록을 그린다.

    Raises:
        ValueError: 모르는 스테이지 토큰 (조용히 빈 튜플을 주면 폼이 **칸 없이**
            렌더되어 "입력할 게 없다"는 거짓 화면이 된다).
    """
    known = (INTAKE_STAGE, REPORT_STAGE)
    if stage not in known:
        raise ValueError(f'unknown project meta stage {stage!r} — known stages are {list(known)}')
    return tuple(
        field for field in EDITABLE_PROJECT_META_FIELDS
        if PROJECT_META_FIELD_STAGES[field] == stage
    )


def parse_project_create_request(
    body: Optional[Mapping],
) -> dict[str, Optional[str]]:
    """생성 요청 본문을 (필드 → 값-or-``None``) 맵으로 정규화한다.

    PATCH 경로의 :func:`parse_project_metadata_update` 와 **대칭**이다. 그전까지
    생성 경로는 HTTP 어댑터가 ``payload.get('customer')`` … 를 필드 수만큼 손으로
    나열했는데, 그 나열이 곧 필드 목록의 두 번째 사본이었다 — 이 모듈의 튜플이
    바뀌어도 그 나열은 조용히 옛 목록을 날랐다(``customer`` 폐기가 그 결함을
    드러냈다). 이제 두 경로 모두 **여기**를 지난다.

    PATCH 와 다른 점은 정확히 둘이다:

    1. **정체성 필드를 받는다** — ``model_name`` 은 PATCH 에서 loud 거부되지만
       생성에서는 필수다(그때가 정체성이 정해지는 유일한 시점이다).
    2. **필수 검증이 있다** — :data:`CREATE_PROJECT_REQUIRED_FIELDS`. PATCH 는
       "보낸 칸만 바꾼다"가 계약이라 필수가 성립하지 않는다.

    스테이지로 **좁히지는 않는다**: 성적서 스테이지 칸을 생성 시 함께 보내는 것은
    유효하다(예 — 이관 도구가 이미 아는 값을 한 번에 싣는다). 스테이지는 *화면이
    어느 칸을 먼저 묻는가*이지 계약의 경계가 아니다.

    반환 dict 는 **본문에 존재한 키만** 담는다 — 부재 키는 나타나지 않으므로
    호출자가 "미기재"를 그대로 전파할 수 있다. 값 정규화는 PATCH 와 같은 규약
    (trim, 빈 문자열 → ``None``)이라 "생성 땐 되는데 수정 땐 안 되는" 비대칭이 없다.

    Raises:
        ValueError: 본문이 매핑이 아님 / **폐기된 필드** 동봉 / 미지 키 /
            ``status``·``project_code`` 동봉 / 필수 칸 누락·공백. 전부 loud (→ 400).
    """
    if body is None:
        raise ValueError('project create body is required')
    if not isinstance(body, _MappingABC):
        raise ValueError(
            f'project create body must be an object, got {type(body).__name__}'
        )

    # 생성에서도 손댈 수 없는 것들 — ``status`` 는 전이 액션이 SSOT 이고
    # (생성은 항상 'active' 로 시작한다), ``project_code`` 는 ``model_name`` 에서
    # 파생되는 값이라 별도로 받으면 두 정체성이 어긋날 수 있다.
    forbidden = [
        key for key in IMMUTABLE_PROJECT_FIELDS
        if key != CREATE_PROJECT_IDENTITY_FIELD and key in body
    ]
    if forbidden:
        raise ValueError(
            f'{forbidden} cannot be supplied on project create — status starts '
            f"'active' (transitions use the complete/reopen sub-resources) and "
            f'project_code is derived from {CREATE_PROJECT_IDENTITY_FIELD}'
        )

    retired = [key for key in RETIRED_PROJECT_META_FIELDS if key in body]
    if retired:
        moved = ', '.join(
            f'{key!r} → {RETIRED_PROJECT_META_FIELDS[key]!r}' for key in retired
        )
        raise ValueError(
            f'retired project field(s) {retired} — the value moved to another '
            f'field ({moved}); send the successor field instead'
        )

    allowed = {CREATE_PROJECT_IDENTITY_FIELD, *EDITABLE_PROJECT_META_FIELDS}
    unknown = sorted(key for key in body if key not in allowed)
    if unknown:
        raise ValueError(
            f'unknown project create field(s) {unknown} — accepted fields are '
            f'{[CREATE_PROJECT_IDENTITY_FIELD, *EDITABLE_PROJECT_META_FIELDS]}'
        )

    values: dict[str, Optional[str]] = {}
    for field in (CREATE_PROJECT_IDENTITY_FIELD, *EDITABLE_PROJECT_META_FIELDS):
        if field not in body:
            continue
        values[field] = _optional_text(body[field])

    # 필수 판정은 **정규화 뒤**에 한다 — 공백만 있는 문자열은 위에서 ``None`` 이
    # 되었으므로, "보내긴 했는데 비었다"와 "안 보냈다"가 여기서 같은 실패가 된다
    # (사용자에게는 같은 사실이다: 그 칸이 비어 있다).
    missing = [
        field for field in CREATE_PROJECT_REQUIRED_FIELDS
        if values.get(field) is None
    ]
    if missing:
        raise ValueError(
            f'project create requires non-empty {missing} — '
            f'{list(CREATE_PROJECT_REQUIRED_FIELDS)} are mandatory'
        )
    return values


def parse_project_metadata_update(
    body: Optional[Mapping],
) -> dict[str, Optional[str]]:
    """요청 본문을 (필드 → 값-or-``None``) 부분 갱신 맵으로 정규화한다.

    반환 dict 는 **본문에 실제로 존재한 키만** 담는다 — 부재 키는 아예 나타나지
    않으므로 호출자가 "무변경"과 "``null`` 삭제"를 구분할 수 있다. 값은 create
    경로(``_opt_text``)와 같은 규약으로 정규화한다: 문자열은 trim, 빈 문자열/공백
    문자열은 ``None``(삭제) — 두 경로가 다르면 "생성 땐 되는데 수정 땐 안 되는"
    비대칭이 생긴다.

    Raises:
        ValueError: 본문이 매핑이 아님 / ``status``·``model_name``·``project_code``
            동봉 / **폐기된 필드** 동봉 / 미지 키 / 편집 가능 키가 하나도 없음.
            전부 loud (→ 400) — 조용한 무시나 조용한 no-op 은 만들지 않는다.
    """
    if body is None:
        raise ValueError('project metadata update body is required')
    if not isinstance(body, _MappingABC):
        raise ValueError(
            f'project metadata update body must be an object, got '
            f'{type(body).__name__}'
        )

    immutable = [key for key in IMMUTABLE_PROJECT_FIELDS if key in body]
    if immutable:
        raise ValueError(
            f'{immutable} cannot be changed via project metadata update — '
            f'status transitions use the complete/reopen action sub-resources and '
            f'model_name/project_code is the project identity (re-keying, not a '
            f'metadata edit)'
        )

    # 폐기 필드는 미지 키보다 **먼저** 판정한다. 순서가 뒤바뀌면 "unknown field
    # ['customer']" 라는, 고칠 방법을 알려주지 않는 메시지가 나간다.
    retired = [key for key in RETIRED_PROJECT_META_FIELDS if key in body]
    if retired:
        moved = ', '.join(
            f'{key!r} → {RETIRED_PROJECT_META_FIELDS[key]!r}' for key in retired
        )
        raise ValueError(
            f'retired project metadata field(s) {retired} — the value moved to '
            f'another field ({moved}); send the successor field instead'
        )

    allowed = set(EDITABLE_PROJECT_META_FIELDS)
    unknown = sorted(key for key in body if key not in allowed)
    if unknown:
        raise ValueError(
            f'unknown project metadata field(s) {unknown} — editable fields are '
            f'{list(EDITABLE_PROJECT_META_FIELDS)}'
        )

    updates: dict[str, Optional[str]] = {}
    for field in EDITABLE_PROJECT_META_FIELDS:
        if field not in body:
            continue  # 키 부재 = 무변경 (SET 절에 나타나지 않는다)
        updates[field] = _optional_text(body[field])

    if not updates:
        raise ValueError(
            f'project metadata update requires at least one of '
            f'{list(EDITABLE_PROJECT_META_FIELDS)}'
        )
    return updates


def project_table_updates(
    updates: Mapping[str, Optional[str]],
) -> dict[str, Optional[str]]:
    """``projects`` 테이블 소속 갱신분만 (선언 순서로) 투영."""
    return _project_subset(updates, PROJECT_TABLE_META_FIELDS)


def device_model_table_updates(
    updates: Mapping[str, Optional[str]],
) -> dict[str, Optional[str]]:
    """``device_models`` 테이블 소속 갱신분만 (선언 순서로) 투영."""
    return _project_subset(updates, DEVICE_MODEL_META_FIELDS)


def _project_subset(
    updates: Mapping[str, Optional[str]], fields: tuple[str, ...],
) -> dict[str, Optional[str]]:
    return {field: updates[field] for field in fields if field in updates}


def _optional_text(value: object) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
