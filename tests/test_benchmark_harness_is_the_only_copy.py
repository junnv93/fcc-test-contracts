"""벤치 퍼센타일 SSOT 가 **사본이 아니라 배포판**인가 (2026-09-03).

**왜 이 봉인이 있는가.** 2026-09-03 까지 `benchmark_harness` 는 두 벌이었고,
두 사본이 byte-identical 이라 아무 검사도 붉지 않았다. 그런데 provider 저장소의
`CLAUDE.md` 가 벤치 퍼센타일 SSOT 를 **그 모듈에** 걸어 두었다 —
**사본에 SSOT 를 거는 것은 SSOT 가 아니다.**

⚠️ 그리고 그때 그 사본은 **아무도 소비할 수 없었다**: 이 레인의 `scripts/` 는
배포 대상이 아니다(`include = ["fcc_test_contracts*"]`). 즉 「공유」가 아니라
「복사」였고, 갈라지지 않은 것은 시간이 안 지났기 때문이지 구조 때문이 아니다.

이 봉인이 붙잡는 성질은 하나다 — **이 레인 안에 두 벌이 다시 생기지 않는다.**

⚠️ **다른 저장소의 사본은 이 봉인이 볼 수 없다.** 그것은 이 검사의 축이 아니고,
그 사실을 숨기지 않는다: 형제 레인의 전환은 그쪽 웨이브가 하고, 그때까지
그쪽 사본은 정당하게 남는다(먼저 지우면 그 사이 그쪽 벤치가 전부 죽는다).
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CANONICAL = _REPO_ROOT / 'fcc_test_contracts' / 'common' / 'benchmark_harness.py'

#: 이 이름들이 SSOT 의 내용이다 — provider 저장소 `CLAUDE.md` 가 지목한 것들.
_SSOT_NAMES = ('percentile', 'measure_latency_us_robust', 'LatencyBudget')


class TestTheCanonicalCopyIsShipped(unittest.TestCase):
    def test_it_lives_inside_the_distributed_package(self):
        self.assertTrue(
            _CANONICAL.is_file(),
            f'{_CANONICAL} 가 없다 — 배포되는 자리에 없으면 소비 레인이 못 쓴다.',
        )

    def test_it_is_importable_from_the_distributed_name(self):
        from fcc_test_contracts.common import benchmark_harness

        for name in _SSOT_NAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    hasattr(benchmark_harness, name),
                    f'{name} 이 없다 — SSOT 가 가리키는 이름이 사라졌다.',
                )

    def test_the_percentile_is_nearest_rank_not_interpolated(self):
        """SSOT 의 **내용**을 잰다 — 이름만 있고 의미가 바뀌면 소용없다.

        nearest-rank 는 표본에 실재하는 값을 돌려준다. 보간판은 그러지 않는다.
        """
        from fcc_test_contracts.common.benchmark_harness import percentile

        samples = [1.0, 2.0, 3.0, 4.0]
        for q in (0.5, 0.95, 0.99):
            with self.subTest(q=q):
                self.assertIn(
                    percentile(samples, q), samples,
                    'percentile 이 표본에 없는 값을 돌려준다 — 보간판으로 바뀌었다.',
                )


class TestThereIsExactlyOneCopyInThisRepository(unittest.TestCase):
    """⚠️ 두 벌이 다시 생기면 red. **byte-identical 여부를 묻지 않는다** —
    같아 보이는 두 벌이 정확히 2026-09-03 이전의 상태이고, 그것이 문제였다."""

    def test_no_other_module_in_this_repo_defines_the_ssot_names(self):
        offenders: list[str] = []
        for path in _REPO_ROOT.rglob('*.py'):
            if '__pycache__' in path.parts or '.git' in path.parts:
                continue
            if path.resolve() == _CANONICAL.resolve():
                continue
            if path.name != 'benchmark_harness.py':
                continue
            offenders.append(str(path.relative_to(_REPO_ROOT)))
        self.assertEqual(
            [], offenders,
            '이 저장소에 benchmark_harness 사본이 또 있다 — SSOT 가 둘이 된다:\n  '
            + '\n  '.join(offenders),
        )

    def test_the_canonical_module_defines_the_ssot_names_itself(self):
        """비-공허성 — 정본이 그 이름들을 **직접 정의**해야 위 검사가 의미를 갖는다.

        정본이 다른 곳에서 재수출만 하고 있으면 「사본이 하나」는 참이지만
        SSOT 는 여전히 다른 데 있다.
        """
        tree = ast.parse(_CANONICAL.read_text(encoding='utf-8'))
        defined = {
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        for name in _SSOT_NAMES:
            with self.subTest(name=name):
                self.assertIn(
                    name, defined,
                    f'{name} 이 정본에서 정의되지 않는다 — 재수출이면 SSOT 가 다른 곳이다.',
                )


if __name__ == '__main__':  # pragma: no cover
    unittest.main(verbosity=2)
