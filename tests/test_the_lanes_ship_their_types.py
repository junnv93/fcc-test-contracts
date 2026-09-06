"""배포판이 «타입이 있다»고 말하는가 — PEP 561 마커 (2026-09-06).

⚠️ **이 봉인이 존재하는 이유는 「없으면 조용하다」이다.** 마커가 빠지면 소비 레인의
mypy 는 이 패키지를 미타입으로 보고 import 전체를 ``Any`` 로 만든다. 그러면:

  · 이 레인의 타입 선언이 **하나도 검사되지 않는다**
  · 소비 레인의 mypy 는 **초록**이다 (검사할 것이 없으므로)
  · platform 의 ``mypy.ini`` 는 ``ignore_missing_imports = True`` 라
    ``[import-untyped]`` 경고**조차** 안 뜬다

즉 마커 삭제는 게이트를 끄는 변경인데 **아무 신호도 내지 않는다.** 실측 2026-09-06,
소비 레인에서 같은 코드에 대해::

    py.typed 없음   revealed: Any            잘못된 대입 0건 · 없는 키 0건
    py.typed 있음   revealed: OperationSpec  [assignment] · [typeddict-item]

⚠️ 그리고 **선언과 실물 둘 다** 물어야 한다. 파일만 있고 ``package-data`` 에 없으면
휠에 안 실리고, 선언만 있고 파일이 없으면 빌드가 조용히 통과한다. 어느 쪽도 트리에서는
안 보인다 — 소비자만 안다.
"""
from __future__ import annotations

import pathlib
import tomllib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]

#: (배포판 이름, pyproject 경로, 패키지 디렉터리) — **경로를 세지 말고 선언에서 파생한다.**
DISTRIBUTIONS = (
    ('fcc-test-contracts', REPO / 'pyproject.toml', REPO / 'fcc_test_contracts'),
    ('fcc-test-kernel', REPO / 'packages/fcc-test-kernel/pyproject.toml',
     REPO / 'packages/fcc-test-kernel/fcc_test_kernel'),
)


def _package_data(pyproject: pathlib.Path) -> dict[str, list[str]]:
    config = tomllib.loads(pyproject.read_text(encoding='utf-8'))
    return config.get('tool', {}).get('setuptools', {}).get('package-data', {})


class TestBothDistributionsShipTheMarker(unittest.TestCase):
    """두 배포판 «모두». 하나만 넣으면 절반이다."""

    def test_the_marker_file_exists(self) -> None:
        missing = [name for name, _, pkg in DISTRIBUTIONS if not (pkg / 'py.typed').is_file()]
        self.assertEqual(
            [], missing,
            f'PEP 561 마커 파일이 없다: {missing}. 없으면 이 배포판의 타입 선언은 '
            '소비 레인에서 «투명»하고, 그 사실이 경고 없이 조용히 성립한다.',
        )

    def test_the_marker_is_declared_as_package_data(self) -> None:
        """⚠️ 파일이 있어도 선언에 없으면 **휠에 안 실린다** — 트리에서는 안 보인다."""
        undeclared = []
        for name, pyproject, pkg in DISTRIBUTIONS:
            patterns = _package_data(pyproject).get(pkg.name, [])
            if 'py.typed' not in patterns:
                undeclared.append(f'{name}: [tool.setuptools.package-data]."{pkg.name}" = {patterns}')
        self.assertEqual(
            [], undeclared,
            '마커 파일은 있는데 `package-data` 선언에 없다 — 휠에 안 실린다:\n  '
            + '\n  '.join(undeclared),
        )

    def test_every_distribution_in_this_repo_is_covered(self) -> None:
        """이빨 — 새 배포판이 생기면 이 표에 넣어라. 안 넣으면 그 배포판만 조용히 투명해진다."""
        found = {REPO / 'pyproject.toml', *(REPO / 'packages').glob('*/pyproject.toml')}
        declared = {p for _, p, _ in DISTRIBUTIONS}
        self.assertEqual(
            found, declared,
            f'이 저장소의 pyproject 집합이 이 표와 다르다.\n'
            f'  표에 없음: {sorted(str(p.relative_to(REPO)) for p in found - declared)}\n'
            f'  사라짐   : {sorted(str(p.relative_to(REPO)) for p in declared - found)}',
        )


if __name__ == '__main__':
    unittest.main()
