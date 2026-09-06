"""테스트 플랜 도메인의 세 모델이 **한 배포판**에 있는가 (2026-09-06).

**무엇이 있었나.** 한 도메인의 세 모델이 두 배포판에 갈려 있었다:

    test_plan(Snapshot)      kernel ❌   platform ✅   ← GUI 가 부르던 그것
    published_test_plan      kernel ✅   platform ❌
    test_plan_authoring      kernel ✅   platform ❌

그 갈라짐이 **초록으로 보이던** 이유: 모노레포가 `src/domain/models/test_plan.py`
로컬 사본을 들고 있어서 GUI→platform 간선이 레인 폐포에 나타나지 않았다. 사본을
걷어내자(모노레포 PR #789) 드러났다. 분류 시점(커널 3단계, 2026-09-03)에 GUI 는
**이미 7개월째** 그 모델을 쓰고 있었지만, 사본이 그 소비를 가리고 있었다.

**이 검사가 지키는 것.** 셋이 여기 함께 있다는 사실. 하나라도 이 배포판을 떠나면
같은 갈라짐이 다시 생기고, 그때는 사본이 없으므로 소비 레인이 붉어진다 — 그러나
붉어지는 자리가 **여기가 아니다**. 이 검사는 그것을 원인 자리에서 잡는다.

⚠️ **집합을 선언에서 파생한다.** 가족 구성원을 손으로 적으면 넷째가 생긴 날 조용해진다.
`_FAMILY_PREFIX` 로 디렉터리에서 파생하되, **하한**(반드시 있어야 하는 셋)을 따로
못 박는다 — 파생만 하면 셋이 모두 사라져도 「빈 집합이 빈 집합과 같다」로 초록이 된다
(공집합형 봉인의 함정).

⚠️ 이 검사는 소비 레인(`fcc_test_platform`)의 트리를 **보지 않는다**. 커널이 그
트리에 기대면 그것은 커널이 아니다 — `test_kernel_imports_standalone` 과 같은 규율.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

# 경로를 스스로 댄다 — `test_kernel_imports_standalone.py` 가 먼저 쓴 형태이고
# `test_sample_custody_contract.py` 가 따른다. 커널은 루트 pyproject 가 설치하지 않는다.
_KERNEL_ROOT = Path(__file__).resolve().parents[1] / 'packages' / 'fcc-test-kernel'
if str(_KERNEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_KERNEL_ROOT))

# ⚠️ 모델을 **여기서 import 하지 않는다.** 구조 축(가족 존재 · 금지된 이름 · pandas
# 부재)은 파일시스템과 AST 만 보면 답할 수 있고, 그 축이 최상단 import 에 얹히면
# 정작 그 축이 붉어야 할 때 파일 전체가 수집 단계에서 죽는다 — 그러면 아래에 적은
# 진단 문장이 한 번도 출력되지 않는다. 실측(2026-09-06): 「가족원이 떠난다」와
# 「pandas 를 들인다」 두 주입이 `1 failed` 가 아니라 `1 error` 로 나왔다.
# 같은 규율: `test_a_seal_that_could_not_run_is_not_a_verdict.py`.
# 모델 import 는 동작 축(`TestPlanSnapshotBehaviour`)이 자기 안에서 한다.

_MODELS_DIR = _KERNEL_ROOT / 'fcc_test_kernel' / 'domain' / 'models'
_FAMILY_PREFIX = 'test_plan'

# 하한 — 2026-09-06 이관으로 셋이 모두 여기 있다. 파생 집합이 이것을 «포함»해야 한다.
_REQUIRED = frozenset({
    'test_plan_snapshot',
    'test_plan_authoring',
    'published_test_plan',
})


def _family() -> frozenset[str]:
    """`domain/models/` 에서 테스트 플랜 가족을 파생한다."""
    return frozenset(
        p.stem
        for p in _MODELS_DIR.glob('*.py')
        if p.stem != '__init__' and _FAMILY_PREFIX in p.stem
    )


class TestPlanFamilyLivesInOneDistribution(unittest.TestCase):

    def test_every_required_member_is_here(self) -> None:
        missing = sorted(_REQUIRED - _family())
        self.assertEqual(
            [], missing,
            f'테스트 플랜 도메인의 모델이 이 배포판을 떠났다: {missing}. '
            f'한 도메인의 모델이 두 배포판에 갈리면 소비 레인의 폐포가 거짓이 된다 '
            f'(2026-09-06 이관이 닫은 상태). 옮기려면 이 하한을 함께 판정하라.',
        )

    def test_the_reserved_name_stays_empty(self) -> None:
        """`test_plan.py` 는 «쓰지 않기로 한» 이름이다 (bounded context 구별)."""
        self.assertFalse(
            (_MODELS_DIR / 'test_plan.py').exists(),
            '`domain/models/test_plan.py` 가 생겼다. 이 패키지는 그 이름을 쓰지 않는다 — '
            '런타임 스냅샷은 `test_plan_snapshot.py`, authoring 도메인은 '
            '`test_plan_authoring.py` 다. `test_plan_authoring` 의 docstring 「파일명 결정」 참조.',
        )

    def test_the_family_is_pandas_free(self) -> None:
        """도메인 순수 — 가족 전원이 pandas 를 import 하지 않는다.

        AST 로 묻는다. 줄 단위 스캔은 여러 줄로 쪼갠 import 를 못 본다.
        """
        offenders: list[str] = []
        for name in sorted(_family()):
            tree = ast.parse((_MODELS_DIR / f'{name}.py').read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = [a.name.split('.')[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    roots = [(node.module or '').split('.')[0]]
                else:
                    continue
                if 'pandas' in roots:
                    offenders.append(f'{name}.py:{node.lineno}')
        self.assertEqual([], offenders, f'도메인 모델이 pandas 를 import 한다: {offenders}')


class TestPlanSnapshotBehaviour(unittest.TestCase):
    """이관된 모델의 동작 — 옮기면서 잃은 것이 없음을 여기서 묻는다.

    ⚠️ 이 동작을 봉인하던 시험(`tests/test_test_plan_page_invariants.py`)은 **모노레포에**
    있고 이 저장소로 오지 않았다. 그쪽은 GUI 어댑터와의 3-site 동치를 묻는다 — 그것은
    GUI 가 있는 자리에서만 물을 수 있다. 여기서는 모델 «단독»의 계약만 봉인한다.
    """

    @classmethod
    def setUpClass(cls) -> None:
        # ⚠️ 알리아스로 받는다 — 이름이 `Test` 로 시작해 pytest 가 시험 클래스로
        # 수집하려다 `PytestCollectionWarning` 을 낸다.
        from fcc_test_kernel.domain.models.test_plan_snapshot import (
            NULL_DISPLAY_TOKENS,
            TestPlanSnapshot as Snapshot,
            _normalize_display_value,
        )
        cls.tokens = NULL_DISPLAY_TOKENS
        cls.snapshot_cls = Snapshot
        cls.normalize = staticmethod(_normalize_display_value)

    def test_stringified_null_sentinels_render_empty(self) -> None:
        """토큰 셋이 «기능상 필수»인 이유: `pandas.NA` 는 ``!=`` 로 안 잡힌다."""
        self.assertEqual({'nan', '<NA>', 'NaT'}, set(self.tokens))
        for token in sorted(self.tokens):
            self.assertEqual('', self.normalize(token), f'{token!r} 이 빈 문자열로 안 접힌다')

    def test_real_null_likes_render_empty(self) -> None:
        self.assertEqual('', self.normalize(None))
        self.assertEqual('', self.normalize(float('nan')))

    def test_ordinary_values_survive(self) -> None:
        self.assertEqual('0', self.normalize(0))
        self.assertEqual('', self.normalize(''))
        self.assertEqual('nan_but_longer', self.normalize('nan_but_longer'))

    def test_from_dataframe_is_duck_typed_and_keeps_row_order(self) -> None:
        """pandas 없이 — ``.columns`` / ``.to_dict`` / ``.index`` 만 쓴다."""
        class FakeFrame:
            columns = ('name', 'value')
            index = (7, 3)

            def to_dict(self, orient: str) -> list[dict[str, object]]:
                assert orient == 'records'
                return [{'name': 'a', 'value': float('nan')}, {'name': 'b', 'value': 2}]

        snapshot = self.snapshot_cls.from_dataframe(FakeFrame())
        self.assertEqual((7, 3), snapshot.row_orders, 'Excel 행 순서가 사라졌다')
        self.assertEqual(('name', 'value'), snapshot.columns)
        self.assertEqual((('a', ''), ('b', '2')), snapshot.display_rows)
        self.assertEqual(2, snapshot.total_tests)
        self.assertEqual(2, len(snapshot), '__len__ 이 total_tests 를 안 돌려준다')


if __name__ == '__main__':
    unittest.main()
