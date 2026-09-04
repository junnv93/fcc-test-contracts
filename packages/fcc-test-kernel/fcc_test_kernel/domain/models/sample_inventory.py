"""Pure value objects for the web-owned sample inventory.

The web inventory deliberately models the current projection, immutable intake
rows, and immutable revision snapshots separately.  No database, spreadsheet,
HTTP, or UI dependency belongs in this module: the same objects are used by
the API service, export policy, and measurement-session snapshot boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


SNAPSHOT_SCHEMA_VERSION = 'fcc.sample.inventory.snapshot.v1'


class SampleStatus(str, Enum):
    ACTIVE = 'active'
    DELETED = 'deleted'


class SampleRevisionEvent(str, Enum):
    CREATED = 'created'
    UPDATED = 'updated'
    STATUS_CHANGED = 'status_changed'
    RESTORED = 'restored'
    BASELINE = 'baseline'


# 시료 분류 어휘 (ADR-0002 결정 3·4·8). DB CHECK 로 굳히지 않는다 — 값 제한은
# 애플리케이션 경계가 하고, 이 튜플이 그 경계의 SSOT 다. `test_equipment_lists.
# test_item_key` 가 같은 판단을 먼저 내렸다: 확장마다 중앙 마이그레이션을 요구하는
# CHECK 보다 코드 경계의 검증이 낫다.
class SampleCustodyEventType(str, Enum):
    """PM 축의 반입/반출 사건 (ADR-0002).

    ⭐ 이 어휘에는 CHECK 를 건다 — `test_category` 와 달리 확장 가능한 어휘가 아니라
    **닫힌 이분법**이고, 보유 상태 계산의 입력이다(가장 최근 사건이 ``received`` 면
    보유 중). 제3의 값이 들어오면 그 계산이 조용히 틀린다.
    """

    RECEIVED = 'received'
    RELEASED = 'released'


SAMPLE_KINDS: tuple[str, ...] = ('Device', 'Accessory')

# Conducted/Radiated 는 시료의 속성이다 (결정 4) — 한 물리 시료는 한쪽 전용이다.
# 값은 RF 엑셀 export 의 시트 이름과 같은 철자여야 한다 (Conduction/Radiation 시트를
# `test_category == sheet_name` 으로 가른다).
TEST_CATEGORIES: tuple[str, ...] = ('Conduction', 'Radiation')

# Accessory 는 Conducted/Radiated 를 갖지 않는다 (결정 8).
KIND_WITHOUT_TEST_CATEGORY: str = 'Accessory'


SAMPLE_EDITABLE_FIELDS: tuple[str, ...] = (
    'sample_number',
    'sample_code',
    'sample_kind',
    'sample_description',
    'test_category',
    'label_number',
    'smsn',
    'serial_number',
    'intake_cert',
    'assigned_team',
    'sender',
    'receiver',
    'received_date',
    'released_date',
    'note',
)

INTAKE_FIELDS: tuple[str, ...] = (
    'intake_date',
    'bl',
    'ap',
    'cp',
    'csc',
    'rf_cal',
    'hw_rev',
    'note',
    'tech_group',
)

# 한 custody 사건이 사람에게서 받는 값 (ADR-0002 결정 6·7).
# ⚠️ `intake_cert_number` 는 시료의 속성이 아니라 **반입 사건**의 속성이다. 반입증은
# 고객사가 한 번의 납품에 한 장 발행하고 그 납품에 실린 시료 여럿이 같은 번호를
# 공유한다(운영자 확인, 12대 단위). 배치는 (project_id, intake_cert_number) 로 묶으면
# 복원되므로 별도의 반입증 테이블을 두지 않는다.
CUSTODY_EVENT_FIELDS: tuple[str, ...] = (
    'event_type',
    'occurred_on',
    'counterparty',
    'intake_cert_number',
    'reason',
    'note',
)

REVISION_SNAPSHOT_FIELDS: tuple[str, ...] = SAMPLE_EDITABLE_FIELDS + (
    'status',
    'row_version',
    'latest_intake',
)


@dataclass(frozen=True)
class SampleIntake:
    """One immutable intake observation."""

    id: Optional[str] = None
    sample_id: Optional[str] = None
    intake_date: Optional[str] = None
    bl: Optional[str] = None
    ap: Optional[str] = None
    cp: Optional[str] = None
    csc: Optional[str] = None
    rf_cal: Optional[str] = None
    hw_rev: Optional[str] = None
    note: Optional[str] = None
    tech_group: Optional[str] = None
    created_at: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'sample_id': self.sample_id,
            'intake_date': self.intake_date,
            'bl': self.bl,
            'ap': self.ap,
            'cp': self.cp,
            'csc': self.csc,
            'rf_cal': self.rf_cal,
            'hw_rev': self.hw_rev,
            'note': self.note,
            'tech_group': self.tech_group,
            'created_at': self.created_at,
        }


@dataclass(frozen=True)
class SampleCustodyEvent:
    """PM 축의 반입/반출 사건 한 건 (ADR-0002).

    시험 실무자 축의 ``SampleIntake`` 와 대칭이다 — 같은 시료에 1:N 으로 쌓이고,
    화면·API·감사가 한 벌의 관례로 처리한다. 차이는 이 축이 **짝지어진다**는 것이다:
    ``released`` 뒤에 ``received`` 가 오면 재반입이고, 가장 최근 사건이 무엇이냐가
    현재 보유 상태다.
    """

    id: Optional[str] = None
    sample_id: Optional[str] = None
    project_id: Optional[str] = None
    event_type: SampleCustodyEventType = SampleCustodyEventType.RECEIVED
    occurred_on: Optional[str] = None
    counterparty: Optional[str] = None
    intake_cert_number: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    actor_subject: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'sample_id': self.sample_id,
            'project_id': self.project_id,
            'event_type': self.event_type.value,
            'occurred_on': self.occurred_on,
            'counterparty': self.counterparty,
            'intake_cert_number': self.intake_cert_number,
            'reason': self.reason,
            'note': self.note,
            'actor_subject': self.actor_subject,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


@dataclass(frozen=True)
class Sample:
    """Current sample projection returned by the central read service."""

    id: str
    project_id: str
    sample_number: Optional[str] = None
    sample_code: Optional[str] = None
    sample_kind: Optional[str] = None
    sample_description: Optional[str] = None
    test_category: Optional[str] = None
    label_number: Optional[str] = None
    smsn: Optional[str] = None
    serial_number: Optional[str] = None
    intake_cert: Optional[str] = None
    assigned_team: Optional[str] = None
    sender: Optional[str] = None
    receiver: Optional[str] = None
    received_date: Optional[str] = None
    released_date: Optional[str] = None
    note: Optional[str] = None
    status: SampleStatus = SampleStatus.ACTIVE
    row_version: int = 1
    latest_intake: Optional[SampleIntake] = None
    intake_count: int = 0
    # 파생값이다 — 사람이 편집하지 않으므로 SAMPLE_EDITABLE_FIELDS 에 없고, 따라서
    # 리비전 스냅샷에도 들어가지 않는다. custody 사건들로부터 읽기 시점에 계산된다.
    custody_state: Optional[str] = None
    custody_event_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def as_dict(self, *, include_intake: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            'id': self.id,
            'project_id': self.project_id,
            'sample_number': self.sample_number,
            'sample_code': self.sample_code,
            'sample_kind': self.sample_kind,
            'sample_description': self.sample_description,
            'test_category': self.test_category,
            'label_number': self.label_number,
            'smsn': self.smsn,
            'serial_number': self.serial_number,
            'intake_cert': self.intake_cert,
            'assigned_team': self.assigned_team,
            'sender': self.sender,
            'receiver': self.receiver,
            'received_date': self.received_date,
            'released_date': self.released_date,
            'note': self.note,
            'status': self.status.value,
            'row_version': self.row_version,
            'intake_count': self.intake_count,
            'custody_state': self.custody_state,
            'custody_event_count': self.custody_event_count,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if include_intake:
            result['latest_intake'] = (
                self.latest_intake.as_dict() if self.latest_intake else None
            )
        return result


@dataclass(frozen=True)
class SampleRevision:
    """Append-only full post-mutation sample snapshot."""

    id: str
    sample_id: str
    project_id: str
    revision_number: int
    event_type: SampleRevisionEvent
    snapshot: Mapping[str, Any]
    changed_fields: tuple[str, ...] = ()
    actor_subject: str = ''
    occurred_at: str = ''
    created_at: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'sample_id': self.sample_id,
            'project_id': self.project_id,
            'revision_number': self.revision_number,
            'event_type': self.event_type.value,
            'snapshot': dict(self.snapshot),
            'changed_fields': list(self.changed_fields),
            'actor_subject': self.actor_subject,
            'occurred_at': self.occurred_at,
            'created_at': self.created_at,
        }


@dataclass(frozen=True)
class SampleSnapshot:
    """Canonical immutable snapshot carried into a measurement session."""

    schema_version: str
    captured_at: str
    project: Mapping[str, Any]
    sample: Mapping[str, Any]
    latest_intake: Optional[Mapping[str, Any]]
    sample_revision: int
    row_version: int

    def as_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'captured_at': self.captured_at,
            'project': dict(self.project),
            'sample': dict(self.sample),
            'latest_intake': (
                dict(self.latest_intake) if self.latest_intake is not None else None
            ),
            'sample_revision': self.sample_revision,
            'row_version': self.row_version,
        }


@dataclass(frozen=True)
class SampleInventoryFilter:
    """One filter specification shared by list and export."""

    project_id: Optional[str] = None
    team: Optional[str] = None
    status: Optional[SampleStatus] = None
    as_of: Optional[str] = None
    after: Optional[str] = None
    limit: int = 100
    include_deleted: bool = False


def intake_from_mapping(value: Optional[Mapping[str, Any]]) -> Optional[SampleIntake]:
    if value is None:
        return None
    return SampleIntake(
        id=value.get('id'),
        sample_id=value.get('sample_id'),
        intake_date=value.get('intake_date'),
        bl=value.get('bl'),
        ap=value.get('ap'),
        cp=value.get('cp'),
        csc=value.get('csc'),
        rf_cal=value.get('rf_cal'),
        hw_rev=value.get('hw_rev'),
        note=value.get('note'),
        tech_group=value.get('tech_group'),
        created_at=value.get('created_at'),
    )


def custody_event_from_mapping(
    value: Optional[Mapping[str, Any]],
) -> Optional[SampleCustodyEvent]:
    if value is None:
        return None
    event_type = value.get('event_type', SampleCustodyEventType.RECEIVED)
    if not isinstance(event_type, SampleCustodyEventType):
        event_type = SampleCustodyEventType(str(event_type))
    return SampleCustodyEvent(
        id=value.get('id'),
        sample_id=value.get('sample_id'),
        project_id=value.get('project_id'),
        event_type=event_type,
        occurred_on=value.get('occurred_on'),
        counterparty=value.get('counterparty'),
        intake_cert_number=value.get('intake_cert_number'),
        reason=value.get('reason'),
        note=value.get('note'),
        actor_subject=value.get('actor_subject'),
        created_at=value.get('created_at'),
        updated_at=value.get('updated_at'),
    )


def custody_state(
    latest_event: Optional[SampleCustodyEvent | Mapping[str, Any]],
) -> Optional[str]:
    """현재 보유 상태 — 가장 최근 custody 사건 하나가 답이다.

    ⚠️ 이 규칙이 사는 자리는 여기 하나여야 한다. 읽기 어댑터가 SQL 로, 화면이
    TypeScript 로 각자 판단하면 세 곳이 서로 다르게 틀릴 수 있다. SQL 은 '가장 최근
    사건'을 고르기만 하고 그 뜻은 이 함수가 정한다.

    사건이 하나도 없으면 ``None`` 이다 — '반출됨'이 아니다. 기존 시료는 사건이 없는
    채로 넘어오고(ADR-0002 결정 9: 자동 변환하지 않는다), 그것을 '반출됨'으로 읽으면
    사람이 적지 않은 사실을 시스템이 지어내는 것이 된다.
    """
    if latest_event is None:
        return None
    event_type = (
        latest_event.event_type if isinstance(latest_event, SampleCustodyEvent)
        else latest_event.get('event_type')
    )
    if event_type is None:
        return None
    if not isinstance(event_type, SampleCustodyEventType):
        event_type = SampleCustodyEventType(str(event_type))
    return (
        'in_custody' if event_type is SampleCustodyEventType.RECEIVED
        else 'released'
    )


def sample_from_mapping(value: Mapping[str, Any]) -> Sample:
    status = value.get('status', SampleStatus.ACTIVE)
    if not isinstance(status, SampleStatus):
        status = SampleStatus(str(status))
    return Sample(
        id=str(value['id']),
        project_id=str(value['project_id']),
        sample_number=value.get('sample_number'),
        sample_code=value.get('sample_code'),
        sample_kind=value.get('sample_kind'),
        sample_description=value.get('sample_description'),
        test_category=value.get('test_category'),
        label_number=value.get('label_number'),
        smsn=value.get('smsn'),
        serial_number=value.get('serial_number'),
        intake_cert=value.get('intake_cert'),
        assigned_team=value.get('assigned_team'),
        sender=value.get('sender'),
        receiver=value.get('receiver'),
        received_date=value.get('received_date'),
        released_date=value.get('released_date'),
        note=value.get('note'),
        status=status,
        row_version=int(value.get('row_version', 1)),
        latest_intake=intake_from_mapping(value.get('latest_intake')),
        intake_count=int(value.get('intake_count', 0) or 0),
        custody_state=value.get('custody_state'),
        custody_event_count=int(value.get('custody_event_count', 0) or 0),
        created_at=value.get('created_at'),
        updated_at=value.get('updated_at'),
    )


__all__ = [
    'CUSTODY_EVENT_FIELDS',
    'INTAKE_FIELDS',
    'KIND_WITHOUT_TEST_CATEGORY',
    'REVISION_SNAPSHOT_FIELDS',
    'SAMPLE_EDITABLE_FIELDS',
    'SAMPLE_KINDS',
    'SNAPSHOT_SCHEMA_VERSION',
    'TEST_CATEGORIES',
    'Sample',
    'SampleCustodyEvent',
    'SampleCustodyEventType',
    'SampleIntake',
    'SampleInventoryFilter',
    'SampleRevision',
    'SampleRevisionEvent',
    'SampleSnapshot',
    'SampleStatus',
    'custody_event_from_mapping',
    'custody_state',
    'intake_from_mapping',
    'sample_from_mapping',
]
