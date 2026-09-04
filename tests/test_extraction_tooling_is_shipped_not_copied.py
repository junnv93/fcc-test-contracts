"""추출 도구의 알맹이가 **배포되는 자리**에 있는가 (2026-09-05).

**왜 이 봉인이 있는가.** 소비 레인(`fcc-test-platform`)의
`scripts/platform_extraction_runner.py` 는 이 레인의 도구 둘을 부르는데, 배송된 상자에서
**import 조차 되지 않았다**(실측 2026-09-04, 공급 폐포 게이트 계급 B). 원인은 의존성
선언이 아니라 **도달성**이다: 알맹이가 `scripts/` 에 있었고, `scripts/` 는 휠에 실리지
않는다.

모노레포의 매니페스트가 그 자리를 이미 이름 붙여 놨다 —

    *"세 개의 platform 박스 시험 모듈이 `check_extraction_import_boundaries` 를 맨
    최상위 이름으로 import 한다 … **platform conftest 는 자기 `scripts/` 만 얹을 수
    있고 형제의 것은 못 얹는다.**"*

그 문장이 적은 답(형제의 `scripts/` 를 PYTHONPATH 에 얹는다)은 **스테이징 시점의
우회**다. 배송 상자에는 형제 디렉터리가 없으므로 거기서는 성립하지 않는다.

⭐ **이 봉인이 붙잡는 성질은 하나다 — 알맹이가 `scripts/` 로 되돌아가지 않는다.**
그리고 그 근거(「`scripts/` 는 휠에 실리지 않는다」)를 산문으로 적는 대신 `pyproject.toml`
에서 **파생해서 다시 잰다**. 누군가 `include` 를 넓히는 날 이 봉인의 전제가 바뀌었다는
것이 그 자리에서 드러난다.

`tests/test_benchmark_harness_is_the_only_copy.py` 와 같은 계급의 봉인이고, 같은 사유다.
"""
from __future__ import annotations

import ast
from pathlib import Path
import tomllib
import unittest


_REPO_ROOT = Path(__file__).resolve().parents[1]

#: 진입점 → 그 알맹이가 사는 배포 모듈 → 소비자가 실제로 부르는 이름.
#:
#: ⚠️ 이름은 **소비자가 부르는 것**을 적는다. `main` 만 확인하면 CLI 는 살아 있는데
#: 라이브러리 표면이 사라진 상태가 통과로 읽힌다 — 그리고 그것이 정확히 소비 레인의
#: 러너가 필요로 하는 표면이다.
_TOOLS = {
    'scripts/check_extraction_import_boundaries.py': (
        'fcc_test_contracts.extraction_import_boundaries',
        ('check_import_boundaries', 'check_dependency_resolution', 'lane_choices', 'main'),
    ),
    'scripts/prepare_headless_extraction_package.py': (
        'fcc_test_contracts.extraction_package',
        ('build_extraction_plan', 'stage_extraction_package', 'main'),
    ),
}

#: 진입점이 「얇다」의 뜻: 자기 이름을 하나도 정의하지 않는다.
#:
#: ⚠️ 줄 수 상한이 아니라 **정의 개수 0** 으로 잰다. 줄 수는 주석을 지우면 통과하고,
#: 이 봉인이 막으려는 것은 짧은 파일이 아니라 **로직이 다시 여기 사는 것**이다.
_ENTRY_POINT_DEFINES_NOTHING = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _pyproject() -> dict:
    return tomllib.loads((_REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))


class TestTheScriptsDirectoryIsStillNotShipped(unittest.TestCase):
    """이 봉인의 **전제**를 먼저 잰다 — 전제가 바뀌면 나머지가 무의미해진다."""

    def test_the_wheel_include_patterns_do_not_cover_scripts(self):
        patterns = _pyproject()['tool']['setuptools']['packages']['find']['include']
        self.assertTrue(patterns, 'include 패턴이 비었다 — 파생할 근거가 없다')
        covered = [p for p in patterns if p.rstrip('*').rstrip('.').startswith('scripts')]
        self.assertEqual(
            covered, [],
            'pyproject 의 packages.find.include 가 이제 scripts/ 를 덮는다. 그러면 이 파일의 '
            '봉인 전제(「scripts 는 휠에 실리지 않는다」)가 바뀐 것이다 — 그 결정을 여기서 '
            '다시 적고, 「scripts 에 __init__.py 가 의도적으로 없다」가 load-bearing 인 자리들'
            '(contract_cli.sibling_module · 실행 축 PYTHONPATH 파생)을 함께 판정하라.',
        )


class TestEveryExtractionToolShipsItsCore(unittest.TestCase):
    def test_each_entry_point_exists_and_defines_nothing(self):
        for script in sorted(_TOOLS):
            with self.subTest(script=script):
                path = _REPO_ROOT / script
                self.assertTrue(path.is_file(), f'{script} 가 없다')
                tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
                defined = [
                    node.name for node in tree.body
                    if isinstance(node, _ENTRY_POINT_DEFINES_NOTHING)
                ]
                self.assertEqual(
                    defined, [],
                    f'{script} 가 자기 이름 {defined} 을 정의한다 — 로직이 다시 여기 살고 '
                    f'있다는 뜻이고, 휠이 나르지 못하는 자리다. 알맹이는 '
                    f'{_TOOLS[script][0]} 로 옮겨라.',
                )

    def test_each_core_lives_inside_the_distributed_package(self):
        for script, (module, _names) in sorted(_TOOLS.items()):
            with self.subTest(module=module):
                path = _REPO_ROOT / Path(*module.split('.')).with_suffix('.py')
                self.assertTrue(
                    path.is_file(),
                    f'{path} 가 없다 — 배포되는 자리에 없으면 소비 레인이 못 쓴다 '
                    f'({script} 의 알맹이다).',
                )

    def test_each_core_is_importable_from_the_distributed_name(self):
        """소비자가 실제로 부르는 표면을 잰다 — 이름만 있고 표면이 비면 소용없다."""
        import importlib

        for module, names in sorted(v for v in _TOOLS.values()):
            with self.subTest(module=module):
                imported = importlib.import_module(module)
                missing = [name for name in names if not hasattr(imported, name)]
                self.assertEqual(
                    missing, [],
                    f'{module} 에 {missing} 이 없다 — 소비 레인의 추출 러너가 부르는 '
                    f'이름이고, 사라지면 그 상자에서 다시 import 되지 않는다.',
                )

    def test_the_two_tools_do_not_each_derive_the_operating_root(self):
        """루트 파생이 **한 벌**인지 본다 — 열두 줄짜리 사본이 갈라지던 자리다.

        `operating_repository_root` 의 사유(설치본에서 `parents[1]` 은 `site-packages`
        이고 그 상태가 「경로가 맞다」와 같은 모양이라는 것)는 실측으로 배운 것이라,
        두 벌이 되면 한쪽이 그 사유를 잃는다.
        """
        offenders: list[str] = []
        for module, _names in _TOOLS.values():
            path = _REPO_ROOT / Path(*module.split('.')).with_suffix('.py')
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.endswith('repository_root'):
                    offenders.append(f'{module}:{node.lineno}:{node.name}')
        self.assertEqual(
            offenders, [],
            '추출 도구가 「지금 다루는 저장소」 파생을 자기 안에서 다시 정의한다: '
            f'{offenders}. SSOT 는 fcc_test_contracts.common.tree_artifacts.'
            'operating_repository_root 이고, 그 함수의 docstring 이 왜 모듈 위치에서 '
            '파생하면 안 되는지를 실측과 함께 적는다.',
        )


if __name__ == '__main__':
    unittest.main()
