"""`fcc-test-kernel` 의 모든 모듈이 **홀로** import 되는가 (2026-09-03).

**왜 이 검사가 폐포 게이트보다 강한가.**

소비 레인의 폐포 게이트(`fcc-test-platform:scripts/check_shared_kernel_closure.py`)는
**import 축**이다. 그 축이 볼 수 없는 의존이 있다:

    패키지 데이터        importlib.resources 로 읽는 파일
    패키징 누락          pyproject 가 안 싣는 하위 패키지
    접두사 재작성 누락    옮기면서 안 고친 import 하나

⚠️ **실측 2026-09-03 — 셋 중 첫째가 실제로 터졌다.** 2단계에서 코드 31파일을
옮기고 `domain/models/decision_catalogue.json` 을 두고 왔더니 15개 모듈이
``ReferenceCatalogError: decision catalogue resource is unavailable`` 로 죽었다.
폐포는 그 간선을 **구조적으로** 볼 수 없다 — 그것은 import 문이 아니다.

축을 하나 더 만드는 대신(`.claude/rules/check-axis-blindness.md` §처방:
*「구분하는 검사를 더하라」가 아니라 「구분되게 만들어라」*) **더 강한 오라클**을
세운다: 실제로 import 해 본다. 셋이 한 번에 붉는다.

⚠️ 그리고 이 검사는 **소비 레인의 트리 없이** 돌아야 한다. 커널이 그 트리에
기대면 그것은 커널이 아니라 그 레인의 일부다 — `sys.path` 를 커널 하나로 좁혀
그 사실을 강제한다.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

_KERNEL_ROOT = Path(__file__).resolve().parents[1] / 'packages' / 'fcc-test-kernel'
_PACKAGE = _KERNEL_ROOT / 'fcc_test_kernel'


def _modules() -> list[str]:
    return sorted(
        str(p.relative_to(_KERNEL_ROOT))[:-3].replace('/', '.').removesuffix('.__init__')
        for p in _PACKAGE.rglob('*.py')
        if '__pycache__' not in p.parts
    )


class TestTheKernelIsPresent(unittest.TestCase):
    """⚠️ 비-공허성 — 모듈이 0개면 아래 검사가 「전부 통과」한다."""

    def test_the_kernel_ships_modules(self):
        self.assertTrue(_PACKAGE.is_dir(), f'{_PACKAGE} 가 없다')
        self.assertGreater(len(_modules()), 0, '커널에 모듈이 하나도 없다')


class TestEveryModuleImportsStandalone(unittest.TestCase):
    def test_every_kernel_module_imports_with_only_the_kernel_on_the_path(self):
        """자식 프로세스에서 잰다 — 부모의 `sys.modules` 가 답을 오염시킨다.

        이 파일을 돌리는 러너는 이미 다른 것들을 import 해 두었을 수 있고, 그러면
        「커널이 스스로 가져온다」와 「누군가 먼저 가져다 놓았다」가 같은 값이 된다.
        """
        script = textwrap.dedent('''
            import importlib, json, sys
            failures = []
            for name in json.loads(sys.argv[2]):
                try:
                    importlib.import_module(name)
                except BaseException as exc:      # noqa: BLE001 — 전부 보고한다
                    failures.append(f'{name}: {type(exc).__name__}: {exc}')
            print(json.dumps(failures))
        ''')
        import json
        modules = _modules()
        proc = subprocess.run(
            [sys.executable, '-c', script, '--', json.dumps(modules)],
            cwd=str(_KERNEL_ROOT), capture_output=True, text=True,
            env={'PYTHONPATH': str(_KERNEL_ROOT), 'PATH': '/usr/bin:/bin'},
        )
        self.assertEqual(
            0, proc.returncode,
            f'하위 인터프리터가 시작조차 못했다 — 이것은 통과가 아니다.\n{proc.stderr}',
        )
        failures = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(
            [], failures,
            '커널 모듈이 홀로 import 되지 않는다 (자원 누락 · 패키징 누락 · '
            '접두사 재작성 누락 중 하나다):\n  ' + '\n  '.join(failures),
        )


class TestDeclaredPackageDataIsRealAndReached(unittest.TestCase):
    """⚠️ 선언과 파일이 함께 있어야 한다 — 하나만으로는 배포가 조용히 비어 나간다."""

    def test_every_declared_package_data_pattern_matches_a_shipped_file(self):
        import tomllib
        config = tomllib.loads(
            (_KERNEL_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        patterns = config.get('tool', {}).get('setuptools', {}).get('package-data', {})
        self.assertTrue(
            patterns,
            'package-data 선언이 없다 — 이 검사가 아무것도 판정하지 않는다. '
            '커널이 자원을 안 싣게 되면 이 팔부터 지워라.',
        )
        for package, globs in patterns.items():
            directory = _KERNEL_ROOT / package.replace('.', '/')
            with self.subTest(package=package):
                self.assertTrue(directory.is_dir(), f'{package} 디렉터리가 없다')
                for pattern in globs:
                    self.assertTrue(
                        list(directory.glob(pattern)),
                        f'{package} 의 선언 {pattern!r} 에 맞는 파일이 없다',
                    )


if __name__ == '__main__':  # pragma: no cover
    unittest.main(verbosity=2)
