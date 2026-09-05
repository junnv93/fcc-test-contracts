"""이 저장소가 **자기가 필요로 하는 것을 선언하는가** (공급 폐포, 2026-09-05).

판정 로직은 이 파일에 없다. `fcc_test_contracts.common.supply_closure` 에 있고, 소비
레인(`fcc-test-platform`)의 같은 이름 시험이 **같은 부품**을 부른다.

⭐ **왜 나눴는가.** 이 축은 2026-09-04 에 소비 레인에서 먼저 섰고, 그때 이 상자에도
같은 계급의 결함이 있었다 — `tests/test_local_identity_live_postgres.py` 가 `psycopg` 를
가드 없이 부르는데 어느 extra 에도 없었다. 그것은 **사람이 손으로 훑어** 찾았다. 게이트가
없는 상자에서는 그것이 유일한 발견 경로이고, 사람은 매번 훑지 않는다.

그렇다고 그 300줄을 여기 복사하면 사본 둘이 생기고, 그것이 이 계열이 이미 값을 치른
형태다 — `tests/test_benchmark_harness_is_the_only_copy.py` 가 같은 자리에서 같은 말을
한다: *"갈라지지 않은 것은 시간이 안 지났기 때문이지 구조 때문이 아니다."*

이 파일에 남는 것은 **이 상자만의 사실** 둘뿐이다:

  ① 이 저장소가 내는 배포판이 무엇인가 (아래 `_EXPECTED_DISTRIBUTIONS`)
  ② 오늘 이 상자가 해소하지 못하는 이름은 무엇인가 (아래 `_KNOWN_UNRESOLVABLE`)

둘 다 **양방향 원장**이다 — 늘어도 red, 줄어도 red.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fcc_test_contracts.common.supply_closure import (
    LEDGER_REMEDY,
    MISSING_RESOURCE_REMEDY,
    UNDECLARED_REMEDY,
    ResourceClosure,
    SupplyClosure,
    WheelBuildUnavailable,
    conventional_import_names,
    convention_misattributions,
    discover_distributions,
    is_virtual_environment,
    iter_source_files,
    missing_resource_report,
    normalize,
    requirement_name,
    requirements_declarations,
    unguarded_imports,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: 이 저장소가 내는 **파이썬 배포판**의 원장.
#:
#: ⚠️ 개수가 아니라 이름의 집합이고, 정확한 일치를 요구한다. 개수로 두면 하나가 사라진
#: 자리에 다른 하나가 생긴 것과 아무 일도 없던 것이 같은 값이 된다 — 이 계열의 매니페스트가
#: `delivered_artifact_path_judged_baseline` 에서 같은 판단을 이미 적어 뒀다
#: (*"양의 하한으로 두지 않고 등식으로 기록한다"*).
#:
#: ⚠️ 이 원장이 이 파일에 있는 이유: 「한 저장소 = 한 pyproject」는 이 상자에서 **거짓**이고
#: (`packages/fcc-test-kernel/` 가 자체 버전 축·자체 의존을 가진 두 번째 배포판이다),
#: 그 사실이 게이트가 보는 대상을 정한다. 커널을 「first-party 니까 무시」로 처리하면
#: 오탐은 사라지지만 **커널의 공급 폐포를 아무도 재지 않게 된다** — 미검사가 통과로 읽힌다.
#: npm 배포물(`packages/api-artifacts`)은 파이썬 배포판이 아니라 이 축의 대상이 아니다.
_EXPECTED_DISTRIBUTIONS = {'fcc-test-contracts', 'fcc-test-kernel'}

#: 계급 B 의 **원장** — 오늘 이 상자가 해소하지 못하는 이름과 그 사유.
#:
#: ⚠️ 이것은 예외 목록이 아니다. `lane_check` 이 쓰는 것과 같은 형태의 원장이고 아래
#: 시험이 **정확한 일치**를 요구한다: 늘면 red, 해소돼도 red(*"그것도 소식이다"*).
#: 예외 목록은 한 방향으로만 자라 조용히 낡지만 원장은 낡을 수 없다.
#:
#: ── 오늘의 항목 (2026-09-05 실측) ──────────────────────────────────────────────
#: **비어 있다.** 그리고 그것이 이 상자에 대한 사실이지 검사를 끈 것이 아니다 —
#: 바로 위 `test_the_scan_is_not_vacuous` 가 스캔이 실제로 191 파일을 읽고 서드파티
#: import 를 찾았음을 먼저 단언한다. 빈 원장과 「스캐너가 고장나 아무것도 못 찾았다」가
#: 같은 값이 되는 것을 그 팔이 막는다.
_KNOWN_UNRESOLVABLE: frozenset[str] = frozenset()


class TestEveryUnguardedImportIsDeclared(unittest.TestCase):
    """① 의존성 폐포 — 코드가 요구하는 것이 선언에 있는가.

    ⚠️ AST 스캔은 이 트리에서 191 파일 · 약 0.5초다. 시험마다 다시 돌리면 그 값을 시험
    수만큼 낸다 — 게이트가 느리면 사람이 게이트를 건너뛰기 시작하고, 그러면 게이트가
    있으나 마나가 된다. 클래스당 한 번만 돈다.
    """

    @classmethod
    def setUpClass(cls):
        cls.closure = SupplyClosure(PROJECT_ROOT)

    def test_the_repository_ships_exactly_the_recorded_distributions(self):
        """배포판 원장 — 이 축이 **무엇을 보는지**가 조용히 바뀌지 않게 한다.

        새 `pyproject.toml` 이 생기면 그것도 재야 하고, 하나가 사라지면 그 트리는 이제
        누구의 선언에도 매이지 않는다. 둘 다 사람이 알아야 하는 소식이다.
        """
        observed = {distribution.name for distribution in self.closure.distributions}
        self.assertEqual(
            observed, _EXPECTED_DISTRIBUTIONS,
            '이 저장소가 내는 파이썬 배포판 집합이 원장과 다르다. 새로 생겼으면 그 배포판도 '
            '이 축이 자기 선언에 대고 재게 되고, 사라졌으면 그 트리가 어느 선언에도 매이지 '
            '않는다 — 어느 쪽이든 원장을 고치면서 왜인지 적어라.',
        )

    def test_the_scan_is_not_vacuous(self):
        """빈 스캔이 통과로 읽히지 않게 한다 — 이 게이트가 스스로 꺼지는 것을 막는다."""
        self.assertGreater(
            len(self.closure.python_files), 100,
            f'스캔한 파이썬 파일이 {len(self.closure.python_files)}개뿐이다',
        )
        self.assertGreater(
            len(self.closure.sites), 0,
            '서드파티 import 를 하나도 못 찾았다 — 스캐너가 고장났다는 뜻이다',
        )

    def test_the_kernel_subtree_is_actually_scanned(self):
        """하위 트리 배포판이 **자기 선언에 대고** 재지는지 봉인한다.

        이 팔이 없으면 커널을 스캔에서 통째로 빼는 변경이 초록으로 지나간다 — 그리고
        그것이 이 파일이 소비 레인의 사본과 갈라지는 자리다(거기는 배포판이 하나뿐이라
        이 성질을 잴 수 없다).
        """
        kernel = next(
            d for d in self.closure.distributions if d.name == 'fcc-test-kernel'
        )
        owned = [
            path for path, distribution in self.closure.python_files.items()
            if distribution is kernel
        ]
        self.assertGreater(
            len(owned), 20,
            f'커널 트리에서 스캔된 파일이 {len(owned)}개뿐이다 — 소유 판정이 무너졌다',
        )
        self.assertEqual(
            kernel.declared, {'fcc-test-contracts'},
            '커널의 선언이 루트 pyproject 의 것으로 바뀌었다 — 커널만 설치한 소비자에게는 '
            '루트의 선언이 존재하지 않으므로, 그 판정은 사실이 아니다.',
        )

    def test_every_unguarded_third_party_import_resolves_to_a_declared_distribution(self):
        """계급 A — 이름은 해소되는데 **선언에 없다.**

        개발 머신에서만 초록인 상태다. 우연히 깔려 있는 배포판에 기대고 있고, 갓 클론한
        러너에서 무너진다. 실측: 이 상자의 `psycopg`(2026-09-04, 손으로 발견) ·
        소비 레인의 jsonschema · PyJWT · PyYAML.
        """
        report = self.closure.undeclared_report()
        self.assertEqual(report, [], UNDECLARED_REMEDY.format(report='\n'.join(report)))

    def test_unresolvable_imports_match_the_recorded_ledger_exactly(self):
        """계급 B — 이름이 **어디에서도 해소되지 않는다.**

        선언 문제가 아니다. 이 상자가 자기 안에 없는 코드를 부른다는 뜻이고, 대개 모노레포
        분리 때 협력자만 다른 레인으로 가고 호출자가 남은 자리다. 계급 A 와 섞어 보고하면
        「의존성 하나 더 선언하면 되겠지」로 오독된다 — 그래서 시험을 나눠 둔다.
        """
        report = self.closure.ledger_report(_KNOWN_UNRESOLVABLE)
        self.assertEqual(report, [], LEDGER_REMEDY.format(report='\n'.join(report)))


class TestTheClosureJudgementItself(unittest.TestCase):
    """판정기 자체를 봉인한다 — 판정이 무너지면 위 시험들이 의미를 잃는다.

    ⚠️ 이 봉인이 **이 레인에** 있는 이유: 판정기가 여기 살기 때문이다. 소비 레인은
    설치된 사본을 쓰므로 그쪽에서 다시 봉인하면 그것이 두 번째 사본이 된다.
    """

    def test_a_guarded_import_is_treated_as_optional(self):
        """가드된 import 는 **선택적 의존성 선언**이다 — 없으면 그 경로를 포기한다는 뜻."""
        source = (
            'try:\n'
            '    import nonexistent_optional_pkg\n'
            'except ImportError:\n'
            '    nonexistent_optional_pkg = None\n'
            'import nonexistent_required_pkg\n'
        )
        found = self._scan(source)
        self.assertIn('nonexistent_required_pkg', found)
        self.assertNotIn('nonexistent_optional_pkg', found)

    def test_a_fallback_branch_is_guarded_too(self):
        """`except ModuleNotFoundError: import psycopg2` 의 **본문도** 가드된 것이다.

        이것을 무가드로 세면 폴백 대안까지 필수 의존성으로 요구하게 되고, 그러면
        「둘 중 하나만 있으면 된다」는 선언을 표현할 수 없다.
        """
        source = (
            'try:\n'
            '    import nonexistent_primary_pkg\n'
            'except ModuleNotFoundError:\n'
            '    import nonexistent_fallback_pkg\n'
        )
        self.assertEqual(self._scan(source), set())

    def test_a_relative_import_is_never_third_party(self):
        source = 'from . import sibling\nfrom .deeper import thing\n'
        self.assertEqual(self._scan(source), set())

    def test_the_distribution_name_is_pep503_normalized(self):
        """PEP 503 §Normalized Names — 대소문자와 **구분자 런**만 접는다.

        ⚠️ 구분자를 **지우지** 않는다. `PyJWT` 와 `pyjwt` 는 같은 배포판이지만
        `py-jwt` 는 다른 이름이다 — PyPI 가 그렇게 다루므로 여기서 더 접으면 이 게이트가
        서로 다른 두 배포판을 같은 것으로 보고 「선언돼 있다」고 잘못 통과시킨다.
        규칙: ``re.sub(r"[-_.]+", "-", name).lower()``.
        """
        same = {
            'PyYAML': 'pyyaml',            # 구분자 없음 — 대소문자만 접힌다
            'pyyaml': 'pyyaml',
            'PyJWT': 'pyjwt',
            'fcc_test_contracts': 'fcc-test-contracts',   # `_` · `.` · `-` 는 한 값
            'fcc.test.contracts': 'fcc-test-contracts',
            'fcc--test__contracts': 'fcc-test-contracts',  # 런은 하나로 접힌다
        }
        for spelling, expected in same.items():
            with self.subTest(spelling=spelling):
                self.assertEqual(normalize(spelling), expected)
        self.assertNotEqual(
            normalize('PyYAML'), normalize('Py_YAML'),
            'PEP 503 은 구분자를 지우지 않는다 — 지우면 다른 배포판 둘이 같은 이름이 된다.',
        )

    def test_a_requirement_spec_yields_only_its_name(self):
        """extra · 버전 · 환경표지 · PEP 508 direct reference 를 전부 벗긴다."""
        cases = {
            'PyJWT[crypto]>=2.8.0': 'pyjwt',
            'pytest >= 7.0.0': 'pytest',
            'psycopg[binary]>=3.1': 'psycopg',
            'fcc-test-contracts[oidc]': 'fcc-test-contracts',
            'fcc-test-contracts @ git+https://example.invalid/x@v0.1.18': 'fcc-test-contracts',
            'tomli; python_version < "3.11"': 'tomli',
        }
        for spec, expected in cases.items():
            with self.subTest(spec=spec):
                self.assertEqual(requirement_name(spec), expected)

    @staticmethod
    def _scan(source: str) -> set[str]:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / 'probe.py'
            probe.write_text(source, encoding='utf-8')
            return {site.module for site in unguarded_imports(probe)}


class TestWhatCountsAsSource(unittest.TestCase):
    """비-소스를 **이름이 아니라 성질**로 가르는가.

    ⚠️ 이 봉인이 없으면 다음 저장소가 가상환경을 다른 이름으로 부르는 순간 이 게이트가
    거기 설치된 배포판을 **이 저장소가 내는 것**으로 읽는다. 실측 2026-09-05: 원본
    모노레포는 가상환경을 `fcc_test_env/` 로 부르고 저장소 안에 두며, 그 안의
    `pandas/pyproject.toml` 이 `[project]` 을 갖는다.
    """

    def test_a_directory_with_pyvenv_cfg_is_a_virtual_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            venv = root / 'any_name_at_all'
            venv.mkdir()
            self.assertFalse(is_virtual_environment(venv), '아직 표지가 없다')
            (venv / 'pyvenv.cfg').write_text('home = /usr\n', encoding='utf-8')
            self.assertTrue(
                is_virtual_environment(venv),
                'PEP 405 는 가상환경을 pyvenv.cfg 로 정의한다 — 이름이 아니다.',
            )

    def test_a_pyproject_inside_a_virtual_environment_is_not_this_repository(self):
        """설치된 배포판의 `pyproject.toml` 을 우리 것으로 세지 않는다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pyproject.toml').write_text(
                '[project]\nname = "mine"\nversion = "0"\n', encoding='utf-8',
            )
            venv = root / 'runtime_env'
            (venv / 'lib' / 'site-packages' / 'somelib').mkdir(parents=True)
            (venv / 'pyvenv.cfg').write_text('home = /usr\n', encoding='utf-8')
            (venv / 'lib' / 'site-packages' / 'somelib' / 'pyproject.toml').write_text(
                '[project]\nname = "somelib"\nversion = "9"\n', encoding='utf-8',
            )
            observed = {d.name for d in discover_distributions(root)}
            self.assertEqual(
                observed, {'mine'},
                '가상환경 안의 배포판을 이 저장소가 내는 것으로 읽었다.',
            )

    def test_the_walker_prunes_instead_of_filtering_after_the_fact(self):
        """가지치기가 실제로 **들어가지 않는지** 본다 — 걸러내기와 구별되는 성질이다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'kept.py').write_text('', encoding='utf-8')
            for name in ('node_modules', '__pycache__', 'build'):
                (root / name).mkdir()
                (root / name / 'dropped.py').write_text('', encoding='utf-8')
            venv = root / 'env'
            venv.mkdir()
            (venv / 'pyvenv.cfg').write_text('home = /usr\n', encoding='utf-8')
            (venv / 'dropped.py').write_text('', encoding='utf-8')
            observed = {path.name for path in iter_source_files(root)}
            self.assertEqual(observed, {'kept.py'})


class TestTheDeclarationSourceIsDerived(unittest.TestCase):
    """선언 출처가 **파생**인가 — `[project]` 이 있으면 그것, 없으면 `requirements*.txt`.

    ⚠️ 이 봉인이 이 파일에 있는 이유: 이 레인에는 `[project]` 이 **있어서** 그 대체
    경로가 여기서는 절대 실행되지 않는다. 봉인하지 않으면 그 경로는 소비 저장소에서
    처음 돌고, 거기서 틀리면 **배포판 0개**로 조용히 초록이 된다(실측 2026-09-05:
    원본 모노레포에서 정확히 그 상태였다).
    """

    def _repo(self, directory: str, **files: str) -> Path:
        root = Path(directory)
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        return root

    def test_pyproject_wins_when_it_declares_a_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(
                directory,
                **{
                    'pyproject.toml': '[project]\nname = "boxed"\nversion = "0"\n'
                                      'dependencies = ["one"]\n',
                    'requirements.txt': 'two\n',
                },
            )
            (distribution,) = discover_distributions(root)
            self.assertEqual(distribution.name, 'boxed')
            self.assertEqual(distribution.declared, {'one'})
            self.assertFalse(distribution.whole_tree)
            self.assertTrue(distribution.is_installable)

    def test_requirements_take_over_when_pyproject_declares_no_project(self):
        """도구 설정만 있는 `pyproject.toml` 은 선언이 아니다 — 실측된 형상이다."""
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(
                directory,
                **{
                    'pyproject.toml': '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
                    'requirements.txt': 'alpha>=1.0   # 주석\n',
                    'requirements-node.txt': '-r requirements.txt\nbeta[extra]>=2\n',
                },
            )
            (distribution,) = discover_distributions(root)
            self.assertTrue(distribution.whole_tree)
            self.assertFalse(
                distribution.is_installable,
                'requirements 는 설치 목록이지 배포 선언이 아니다 — 휠을 낼 수 없다.',
            )
            self.assertEqual(distribution.declared, {'alpha', 'beta'})

    def test_an_include_is_followed_so_the_gate_does_not_invent_a_defect(self):
        """`-r` 너머의 선언을 못 보면 이 게이트가 **없는 결함**을 보고한다."""
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(
                directory,
                **{
                    'requirements.txt': 'alpha\n',
                    'requirements-web.txt': '-r requirements.txt\ngamma\n',
                },
            )
            declarations = requirements_declarations(root)
            self.assertEqual(
                declarations[root / 'requirements-web.txt'], {'alpha', 'gamma'},
            )

    def test_each_list_is_kept_apart_before_it_is_unioned(self):
        """넷을 합치기 **전의** 값이 남아야 레인별 축이 나중에 성립할 수 있다."""
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(
                directory,
                **{
                    'requirements.txt': 'shared\n',
                    'requirements-central.txt': 'shared\ncentral-only\n',
                },
            )
            (distribution,) = discover_distributions(root)
            self.assertEqual(
                dict(distribution.declared_by),
                {
                    'requirements-central.txt': frozenset({'shared', 'central-only'}),
                    'requirements.txt': frozenset({'shared'}),
                },
            )
            self.assertEqual(
                distribution.sources_declaring('central-only'),
                ('requirements-central.txt',),
                '어느 목록이 그것을 선언했는지 말할 수 있어야 처방이 성립한다.',
            )

    def test_a_url_fragment_is_not_a_comment(self):
        """PEP 508 direct reference 의 `#subdirectory=` 를 주석으로 자르면 안 된다."""
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo(
                directory,
                **{
                    'requirements.txt':
                        'kern @ git+https://example.invalid/x@v1#subdirectory=packages/kern\n',
                },
            )
            (distribution,) = discover_distributions(root)
            self.assertEqual(distribution.declared, {'kern'})

    def test_a_repository_with_no_declaration_at_all_yields_nothing(self):
        """⚠️ 빈 튜플은 「위반 없음」이 아니다 — 부르는 쪽이 그것을 막아야 한다."""
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(discover_distributions(Path(directory)), ())


class TestTheNameConventionIsARuleNotATable(unittest.TestCase):
    """설치 없이 배포판 이름에서 import 이름을 알아내는 **세 번째 경로**.

    ⚠️ 왜 필요한가 (실측 2026-09-05, 원본 모노레포): `Appium-Python-Client` 와
    `python-docx` 는 선언돼 있지만 **챔버 레인의 것**이라 중앙 러너에 깔리지 않고,
    이름도 달라 문자열 대조도 실패한다. 그러면 선언을 지키고 있는 저장소가 red 가
    되고, 더 나쁘게는 **이 게이트의 답이 러너에 무엇이 깔렸는지에 따라 달라진다**.
    규약 경로를 끄고 재면 계급 B 가 5 → 7 로 늘고 그 둘이 정확히 그 이름이다.
    """

    def test_the_measured_conventions_hold(self):
        cases = {
            'python-docx': 'docx',
            'PyYAML': 'yaml',
            'PyJWT': 'jwt',
            'Appium-Python-Client': 'appium',
            'python-multipart': 'multipart',
            'starlette': 'starlette',
        }
        for distribution_name, expected in cases.items():
            with self.subTest(distribution=distribution_name):
                self.assertIn(expected, conventional_import_names(distribution_name))

    def test_the_rule_does_not_grow_with_our_dependency_list(self):
        """규약은 **이름의 모양**에 대한 것이지 우리 의존성에 대한 것이 아니다.

        한 번도 본 적 없는 이름에도 같은 규칙이 그대로 적용돼야 한다 — 그렇지 않다면
        그것은 규약이 아니라 대응표이고, 대응표는 의존성이 늘 때마다 낡는다.
        """
        self.assertIn('neverseen', conventional_import_names('python-neverseen'))
        self.assertIn('neverseen', conventional_import_names('Neverseen-Python-Client'))

    def test_the_convention_never_attributes_a_name_to_the_wrong_distribution(self):
        """⚠️ 규약을 넓힐 때 드는 값을 **잰다** — 재지 않는 규약은 대응표보다 나쁘다.

        위험한 오예측은 「규약이 D 가 N 을 준다고 했는데 실제로 N 을 주는 것은 다른
        배포판」인 경우다. 그때 이 게이트는 선언되지 않은 의존을 선언된 것으로 읽고
        **조용히 통과**시킨다. 이 러너에 설치된 배포판 전량이 관측 가능한 자리다.
        """
        from importlib.metadata import distributions as installed_distributions
        installed = {
            normalize(dist.metadata['Name'])
            for dist in installed_distributions()
            if dist.metadata['Name']
        }
        self.assertGreater(
            len(installed), 5, f'설치된 배포판이 {len(installed)}개뿐이다 — 이 팔은 공허하다',
        )
        errors = convention_misattributions(installed)
        self.assertEqual(
            errors, [],
            '규약이 이름을 틀린 배포판에 붙인다 — 그 이름의 import 는 이제 선언 없이도 '
            '통과한다:\n' + '\n'.join(errors),
        )

    def test_the_convention_never_overrides_an_installed_answer(self):
        """설치본이 있으면 그것이 이긴다 — 규약은 답이 **존재하지 않는** 자리에서만 쓰인다.

        이 순서가 뒤집히면 계급 A(= 깔려 있는데 선언에 없다)가 규약에 먹혀 사라진다.
        """
        source = SupplyClosure.__init__.__doc__ or ''
        del source  # 문서가 아니라 동작으로 봉인한다 — 아래가 그 동작이다.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pyproject.toml').write_text(
                '[project]\nname = "probe"\nversion = "0"\n'
                'dependencies = ["python-notinstalled"]\n', encoding='utf-8',
            )
            (root / 'tests').mkdir()
            # `unittest` 는 stdlib 이라 걸리지 않는다. 설치돼 있고 선언에 없는 이름을
            # 골라야 계급 A 가 성립한다.
            (root / 'tests' / 'probe.py').write_text(
                'import pytest\nimport notinstalled\n', encoding='utf-8',
            )
            closure = SupplyClosure(root)
            self.assertEqual(
                [item.module for item in closure.undeclared], ['pytest'],
                '설치돼 있고 선언에 없는 이름은 규약과 무관하게 계급 A 여야 한다.',
            )
            self.assertEqual(
                closure.unresolvable_names, set(),
                '`python-notinstalled` 선언이 규약으로 `notinstalled` 를 해소해야 한다.',
            )


class TestEveryPackageResourceShipsInTheWheel(unittest.TestCase):
    """② 패키지 자원 폐포 — 코드 옆에 있는 비-.py 가 **휠에도** 있는가.

    ⚠️ **실제로 휠을 빌드해서 잰다.** 선언(`package-data` 글롭)을 읽어서 재면 그 선언이
    틀렸을 때 검사도 같이 틀린다 — 커널의 `decision_catalogue.json` 이 정확히 그 계급의
    결함이었다(2단계 이관에서 코드만 옮기자 15개 모듈이 import 시점에 죽었다). 재는
    대상은 선언이 아니라 **산출물**이어야 한다.

    ⚠️ 빌드는 트리 밖 사본에서 한다. non-editable 설치는 `build/` 를 남기고 `lane_check`
    은 그 트리에서 **판정을 거부한다**(`CONFOUNDING_ARTIFACTS`). 검사가 자기가 재는
    트리를 오염시키면 그 측정은 자기 자신의 부작용을 잰다.

    ⚠️ **배포판마다 잰다.** 커널의 자원은 커널 휠에 있어야 한다 — 루트 휠에 있어도
    커널만 설치한 소비자에게는 없다.
    """

    @classmethod
    def setUpClass(cls):
        cls.closures: dict[str, ResourceClosure] = {}
        for distribution in SupplyClosure(PROJECT_ROOT).distributions:
            closure = ResourceClosure(distribution, repo_root=PROJECT_ROOT)
            try:
                closure.build()
            except WheelBuildUnavailable as exc:  # pragma: no cover — 빌드 불가 환경
                raise unittest.SkipTest(str(exc)) from exc
            cls.closures[distribution.name] = closure

    @classmethod
    def tearDownClass(cls):
        for closure in getattr(cls, 'closures', {}).values():
            closure.close()

    def test_every_distribution_was_actually_built(self):
        self.assertEqual(set(self.closures), _EXPECTED_DISTRIBUTIONS)

    def test_the_scan_is_not_vacuous(self):
        total = sum(len(c.source_resources()) for c in self.closures.values())
        self.assertGreater(
            total, 0, '패키지 안에서 비-.py 자원을 하나도 못 찾았다 — 스캐너가 고장났다',
        )

    def test_every_non_python_file_beside_the_code_is_in_the_wheel(self):
        missing: list[str] = []
        for name, closure in sorted(self.closures.items()):
            missing.extend(f'{name}: {item}' for item in closure.missing_resources())
        self.assertEqual(
            missing, [],
            MISSING_RESOURCE_REMEDY.format(report='\n'.join(missing_resource_report(missing))),
        )

    def test_each_wheel_carries_the_python_it_claims(self):
        """휠이 비었는데 자원만 맞는 상태를 통과로 읽지 않는다."""
        for name, closure in sorted(self.closures.items()):
            with self.subTest(distribution=name):
                self.assertGreater(
                    closure.shipped_module_count(), 20,
                    f'{name} 휠에 .py 가 {closure.shipped_module_count()}개뿐이다',
                )


if __name__ == '__main__':
    unittest.main()
