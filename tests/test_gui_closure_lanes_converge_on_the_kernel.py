"""GUI 폐포가 부르는 공유 모듈이 커널에 있는가 (2026-09-07).

■ 무엇을 닫는가

모노레포 GUI 폐포가 `fcc_test_platform` 에 닿는 간선이 **19개** 있었다. 그것은
「GUI 는 platform 배포판을 몰라야 한다」는 설계 판정을 깨는 상태였고, 원인은 언제나
같았다 — **모노레포 로컬 사본이 그 의존을 레인 폐포에서 보이지 않게 하고 있었다.**

    kernel-v0.5.2   test_plan_snapshot        6간선 닫힘   19 → 13
    이 변경         notification_types        8간선
                    measurement_history       5간선        13 →  0

■ ⚠️ 두 모듈의 «근거가 다르다»

    notification_types    platform 레포 안의 소비자가 `domain/models/__init__.py` 의
                          재수출 목록 **하나뿐**이다. 실제로 쓰는 코드가 없다.
                          → 자리가 틀렸다. `test_plan_snapshot` 과 같은 형태.

    measurement_history   platform 레포 안의 `domain/services/rekey_dry_run.py` 가
                          `ConditionFieldSet` 과 해시 계산기 둘을 **실제 로직에서**
                          쓴다. 양쪽이 진짜로 쓴다.
                          → 공유 서비스가 한쪽 배포판에만 있었다.

근거를 뭉뚱그리면 `rekey_dry_run` 의 존재가 판정에서 빠진다. 이 검사는 그 둘을
**따로** 묻는다.

■ ⚠️ `measurement_history` 는 해시 SSOT 다

`condition_hash` 는 measurement identity 다. 같은 구현이 두 자리에 있으면 두 자리가
갈리는 날 **같은 조건이 다른 해시**를 낳는다 — DTO 사본과 달리 이 사본은 데이터를
오염시킨다. 그래서 이 검사는 이름의 존재가 아니라 **해시가 실제로 나오는지**까지
묻는다.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

# 경로를 스스로 댄다 — `test_kernel_imports_standalone.py` 가 먼저 쓴 형태다.
_KERNEL_ROOT = Path(__file__).resolve().parents[1] / 'packages' / 'fcc-test-kernel'
if str(_KERNEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_KERNEL_ROOT))

_PKG = _KERNEL_ROOT / 'fcc_test_kernel'

#: GUI 폐포가 부르던 공유 모듈 → 그 모듈이 닫는 간선 수 (2026-09-07 실측).
#:
#: ⚠️ 하한이다. 파생만 하면 셋이 모두 사라져도 「빈 집합 == 빈 집합」으로 초록이 된다.
_REQUIRED = {
    'domain/models/test_plan_snapshot.py': 6,
    'domain/models/notification_types.py': 8,
    'domain/services/measurement_history.py': 5,
}


class TheSharedModulesAreHere(unittest.TestCase):
    """구조 축 — 대상 import 에 «얹지 않는다».

    최상단에서 import 하면 모듈이 떠나는 바로 그때 파일 전체가 수집 단계에서 죽어
    아래 진단이 한 번도 출력되지 않는다.
    """

    def test_every_required_module_is_here(self) -> None:
        missing = sorted(rel for rel in _REQUIRED if not (_PKG / rel).is_file())
        self.assertEqual(
            [], missing,
            f'GUI 폐포가 부르는 공유 모듈이 이 배포판을 떠났다: {missing}. '
            f'떠나면 그 모듈이 닫던 간선이 되살아나고, 모노레포가 다시 '
            f'fcc_test_platform 에 닿는다.',
        )

    def test_none_of_them_imports_the_consuming_lane(self) -> None:
        """커널이 소비 레인을 import 하면 그것은 커널이 아니다."""
        offenders: list[str] = []
        for rel in sorted(_REQUIRED):
            path = _PKG / rel
            if not path.is_file():
                continue  # 위 시험이 이미 red 다
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Import):
                    roots = [a.name.split('.')[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    roots = [(node.module or '').split('.')[0]]
                else:
                    continue
                for bad in ('fcc_test_platform', 'fcc_test_contracts'):
                    if bad in roots:
                        offenders.append(f'{rel}:{node.lineno} → {bad}')
        self.assertEqual([], offenders, f'커널이 소비 레인을 import 한다: {offenders}')


class TheHashSsotProducesHashes(unittest.TestCase):
    """`measurement_history` 는 이름이 있는 것으로 부족하다 — 값을 내야 한다.

    ⚠️ 여기 적힌 해시는 platform 배포판의 사본이 내던 값이다(2026-09-07, 68건 대조
    불일치 0). 이관이 값을 바꾸지 않았음을 «리터럴로» 못 박는다 — 리터럴이 없으면
    「두 사본이 서로 같다」만 묻게 되고, 둘이 함께 틀려도 초록이다.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from fcc_test_kernel.domain.services import measurement_history as mh
        cls.mh = mh

    def test_normalisation_folds_the_null_likes(self) -> None:
        n = self.mh.normalize_condition_value
        for value in (None, '', '   ', 'nan', 'NaN', float('nan')):
            self.assertIsNone(n(value), f'{value!r} 이 None 으로 안 접힌다')
        self.assertEqual('HT20', n(' HT20 '), '앞뒤 공백이 안 걷힌다')
        self.assertEqual('0', n(0), "0 은 null 이 아니다")

    def test_serialisation_is_key_order_independent(self) -> None:
        s = self.mh.serialize_condition_payload
        self.assertEqual(s({'b': 1, 'a': 2}), s({'a': 2, 'b': 1}))

    #: ⚠️ 입력이 **판별력**을 가져야 한다. 첫 판에서 `sheet_name='S1'` 하나만 썼더니,
    #: payload 의 `normalize_condition_value(sheet_name)` 를 `str(sheet_name)` 로
    #: 바꾸는 주입이 **통과했다** — 그 값은 두 구현에서 같은 결과를 내기 때문이다.
    #: 아래 입력은 정규화를 «거쳐야만» 이 값이 나온다:
    #:   `' S1 '`      앞뒤 공백이 걷혀야 `'S1'` 과 같은 해시가 된다
    #:   `' 2412 '`    값 쪽 공백도 마찬가지
    #:   `'nan'`/None  null-like 가 접혀야 별도의 그 해시가 된다
    _STABLE_HASH_CASES = (
        (' S1 ', {'freq': '2412', 'power': '20'},
         '88d43fe4d86062c28b62ba1c676bab767180e9f441e46dd487404ecbd57b00ab'),
        ('S1', {'freq': ' 2412 ', 'power': '20'},
         '88d43fe4d86062c28b62ba1c676bab767180e9f441e46dd487404ecbd57b00ab'),
        ('S1', {'freq': 'nan', 'power': None},
         '30ccb13f0bec4a4911673cd4dcd07c2e3569d29beb0b9de529535878da3de4dd'),
    )

    def test_the_stable_hash_is_the_value_the_copy_produced(self) -> None:
        field_set = self.mh.ConditionFieldSet(name='u', columns=('freq', 'power'))
        for sheet_name, test_params, expected in self._STABLE_HASH_CASES:
            with self.subTest(sheet_name=sheet_name, test_params=test_params):
                self.assertEqual(
                    expected,
                    self.mh.compute_stable_hash_for_field_set(
                        field_set, sheet_name=sheet_name, test_params=test_params,
                    ),
                    'condition_hash 가 이관 전 값과 다르다 — 저장된 해시와 갈라진다.',
                )

    def test_the_live_hash_is_the_value_the_copy_produced(self) -> None:
        """live 해시는 `row_order` 를 더 받는다 — 그 경로도 따로 못 박는다."""
        field_set = self.mh.ConditionFieldSet(name='u', columns=('freq', 'power'))
        self.assertEqual(
            'a5cdba697c03bcda0b054546545c40668c39218472a01c76230f01b836f9b3cd',
            self.mh.compute_live_hash_for_field_set(
                field_set, sheet_name=' S1 ', row_order=7,
                test_params={'freq': '2412', 'power': '20'},
            ),
        )

    def test_the_field_set_refuses_a_duplicate_column(self) -> None:
        with self.assertRaises(ValueError):
            self.mh.ConditionFieldSet(name='u', columns=('freq', 'freq'))


class TheNotificationTypesKeepTheirContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        from fcc_test_kernel.domain.models import notification_types as nt
        cls.nt = nt

    def test_the_levels_are_json_serialisable_strings(self) -> None:
        """`str` Enum 인 것이 계약이다 — JSON/log 직렬화가 그것에 얹혀 있다."""
        for level in self.nt.NotificationLevel:
            self.assertIsInstance(level, str)
        self.assertEqual('critical', self.nt.NotificationLevel.CRITICAL)

    def test_the_cooldown_exemption_set_is_what_it_was(self) -> None:
        """⚠️ `TEST_FAILED` 가 «의도적으로» 빠져 있다 — 그 부재가 계약이다."""
        e = self.nt.EventTypes
        self.assertEqual(
            {e.SESSION_STARTED, e.SESSION_COMPLETED, e.SESSION_FAILED,
             e.HARDWARE_ERROR, e.PROGRESS_MILESTONE},
            set(e.NO_COOLDOWN),
        )
        self.assertNotIn(
            e.TEST_FAILED, e.NO_COOLDOWN,
            'TEST_FAILED 가 면제 목록에 들어왔다 — 동일 세션 내 연속 실패가 '
            'cooldown 없이 전부 발송된다(spam).',
        )

    def test_an_event_defaults_its_timestamp_and_details(self) -> None:
        event = self.nt.NotificationEvent(
            event_type=self.nt.EventTypes.TEST_FAILED,
            level=self.nt.NotificationLevel.ERROR,
            title='t', message='m',
        )
        self.assertEqual({}, event.details)
        self.assertIsNotNone(event.timestamp)


if __name__ == '__main__':
    unittest.main()
