"""소비자의 프로젝트 루트를 **배송 트리로 오인하지 않는다**.

⚠️ 실측 2026-09-04 — provider 레인이 보고했고 최소 재현으로 확인했다.
``resolve_dependency_artifact`` 는 이 모듈이 온 트리를 ``_tree_root`` 로 찾는데, 그
함수는 레이아웃 기록이 없으면 **``.git``/``pyproject.toml`` 을 가진 가장 가까운 조상**
으로 물러난다. provider 는 이 레인을 **자기 프로젝트 안의 virtualenv** 에 설치하므로 그
훑기가 **소비자의 ``pyproject.toml``** 을 집었고, 레포 상대 경로가 소비자 루트에
이어 붙어 *아무것도 없는 경로*를 **예외 없이** 돌려줬다.

거부(``DependencyTreeUnavailable``)는 훑기가 **파일시스템 루트까지 갔을 때만** 발화한다.
소비자 프로젝트가 위에 있으면 그 조건이 성립하지 않아 ``_packaged_artifact`` 경로는
시도조차 되지 않았다.

**이 모듈 자신의 docstring 이 끝내려던 결함이 자기 폴백 안에 있었다** —
*"a resolver that answers anyway hands back a path that looks authoritative and is
wrong."* 그리고 **모든 provider 는 프로젝트 안에 venv 를 둔다.**

판별자는 *이 모듈을 어디서 읽었는가*이지 *위에 무엇이 있는가*가 아니다. 후자가 실패한
질문이다 — 소비자 프로젝트도 체크아웃이고, 그것은 이 레인의 것이 아니다.
"""
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest
import venv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fcc_test_contracts.common.tree_artifacts import (  # noqa: E402
    _is_installed_location,
    resolve_dependency_artifact,
)

SSOT = 'fcc_test_contracts/artifacts/headless_api_contract.v1.json'


class TestInstalledLocationDiscriminator(unittest.TestCase):
    def test_a_source_checkout_is_not_an_installed_location(self):
        """이 스위트 자신이 소스 트리에서 돈다 — 답이 알려진 대상이다."""
        self.assertFalse(
            _is_installed_location(PROJECT_ROOT / 'fcc_test_contracts' / 'common' / 'x.py'),
            '소스 체크아웃을 설치본으로 읽으면 이 레인의 자기 해소가 패키지 사본으로 우회한다',
        )

    def test_a_site_packages_path_is_an_installed_location(self):
        for part in ('site-packages', 'dist-packages'):
            with self.subTest(part=part):
                self.assertTrue(
                    _is_installed_location(Path('/anywhere') / 'venv' / 'lib' / part
                                           / 'fcc_test_contracts' / 'common' / 'x.py'),
                    f'{part} 아래는 설치본이다 — 다른 인터프리터가 만든 환경도 포함한다',
                )

    def test_this_interpreters_own_install_dir_is_an_installed_location(self):
        """``sysconfig`` 축. 경로 성분 축이 못 보는 배치를 덮는다."""
        purelib = sysconfig.get_paths().get('purelib')
        if not purelib:                                     # pragma: no cover
            self.skipTest('이 인터프리터가 purelib 을 보고하지 않는다')
        self.assertTrue(_is_installed_location(Path(purelib).resolve() / 'pkg' / 'm.py'))

    def test_the_source_tree_still_resolves_through_its_own_checkout(self):
        """⚠️ 반대 방향 팔. 수리가 「전부 패키지 사본으로」로 퇴화하면 red 다.

        `.claude/rules/check-axis-blindness.md` §비-공허성: *이 검사가 성공하면 이
        팔이 red 가 되는가?* → 아니오. 소스 트리에서 도는 한 초록이다.
        """
        resolved = resolve_dependency_artifact(SSOT)
        self.assertTrue(resolved.exists(), f'소스 트리에서 SSOT 를 못 찾는다: {resolved}')
        self.assertTrue(
            resolved.is_relative_to(PROJECT_ROOT),
            f'소스 트리에서 돌면서 트리 밖을 답했다: {resolved}',
        )


class TestConsumerProjectDoesNotAnswerForThisLane(unittest.TestCase):
    """⚠️ 재현 그 자체. 이 검사가 없으면 수리가 조용히 되돌려진다."""

    #: ⚠️ **마커 둘 다 재야 한다.** `_tree_root` 폴백은 ``.git`` **또는**
    #: ``pyproject.toml`` 을 본다. 이 검사의 초판은 ``pyproject.toml`` 만 뒀는데,
    #: 실제로 걸린 provider 레포에는 ``pyproject.toml`` 이 **없고 ``.git`` 만
    #: 있었다**(KC 실측 2026-09-04). 좁은 마커 하나만 재면 수리가 되돌려질 때
    #: ``.git`` 경로가 조용히 통과한다 — 조건은 「레포 안에 venv 를 둔 프로젝트」가
    #: 아니라 **「레포 안에 venv 를 둔 git 체크아웃 전부」**로 더 헐겁다.
    CONSUMER_MARKERS = ('pyproject.toml', '.git')

    def test_a_venv_inside_a_consumer_project_does_not_resolve_under_the_consumer(self):
        for marker in self.CONSUMER_MARKERS:
            with self.subTest(marker=marker):
                self._probe_consumer_shape(marker)

    def _probe_consumer_shape(self, marker: str):
        with tempfile.TemporaryDirectory() as tmp:
            consumer = Path(tmp) / 'consumer'
            consumer.mkdir()
            # 소비자의 마커. 이것 하나가 옛 폴백을 오답으로 이끌었다.
            if marker == '.git':
                (consumer / '.git').mkdir()
            else:
                (consumer / marker).write_text(
                    '[project]\nname = "consumer"\nversion = "0.0.0"\n', encoding='utf-8')
            venv.create(consumer / 'venv', with_pip=True)
            python = consumer / 'venv' / 'bin' / 'python'
            if not python.is_file():                        # pragma: no cover
                python = consumer / 'venv' / 'Scripts' / 'python.exe'
            # ⚠️ **설치는 사본에서 한다. 소스 트리에서 하면 안 된다.**
            # `pip install <PROJECT_ROOT>` 는 그 트리에 `build/` 를 남기고,
            # `lane_check` 는 `build/` 가 있으면 실패 집합이 오염됐다며 **게이트를
            # 거부한다**(원본과 사본을 함께 세기 때문). 즉 이 검사가 자기가 속한
            # 게이트를 부수는 형태였다 — 실측 2026-09-04, 이 파일의 초판이 그랬다.
            # 검사가 자기 트리를 변이시키면 그다음 측정은 실측이 아니다.
            staged = Path(tmp) / 'lane'
            staged.mkdir()
            shutil.copy2(PROJECT_ROOT / 'pyproject.toml', staged / 'pyproject.toml')
            shutil.copytree(PROJECT_ROOT / 'fcc_test_contracts',
                            staged / 'fcc_test_contracts',
                            ignore=shutil.ignore_patterns('__pycache__'))
            install = subprocess.run(
                [str(python), '-m', 'pip', 'install', '-q', '--no-deps', str(staged)],
                capture_output=True, text=True)
            if install.returncode != 0:                     # pragma: no cover
                self.skipTest(f'이 환경에서 레인을 설치하지 못했다: {install.stderr[-300:]}')

            probe = subprocess.run([str(python), '-c', (
                'from fcc_test_contracts.common.tree_artifacts import '
                'resolve_dependency_artifact, DependencyTreeUnavailable\n'
                'try:\n'
                f'    p = resolve_dependency_artifact({SSOT!r})\n'
                '    print("PATH", p, p.exists())\n'
                'except DependencyTreeUnavailable:\n'
                '    print("REFUSE")\n'
            )], capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr[-400:])
            answer = probe.stdout.strip()

            self.assertNotIn(
                f'PATH {consumer}/fcc_test_contracts', answer,
                '소비자 프로젝트 루트 아래를 답했다 — 2026-09-04 결함의 재발이다',
            )
            if answer.startswith('PATH'):
                self.assertTrue(
                    answer.endswith('True'),
                    f'실재하지 않는 경로를 예외 없이 돌려줬다: {answer}',
                )


class TestThisAxisDoesNotMutateTheTreeItMeasures(unittest.TestCase):
    """⚠️ 이 파일의 초판이 소스 트리에 ``build/`` 를 남겨 게이트를 거부하게 만들었다.

    산문 주석으로 *"사본에서 설치한다"* 라고 적는 것과 그것을 검사로 두는 것은 다르다 —
    이 저장소가 반복해 이름 붙인 차이다.
    """

    def test_no_build_artifacts_are_left_in_the_source_tree(self):
        strays = [name for name in ('build', 'fcc_test_contracts.egg-info')
                  if (PROJECT_ROOT / name).exists()]
        self.assertEqual(
            strays, [],
            f'소스 트리에 빌드 부산물이 남았다: {strays} — `lane_check` 가 이것을 '
            '오염으로 읽고 게이트 자체를 거부한다. 사본에서 설치하라.',
        )


if __name__ == '__main__':
    unittest.main()
