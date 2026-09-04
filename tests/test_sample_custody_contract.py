"""시료 custody 축의 커널 계약 (ADR-0002, 2026-09-04).

플랫폼 쪽 시험은 DB 왕복을 본다. 여기서는 **커널이 혼자 지는 약속**만 본다:
어휘가 도메인에서 파생되는가, 표면 분해 규칙을 지키는가, 보유 상태 규칙이 한 곳에만
사는가.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

# ⚠️ 이 상자는 커널을 **설치하지 않는다** — CI 도 pre-push 훅도
# `pip install -e '.[test,oidc]'` 로 레포 루트만 얹는다("상자가 자족적인가"를 묻는
# 설치 방식이고, 커널을 끼워 넣으면 그 질문이 흐려진다). 그래서 커널을 읽는 시험은
# 경로를 스스로 댄다 — `test_kernel_imports_standalone.py` 가 먼저 쓴 형태다.
# 이것을 빼면 CI 에서 **collection error** 가 나고 lane_check 가 새 실패로 읽는다
# (실측 2026-09-04, run 33856873484).
_KERNEL_ROOT = Path(__file__).resolve().parents[1] / 'packages' / 'fcc-test-kernel'
if str(_KERNEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_KERNEL_ROOT))

from fcc_test_kernel.application.central_contract import api_contracts
from fcc_test_kernel.application.central_contract import surface_samples
from fcc_test_kernel.domain.models.sample_inventory import (
    CUSTODY_EVENT_FIELDS,
    SAMPLE_EDITABLE_FIELDS,
    SAMPLE_KINDS,
    TEST_CATEGORIES,
    SampleCustodyEvent,
    SampleCustodyEventType,
    custody_event_from_mapping,
    custody_state,
    sample_from_mapping,
)
from fcc_test_kernel.domain.services.sample_inventory_policy import (
    SampleInvalidCustodyEvent,
    SampleUnknownField,
    custody_events_projection,
    validate_custody_event,
)


class TestTheContractIsDerivedFromTheDomain(unittest.TestCase):
    """PM · 시험원 · API · export 가 서로 다른 컬럼 목록을 기를 수 없어야 한다."""

    def test_new_classification_fields_reach_the_api_schema_without_hand_editing(self):
        properties = api_contracts.PLATFORM_API_SCHEMAS['SampleCreateRequest']['properties']
        for field in ('sample_kind', 'sample_description'):
            self.assertIn(field, properties)
            self.assertIn(field, SAMPLE_EDITABLE_FIELDS)

    def test_custody_request_properties_are_exactly_the_domain_fields(self):
        schema = api_contracts.PLATFORM_API_SCHEMAS['SampleCustodyEventRequest']
        self.assertEqual(tuple(schema['properties']), CUSTODY_EVENT_FIELDS)
        self.assertEqual(schema['required'], ['event_type'])
        self.assertFalse(schema['additionalProperties'])

    def test_event_type_is_the_only_closed_vocabulary_on_the_wire(self):
        properties = api_contracts.PLATFORM_API_SCHEMAS[
            'SampleCustodyEventRequest']['properties']
        self.assertEqual(
            properties['event_type']['enum'],
            [member.value for member in SampleCustodyEventType],
        )
        # 나머지는 자유 텍스트다 — 실제 데이터의 날짜가 '2025/09/30' 과 '10/21' 로
        # 섞여 들어오고, 사유는 문장이다.
        for field in CUSTODY_EVENT_FIELDS:
            if field != 'event_type':
                self.assertNotIn('enum', properties[field], field)

    def test_the_classification_vocabulary_is_not_a_database_check(self):
        """결정 3 — 값 제한은 애플리케이션 경계가 한다. 그 경계가 이 튜플이다."""
        self.assertEqual(SAMPLE_KINDS, ('Device', 'Accessory'))
        # RF 엑셀 export 가 이 철자로 시트를 가른다.
        self.assertEqual(TEST_CATEGORIES, ('Conduction', 'Radiation'))

    def test_every_custody_operation_is_declared_on_the_samples_surface(self):
        """표면 경계는 표 종류가 아니라 operation 표면이다 (모듈 docstring)."""
        for operation in ('list_sample_intakes', 'list_sample_custody_events',
                          'append_sample_custody_event', 'delete_sample_custody_event'):
            self.assertIn(operation, surface_samples.ROUTES)
            self.assertIn(operation, surface_samples.PERMISSIONS)
            self.assertIn(operation, surface_samples.OPERATIONS)
            path = surface_samples.ROUTES[operation][1]
            self.assertTrue(
                any(path.startswith(prefix) for prefix in surface_samples.SURFACE_PREFIXES),
                f'{operation} 의 경로가 이 표면이 소유한 prefix 밖이다: {path}',
            )

    def test_writing_custody_needs_the_sample_write_permission_and_reading_does_not(self):
        self.assertEqual(
            surface_samples.PERMISSIONS['append_sample_custody_event'],
            'platform:sample-write')
        self.assertEqual(
            surface_samples.PERMISSIONS['delete_sample_custody_event'],
            'platform:sample-write')
        self.assertEqual(
            surface_samples.PERMISSIONS['list_sample_custody_events'], 'platform:read')
        self.assertEqual(
            surface_samples.PERMISSIONS['list_sample_intakes'], 'platform:read')

    def test_there_is_no_patch_route_for_a_custody_event(self):
        """정정은 수정이 아니라 삭제다 — 수정 경로가 생기면 그 결정이 무너진다."""
        methods = {method for operation, (method, path)
                   in surface_samples.ROUTES.items()
                   if 'custody-events' in path}
        self.assertEqual(methods, {'GET', 'POST', 'DELETE'})


class TestCustodyStateHasExactlyOneHome(unittest.TestCase):
    def test_the_most_recent_event_decides(self):
        self.assertEqual(custody_state({'event_type': 'received'}), 'in_custody')
        self.assertEqual(custody_state({'event_type': 'released'}), 'released')

    def test_no_event_is_unknown_not_released(self):
        """기존 시료는 사건 없이 넘어온다 (결정 9). 지어내지 않는다."""
        self.assertIsNone(custody_state(None))
        self.assertIsNone(custody_state({'event_type': None}))

    def test_it_reads_a_value_object_and_a_mapping_the_same_way(self):
        event = SampleCustodyEvent(event_type=SampleCustodyEventType.RELEASED)
        self.assertEqual(custody_state(event), custody_state(event.as_dict()))


class TestValidation(unittest.TestCase):
    def test_event_type_is_required(self):
        with self.assertRaises(SampleInvalidCustodyEvent):
            validate_custody_event({'occurred_on': '2025-10-23'})

    def test_a_third_event_type_is_refused(self):
        with self.assertRaises(SampleInvalidCustodyEvent):
            validate_custody_event({'event_type': 'lent'})

    def test_a_field_outside_the_contract_is_refused(self):
        with self.assertRaises(SampleUnknownField):
            validate_custody_event({'event_type': 'received', 'label_number': 'X'})

    def test_absent_optional_fields_become_explicit_nulls(self):
        value = validate_custody_event({'event_type': 'released'})
        self.assertEqual(set(value), set(CUSTODY_EVENT_FIELDS))
        self.assertIsNone(value['counterparty'])


class TestOrdering(unittest.TestCase):
    def test_display_order_is_record_order_not_the_hand_written_date(self):
        """occurred_on 은 사람이 적는 자유 텍스트라 정렬 키로 신뢰할 수 없다.

        뒤늦게 적은 과거 사건도 적힌 그대로 보여야 하므로 created_at 이 1차 기준이다.
        """
        events = [
            {'id': 'a', 'created_at': '2025-11-04T00:00:00Z', 'occurred_on': '10/21'},
            {'id': 'b', 'created_at': '2025-11-05T00:00:00Z', 'occurred_on': '2025-09-30'},
        ]
        self.assertEqual([e['id'] for e in custody_events_projection(events)], ['b', 'a'])

    def test_it_accepts_value_objects_too(self):
        events = custody_events_projection([
            SampleCustodyEvent(id='a', created_at='2025-01-01T00:00:00Z'),
        ])
        self.assertEqual(events[0]['id'], 'a')
        self.assertEqual(events[0]['event_type'], 'received')


class TestMappers(unittest.TestCase):
    def test_custody_event_round_trips(self):
        event = custody_event_from_mapping({
            'id': 'e1', 'event_type': 'released', 'occurred_on': '2025-10-23',
            'counterparty': '김용태 프로님', 'reason': '임시 반출',
        })
        self.assertIs(event.event_type, SampleCustodyEventType.RELEASED)
        self.assertEqual(event.as_dict()['counterparty'], '김용태 프로님')

    def test_none_maps_to_none(self):
        self.assertIsNone(custody_event_from_mapping(None))

    def test_sample_carries_the_derived_custody_summary(self):
        sample = sample_from_mapping({
            'id': 's1', 'project_id': 'p1', 'sample_kind': 'Accessory',
            'sample_description': 'SM-F968U1_Dummy Batt',
            'custody_state': 'in_custody', 'custody_event_count': 6,
        })
        self.assertEqual(sample.sample_kind, 'Accessory')
        self.assertEqual(sample.custody_event_count, 6)
        # 파생값은 편집 필드가 아니므로 리비전 스냅샷 축에 들어가지 않는다.
        self.assertNotIn('custody_state', SAMPLE_EDITABLE_FIELDS)


if __name__ == '__main__':
    unittest.main()
