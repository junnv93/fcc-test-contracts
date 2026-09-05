"""저장소가 **자기가 필요로 하는 것을 선언하는가** — 공급 폐포 판정기 (2026-09-05).

이 모듈은 `fcc-test-platform:tests/test_supply_closure_axis.py` (2026-09-04) 가 세운
판정을 **두 상자가 함께 쓰는 부품**으로 올린 것이다. 그 파일이 붙잡은 결함 계급의
역사는 이미 두 레인의 `pyproject.toml` 주석에 적혀 있다:

  * *"`jsonschema` 와 `PyJWT[crypto]` 는 검사가 **실제로 임포트** 하는데 선언에 없었다.
    이 머신에는 이미 깔려 있어 로컬은 초록이었고, 갓 클론한 CI 러너에서만 드러났다."*
  * *"`decision_catalogue.json` 이 빠진 배포물은 설치도 되고 휠도 만들어지지만
    **import 하는 순간 죽는다**. … 상자에는 실려 있고 **휠에만 없었다**."*

둘은 **같은 결함의 두 얼굴**이다: 「코드가 실제로 필요로 하는 것」과 「배포 선언이
말하는 것」이 손으로 동기화된다. 손 동기화는 반드시 낡는다.

⭐ **왜 이 모듈이 여기 있는가.** 이 레인의 `scripts/` 와 `tests/` 는 배포 대상이 아니다
(`pyproject.toml`: ``include = ["fcc_test_contracts*"]``). 거기 두면 소비 레인은 그것을
**볼 수 없고**, 「공유」가 아니라 「복사」가 된다 — `benchmark_harness` 가 정확히 그
이유로 여기로 올라왔고 `tests/test_benchmark_harness_is_the_only_copy.py` 가 그 사유를
적어 뒀다. 300줄짜리 두 번째 사본은 갈라지지 않은 것이 아니라 **아직 시간이 안 지난
것**이다.

⚠️ 이 모듈은 서드파티를 쓰지 않는다 — 이 레인의 P0 불변식(하드 의존 0)이 그것이고,
소비 레인의 갓 클론한 러너에서도 이 게이트가 **가장 먼저** 돌아야 하기 때문이다.
게이트가 자기 의존을 못 구해 죽으면 그것이 잴 결함과 구별되지 않는다.

⚠️ 이 모듈은 `unittest` 를 import 하지 않는다. 판정과 단언은 다른 일이다 — 판정은
배포되는 자리에 살고, 단언(과 그 상자의 **원장**)은 그 상자의 시험 파일에 산다.


축이 무엇인가
─────────────

  ① 의존성 폐포 — 코드가 **가드 없이** import 하는 서드파티 이름 ⊆ 선언이 제공하는 배포판
  ② 패키지 자원 폐포 — 패키지 디렉터리 안의 비-.py 파일 ⊆ **실제로 빌드한 휠**의 내용물

②는 선언(`package-data` 글롭)을 읽어 재지 않는다. 그 선언이 틀렸을 때 검사도 같이
틀리기 때문이다 — `decision_catalogue.json` 과 PM/RF 엑셀 서식이 정확히 그렇게 빠졌다.
재는 대상은 선언이 아니라 **산출물**이어야 한다.

이름 매핑(`yaml` → `PyYAML`)은 **하드코딩하지 않는다.** 표준 라이브러리의
``importlib.metadata.packages_distributions()`` 가 그 매핑의 SSOT 다
(https://docs.python.org/3/library/importlib.metadata.html).


⭐ 왜 「스캔 루트」가 아니라 「배포판」을 파생하는가
──────────────────────────────────────────────────

원본은 「한 저장소 = 한 `pyproject.toml`」을 암묵 가정했다. 소비 레인에서는 그것이 참이라
드러나지 않았지만, 이 레인에서는 거짓이다 — `packages/fcc-test-kernel/pyproject.toml` 이
**두 번째 파이썬 배포판**(`fcc-test-kernel`, 자체 버전 축 · 자체 `dependencies`)을 낸다.

그 트리를 「first-party 니까 스캔에서 빼자」로 처리하면 오탐은 사라지지만 **커널의 공급
폐포를 아무도 재지 않게 된다**. 그것은 오탐보다 나쁘다 — 미검사가 통과로 읽히기 때문이다.

그래서 이 모듈이 파생하는 단위는 **배포판**이고, 각 배포판은 **자기 선언**에 대고
판정된다. 상자별 분기가 0 이 된다: 소비 레인은 배포판 1개, 이 레인은 2개일 뿐 규칙은
하나다. 새 배포판이 생겨도 이 파일은 그대로 맞다.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from importlib.metadata import packages_distributions
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile


#: 스캔에서 제외할 디렉터리 이름. 파이썬 소스가 아니거나(node_modules) 원본의 사본이라
#: 두 번 세게 되는 것들(build · dist · __pycache__)이다. 이름 목록이 아니라 **성질**로
#: 골랐다 — 새 디렉터리가 생겨도 이 성질이 아니면 스캔 대상이다.
NOT_SOURCE = frozenset({
    '__pycache__', 'node_modules', 'build', 'dist', '.git', '.venv', '.tox', '.mypy_cache',
})

#: 배포판 루트 옆에 있으면 스캔에 넣는 디렉터리. 배포되지는 않지만 **돈다** —
#: 마이그레이션 러너 · DDL 생성기 · 게이트가 거기 산다. 거기서 쓰는 서드파티가 선언에
#: 없으면 갓 클론한 러너에서 죽는다.
_UNSHIPPED_BUT_RUNS = ('tests', 'scripts')

#: 소스에 있지만 휠에 없어도 되는 것 — 파이썬 자신이 만드는 부산물뿐이다.
_NOT_A_RESOURCE = frozenset({'.pyc', '.pyo', '.pyd', '.so'})


# ──────────────────────────────────────────────────────────────────────────────
# 이름 정규화 — PEP 503
# ──────────────────────────────────────────────────────────────────────────────

def normalize(name: str) -> str:
    """PEP 503 정규화 — `PyYAML` 과 `pyyaml` 과 `Py_YAML` 은 같은 배포판이다."""
    return re.sub(r'[-_.]+', '-', name).lower()


def requirement_name(spec: str) -> str:
    """`"PyJWT[crypto]>=2.8.0"` → `pyjwt`. PEP 508 direct reference 도 이름만 떼어낸다.

    ⚠️ `@` 를 먼저 자른다. `"fcc-test-contracts @ git+https://…@v0.1.18"` 처럼 URL 안에
    `@` 가 또 있어도 첫 조각이 이름이다.
    """
    head = spec.split('@', 1)[0].strip()             # PEP 508 direct reference
    head = re.split(r'[<>=!~\[;\s]', head, 1)[0]     # 버전 · extra · 환경표지 제거
    return normalize(head)


# ──────────────────────────────────────────────────────────────────────────────
# 배포판 — 이 저장소가 내는 파이썬 배포물 하나
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Distribution:
    """`pyproject.toml` 하나가 정의하는 배포판.

    모든 필드가 **파생**이다. 발명한 값이 없다는 것이 이 자료형의 성질이고, 그래서
    새 배포판·새 extra·새 최상위 모듈이 생겨도 이 파일을 고칠 일이 없다.
    """

    #: `[project] name`. 보고 메시지가 「어느 pyproject 를 고치라」고 말할 때 쓴다.
    name: str
    #: 그 `pyproject.toml` 자신.
    pyproject_path: Path
    #: 그 파일이 있는 디렉터리 — 이 배포판의 모든 상대 경로가 여기서 시작한다.
    root: Path
    #: 휠에 실리는 최상위 **패키지** 디렉터리 (`packages.find.include` 에서 파생).
    package_roots: tuple[Path, ...]
    #: 휠에 실리는 최상위 **모듈** 파일 (`[tool.setuptools] py-modules` 에서 파생).
    #:
    #: ⚠️ 이것을 읽지 않으면 안 되는 이유가 소비 레인 pyproject 에 적혀 있다:
    #: *"최상위 모듈은 `packages.find` 가 못 찾는다 — 패키지가 아니기 때문이다. …
    #: 빠지면 휠은 만들어지고 설치도 되는데 **import 하는 순간 죽는다**."*
    module_files: tuple[Path, ...]
    #: 이 배포판이 **선언한** 배포판 전부 (런타임 + 모든 extra), PEP 503 정규화.
    declared: frozenset[str]

    @property
    def scan_roots(self) -> tuple[Path, ...]:
        """이 배포판에 딸린 파이썬 전부 — 실리는 패키지 + 옆에서 도는 tests/scripts."""
        roots = list(self.package_roots)
        for name in _UNSHIPPED_BUT_RUNS:
            candidate = self.root / name
            if candidate.is_dir():
                roots.append(candidate)
        return tuple(roots)

    @property
    def provided_import_names(self) -> frozenset[str]:
        """이 배포판이 **설치되면** 제공하는 최상위 import 이름."""
        return frozenset(
            [root.name for root in self.package_roots]
            + [path.stem for path in self.module_files]
        )


def _read_pyproject(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding='utf-8'))


def _declared_distributions(project: dict) -> frozenset[str]:
    """`[project]` 이 선언한 배포판 전부 (런타임 + **모든** extra).

    extra 이름을 손으로 적지 않는다 — `[project.optional-dependencies]` 전체를 훑는다.
    새 extra 가 생겨도 이 함수는 그대로 맞다.
    """
    specs = list(project.get('dependencies') or [])
    for extra_specs in (project.get('optional-dependencies') or {}).values():
        specs.extend(extra_specs)
    return frozenset(requirement_name(spec) for spec in specs)


def _distribution_from_pyproject(path: Path) -> Distribution | None:
    """`pyproject.toml` 하나를 배포판으로 읽는다. 배포판이 아니면 `None`.

    ⚠️ 「배포판이 아닌 pyproject」가 실재한다 — 도구 설정만 담은 것(`[tool.*]` 뿐),
    빌드 백엔드가 다른 것. `[project] name` 이 없으면 이 축이 판정할 대상이 아니다.
    """
    try:
        data = _read_pyproject(path)
    except (OSError, tomllib.TOMLDecodeError):  # pragma: no cover — 파서 방어
        return None

    project = data.get('project')
    if not isinstance(project, dict) or not project.get('name'):
        return None

    root = path.parent
    setuptools_table = (data.get('tool') or {}).get('setuptools') or {}

    package_roots: list[Path] = []
    patterns = ((setuptools_table.get('packages') or {}).get('find') or {}).get('include') or []
    for pattern in patterns:
        # `"fcc_test_platform*"` → `fcc_test_platform`. 점이 있는 패턴
        # (`"application.central_contract*"`)은 최상위 조각이 그 트리의 뿌리다.
        stem = pattern.rstrip('*').rstrip('.')
        if not stem:
            continue
        candidate = root / Path(*stem.split('.'))
        if candidate.is_dir() and candidate not in package_roots:
            package_roots.append(candidate)

    module_files: list[Path] = []
    for module_name in setuptools_table.get('py-modules') or []:
        candidate = root / f'{module_name}.py'
        if candidate.is_file():
            module_files.append(candidate)

    return Distribution(
        name=project['name'],
        pyproject_path=path,
        root=root,
        package_roots=tuple(package_roots),
        module_files=tuple(module_files),
        declared=_declared_distributions(project),
    )


def discover_distributions(repo_root: Path) -> tuple[Distribution, ...]:
    """이 저장소가 내는 파이썬 배포판 **전부** (파생).

    ⚠️ 목록을 인자로 받지 않는다. 목록을 적어 두는 순간 그 목록이 다음에 낡을 자리가
    되고, 그것이 이 축이 없애려는 바로 그 형태다. 실측: 이 레인은 배포판 2개
    (루트 `fcc-test-contracts` + `packages/fcc-test-kernel`), 소비 레인은 1개다.
    """
    found: list[Distribution] = []
    for path in sorted(repo_root.rglob('pyproject.toml')):
        relative = path.relative_to(repo_root)
        if any(part in NOT_SOURCE or part.endswith('.egg-info') for part in relative.parts):
            continue
        distribution = _distribution_from_pyproject(path)
        if distribution is not None:
            found.append(distribution)
    return tuple(found)


# ──────────────────────────────────────────────────────────────────────────────
# import 자리 — AST 로 뽑는다
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ImportSite:
    module: str
    path: Path
    line: int
    anchor: Path = field(default=Path('.'), compare=False)

    @property
    def where(self) -> str:
        try:
            shown = self.path.relative_to(self.anchor)
        except ValueError:  # pragma: no cover — 앵커 밖 경로 방어
            shown = self.path
        return f'{shown}:{self.line}'


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    """이 except 절이 import 실패를 삼키는가.

    가드된 import 는 **선택적 의존성 선언**이다 — 없으면 그 경로를 포기한다는 뜻이므로
    폐포 검사의 대상이 아니다. 가드가 없으면 그것은 **필수**이고 선언돼 있어야 한다.
    """
    node = handler.type
    if node is None:                       # bare except
        return True
    candidates = node.elts if isinstance(node, ast.Tuple) else [node]
    for candidate in candidates:
        name = getattr(candidate, 'id', None) or getattr(candidate, 'attr', None)
        if name in ('ImportError', 'ModuleNotFoundError', 'Exception', 'BaseException'):
            return True
    return False


def unguarded_imports(path: Path, *, anchor: Path | None = None) -> list[ImportSite]:
    """한 파일에서 **가드 없이** 이름을 요구하는 import 전부."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):  # pragma: no cover — 파서 방어
        return []

    at = anchor if anchor is not None else path.parent
    sites: list[ImportSite] = []

    def visit(node: ast.AST, guarded: bool) -> None:
        if isinstance(node, ast.Try):
            catching = [h for h in node.handlers if _catches_import_error(h)]
            body_guarded = guarded or bool(catching)
            for child in node.body:
                visit(child, body_guarded)
            # ⚠️ import 실패를 잡는 핸들러의 **본문도 가드된 것**이다 — 그것이
            # 폴백 분기이기 때문이다(`except ModuleNotFoundError: import psycopg2`).
            # 이것을 무가드로 세면 폴백 대안까지 필수 의존성으로 요구하게 되고,
            # 그러면 「둘 중 하나만 있으면 된다」는 선언을 표현할 수 없다.
            for handler in node.handlers:
                for child in handler.body:
                    visit(child, guarded or _catches_import_error(handler))
            for group in (node.orelse, node.finalbody):
                for child in group:
                    visit(child, guarded)
            return
        if isinstance(node, ast.Import) and not guarded:
            for alias in node.names:
                sites.append(ImportSite(alias.name.split('.')[0], path, node.lineno, at))
        elif isinstance(node, ast.ImportFrom) and not guarded:
            # 상대 import(`from . import x`)는 이 상자 자신이다.
            if node.level == 0 and node.module:
                sites.append(ImportSite(node.module.split('.')[0], path, node.lineno, at))
        for child in ast.iter_child_nodes(node):
            visit(child, guarded)

    for child in ast.iter_child_nodes(tree):
        visit(child, False)
    return sites


def _importable_children(directory: Path) -> set[str]:
    """이 디렉터리를 `sys.path` 에 얹었을 때 import 되는 최상위 이름들."""
    names: set[str] = set()
    try:
        entries = list(directory.iterdir())
    except OSError:  # pragma: no cover — 경쟁 삭제 방어
        return names
    for entry in entries:
        if entry.name.startswith('.') or entry.name in NOT_SOURCE:
            continue
        if entry.is_dir() and any(entry.glob('*.py')):
            names.add(entry.name)
        elif entry.is_file() and entry.suffix == '.py':
            names.add(entry.stem)
    return names


# ──────────────────────────────────────────────────────────────────────────────
# 계급 A / 계급 B — 두 결함을 나눠서 보고한다
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UndeclaredImport:
    """계급 A — 이름은 해소되는데 **선언에 없다.**"""
    module: str
    providers: tuple[str, ...]
    distribution: str
    pyproject: str
    wheres: tuple[str, ...]

    def describe(self) -> str:
        return (
            f'  · {self.module!r} — {list(self.providers)} 가 제공하는데 '
            f'{self.pyproject} 선언에 없다 (우연히 깔려 있을 뿐이다). '
            f'부르는 곳: {", ".join(self.wheres[:3])}'
        )


@dataclass(frozen=True)
class UnresolvableImport:
    """계급 B — 이름이 **어디에서도 해소되지 않는다.**"""
    module: str
    distribution: str
    wheres: tuple[str, ...]


UNDECLARED_REMEDY = (
    '이 저장소가 자족적이지 않다 — 코드가 요구하는데 선언하지 않은 것이 있다:\n{report}\n\n'
    '고치는 법: 그 배포판의 pyproject.toml 에서 [project.dependencies](소스가 쓰면) 또는 '
    '[project.optional-dependencies] 의 적절한 extra(그 도구만 쓰면) 에 그 배포판을 '
    '선언하라. ⚠️ import 에 try/except 가드를 다는 것으로 통과시키지 마라 — 그것은 '
    '그 경로의 검사를 조용히 끄는 것이고, 이 계열이 lane_check 에서 이미 이름 붙여 거부한 '
    '형태다("기준선을 관측값으로 덮어써서 초록을 만들지 마라 — 그것은 검사를 끄는 것이다").'
)

LEDGER_REMEDY = (
    '해소 불가 import 원장이 관측과 어긋난다:\n{report}\n\n'
    '[새로 생김] 의 고치는 법은 선언이 아니다. 그 코드의 협력자가 어느 레인에 사는지 보고, '
    '(가) 이 상자가 그 레인을 통해 닿게 하거나 (나) 그 코드가 이 상자의 것이 아니면 옮겨라. '
    '그 판정을 내리기 전까지 원장에 넣는 것은 **사유와 날짜를 함께 적을 때만** 정당하다.\n'
    '[해소됨] 은 원장이 낡았다는 사실이고, 그것도 소식이다 — 원장에서 그 줄을 지워라. '
    '⚠️ skip 이나 예외 목록으로 바꾸지 마라: 예외 목록은 한 방향으로만 자라 조용히 낡지만, '
    '양방향 원장은 낡을 수 없다.'
)

MISSING_RESOURCE_REMEDY = (
    '코드 옆에 있는데 휠에 실리지 않은 파일이 있다 — 설치본으로 도는 컨테이너에서만 '
    '죽는 형태다:\n{report}\n\n'
    '고치는 법: 그 배포판의 pyproject.toml 에서 [tool.setuptools.package-data] 에 그 패턴을 '
    '선언하라. ⚠️ 반대로 그 파일이 애초에 패키지 안에 있으면 안 되는 것이라면 패키지 밖으로 '
    '옮겨라 — 둘 중 하나이지, 그냥 두는 선택지는 없다.'
)


# ──────────────────────────────────────────────────────────────────────────────
# ① 의존성 폐포
# ──────────────────────────────────────────────────────────────────────────────

class SupplyClosure:
    """저장소 하나의 공급 폐포 판정.

    ⚠️ **한 번만 스캔한다.** AST 스캔은 소비 레인에서 390 파일 · 3,300여 import ·
    약 1.5초다. 시험마다 다시 돌리면 그 값을 시험 수만큼 낸다 — 게이트가 느리면 사람이
    게이트를 건너뛰기 시작하고, 그러면 게이트가 있으나 마나가 된다. 그래서 이 객체를
    `setUpClass` 에서 한 번 만들어 쓴다.

    ⚠️ **이 판정은 두 가지 형태로 빨개지고 둘 다 옳다.**

      * 개발 머신(전부 깔려 있음): 이름은 import 되는데 그것을 제공하는 배포판이
        **선언에 없다** → 「로컬만 초록」이 되기 전에 여기서 멈춘다.
      * 갓 클론한 러너(선언한 것만 깔림): 이름이 **아예 import 되지 않는다** →
        수십 건이 흩어져 나는 대신 이 판정 하나가 이름을 대고 멈춘다.

    두 형태 모두 사람이 목록을 손보지 않아도 성립한다.
    """

    def __init__(self, repo_root: Path, *, distributions: tuple[Distribution, ...] | None = None):
        self.repo_root = repo_root.resolve()
        self.distributions = (
            distributions if distributions is not None
            else discover_distributions(self.repo_root)
        )
        #: 설치본이 말하는 「import 이름 → 그것을 제공하는 배포판」. 손으로 만든 표가
        #: 아니라 표준 라이브러리가 주는 SSOT 다.
        self.provided = packages_distributions()
        self.first_party = self._first_party_names()
        self.python_files = self._python_files()
        self.sites = self._third_party_sites()
        self._undeclared, self._unresolvable = self._classify()

    # ── 파생 ─────────────────────────────────────────────────────────────────

    def _first_party_names(self) -> frozenset[str]:
        """이 저장소가 스스로 제공하는 import 이름 (파생).

        세 곳에서 모은다:

          ① **모든 배포판**이 제공하는 최상위 이름. 이 레인의 `fcc_test_kernel` 처럼
             하위 트리에 사는 배포판이 여기 걸린다 — 저장소 루트만 훑으면 그것이
             「설치되지 않은 서드파티」로 오독된다.
          ② 저장소 루트의 직계 자식. `tests` · `scripts` 같은 이름이 여기서 나온다.
          ③ **`sys.path` 에 얹히는 디렉터리의 직계 자식.** `scripts/` 와 `tests/` 는
             패키지가 아니라 디렉터리이고, 그 안의 모듈들은 그 디렉터리를 `sys.path` 에
             얹은 뒤 형제 이름으로 서로를 부른다(`import platform_db_migrate`). 저장소
             루트만 훑으면 그 형제들이 전부 서드파티로 오독된다 — 실측 2026-09-04,
             오탐 9건.

        ⚠️ **패키지 루트의 자식은 최상위 이름이 아니다.** `fcc_test_platform/api/` 는
        `import api` 가 아니라 `import fcc_test_platform.api` 로만 닿는다. 그것을
        first-party 로 세면 같은 이름의 실재 배포판을 이 게이트가 구조적으로 못 본다 —
        실측 2026-09-05: 그렇게 가려지던 최상위 이름이 소비 레인에서 **40개**였고
        (`api` · `application` · `domain` · `rbac` …) 그중 여럿이 PyPI 에 실재한다.
        같은 실측에서 그 느슨함이 실제로 가려주던 import 자리는 **양쪽 상자 모두 0건**
        이었다 — 즉 좁히는 데 값이 들지 않고, 넓은 채로 두면 사각지대만 남는다.

        ⚠️ 이름이 서드파티와 겹치면 이 트리 것이 이긴다. 그것이 실제 import 해소 순서다.
        """
        names = _importable_children(self.repo_root)
        for distribution in self.distributions:
            names |= set(distribution.provided_import_names)
            package_roots = set(distribution.package_roots)
            for root in distribution.scan_roots:
                if root in package_roots:
                    # 실리는 패키지다. 그 이름 자체는 위 provided_import_names 가
                    # 이미 넣었고, 자식은 최상위 이름이 아니다.
                    continue
                # 루트 자신도 import 이름이다 — `sys.path` 에 저장소 루트를 얹으면
                # `import tests.support...` 가 성립한다.
                if any(root.glob('*.py')):
                    names.add(root.name)
                names |= _importable_children(root)
        return frozenset(names)

    def _python_files(self) -> dict[Path, Distribution]:
        """스캔 대상 파이썬 파일 → **그 파일을 소유하는 배포판**.

        소유가 중요하다: 판정은 「이 저장소가 선언했는가」가 아니라 「**이 배포판이**
        선언했는가」다. 커널이 쓰는 것을 계약 레인 pyproject 가 선언했다고 통과시키면,
        커널만 설치한 소비자에게는 여전히 없다.
        """
        owned: dict[Path, Distribution] = {}
        for distribution in self.distributions:
            targets = list(distribution.scan_roots)
            targets_files = list(distribution.module_files)
            for root in targets:
                for path in root.rglob('*.py'):
                    relative = path.relative_to(self.repo_root)
                    if any(part in NOT_SOURCE or part.endswith('.egg-info')
                           for part in relative.parts):
                        continue
                    targets_files.append(path)
            for path in targets_files:
                # ⚠️ 더 깊은 배포판이 이긴다. 하위 트리 배포판의 파일이 상위 배포판의
                # 스캔에 딸려 들어가는 경우, 소유는 자기 pyproject 를 가진 쪽이다.
                previous = owned.get(path)
                if previous is None or len(distribution.root.parts) > len(previous.root.parts):
                    owned[path] = distribution
        return owned

    def _third_party_sites(self) -> list[ImportSite]:
        sites: list[ImportSite] = []
        for path in sorted(self.python_files):
            for site in unguarded_imports(path, anchor=self.repo_root):
                if site.module in sys.stdlib_module_names or site.module in self.first_party:
                    continue
                sites.append(site)
        return sites

    def _classify(self) -> tuple[list[UndeclaredImport], list[UnresolvableImport]]:
        """두 결함 계급을 가른다 — 고치는 사람도, 고치는 법도 다르기 때문이다."""
        undeclared: dict[tuple[str, str], list[str]] = {}
        undeclared_meta: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {}
        unresolvable: dict[tuple[str, str], list[str]] = {}

        for site in self.sites:
            distribution = self.python_files[site.path]
            key = (site.module, distribution.name)
            providers = self.provided.get(site.module)
            if providers:
                # 설치돼 있으면 정확한 매핑이 있다 — 그것으로 판정한다.
                if not {normalize(name) for name in providers} & distribution.declared:
                    undeclared.setdefault(key, []).append(site.where)
                    undeclared_meta[key] = (
                        tuple(providers),
                        str(distribution.pyproject_path.relative_to(self.repo_root)),
                    )
                continue
            # 설치돼 있지 않다. 이 검사가 도는 환경은 `[test]` 만 깔린 러너일 수 있고,
            # 다른 extra 로 선언된 도구(브라우저 QA 등)는 여기 없는 것이 정상이다.
            # 그때는 이름 매칭이 유일하게 남은 증거다 — 정확한 매핑은 배포판을 설치해야만
            # 알 수 있기 때문이다(`packages_distributions()` 는 설치본을 훑는다).
            # ⚠️ 이름이 배포판과 다른 경우(PyYAML→yaml)는 이 우회를 못 타지만, 그런 것은
            # `[test]` 에 선언돼 러너에 설치되므로 위 정확한 경로로 판정된다.
            if normalize(site.module) in distribution.declared:
                continue
            unresolvable.setdefault(key, []).append(site.where)

        undeclared_result = [
            UndeclaredImport(
                module=module,
                providers=undeclared_meta[(module, dist_name)][0],
                distribution=dist_name,
                pyproject=undeclared_meta[(module, dist_name)][1],
                wheres=tuple(sorted(set(wheres))),
            )
            for (module, dist_name), wheres in sorted(undeclared.items())
        ]
        unresolvable_result = [
            UnresolvableImport(
                module=module, distribution=dist_name, wheres=tuple(sorted(set(wheres))),
            )
            for (module, dist_name), wheres in sorted(unresolvable.items())
        ]
        return undeclared_result, unresolvable_result

    # ── 보고 ─────────────────────────────────────────────────────────────────

    @property
    def undeclared(self) -> list[UndeclaredImport]:
        return list(self._undeclared)

    @property
    def unresolvable(self) -> list[UnresolvableImport]:
        return list(self._unresolvable)

    @property
    def unresolvable_names(self) -> set[str]:
        """원장과 대조할 관측 집합. 배포판을 가로질러 **이름**으로 센다 —
        원장은 사람이 읽는 것이고, 사람이 세는 단위는 「이 상자가 못 부르는 이름」이다."""
        return {item.module for item in self._unresolvable}

    def undeclared_report(self) -> list[str]:
        """계급 A 보고. 빈 리스트가 초록이다."""
        return [item.describe() for item in self._undeclared]

    def ledger_report(self, known_unresolvable: set[str] | frozenset[str]) -> list[str]:
        """계급 B **양방향 원장** 보고. 빈 리스트가 초록이다.

        ⚠️ 이것은 예외 목록이 아니다. `lane_check` 이 쓰는 것과 같은 형태의 원장이고
        **정확한 일치**를 요구한다:

          * 새 이름이 늘면 red — 누군가 이 상자에 없는 코드를 새로 불렀다.
          * 원장의 이름이 해소되면 **그것도 red** — 선언이 낡았다는 사실이고,
            `lane_check` 의 표현대로 *"그것도 소식이다"*.

        예외 목록은 한 방향으로만 자라서 조용히 낡는다. 원장은 양방향이라 낡을 수 없다.
        """
        observed = self.unresolvable_names
        by_name = {item.module: item for item in self._unresolvable}
        detail: list[str] = []
        for module in sorted(observed - set(known_unresolvable)):
            item = by_name[module]
            detail.append(
                f'  [새로 생김] {module!r} — 이 상자 안에도 없고 설치된 어떤 배포판도 '
                f'제공하지 않는다 (배포판 {item.distribution}). '
                f'부르는 곳: {", ".join(item.wheres[:3])}'
            )
        for module in sorted(set(known_unresolvable) - observed):
            detail.append(
                f'  [해소됨] {module!r} — 원장에 남아 있는데 이제 해소된다. 원장에서 지워라.'
            )
        return detail


# ──────────────────────────────────────────────────────────────────────────────
# ② 패키지 자원 폐포 — **실제로 휠을 빌드해서** 잰다
# ──────────────────────────────────────────────────────────────────────────────

class WheelBuildUnavailable(RuntimeError):
    """휠을 빌드하지 못해 이 축을 **잴 수 없다**. 통과가 아니다."""


class ResourceClosure:
    """배포판 하나의 패키지 자원 폐포.

    ⚠️ **실제로 휠을 빌드해서 잰다.** 선언(`package-data` 글롭)을 읽어서 재면 그 선언이
    틀렸을 때 검사도 같이 틀린다 — `decision_catalogue.json` 과 PM/RF 엑셀 서식이 정확히
    그렇게 빠졌다. 재는 대상은 선언이 아니라 **산출물**이어야 한다.

    ⚠️ 빌드는 트리 안에서 하지 않는다. non-editable 설치는 `build/` 를 남기고
    `lane_check` 은 그 트리에서 **판정을 거부한다**(`CONFOUNDING_ARTIFACTS`). 검사가
    자기가 재는 트리를 오염시키면 그 측정은 자기 자신의 부작용을 잰다.
    """

    def __init__(self, distribution: Distribution, *, repo_root: Path | None = None):
        self.distribution = distribution
        self.repo_root = (repo_root or distribution.root).resolve()
        self._workspace: tempfile.TemporaryDirectory | None = None
        self._wheel: zipfile.ZipFile | None = None

    # ── 생명주기 ─────────────────────────────────────────────────────────────

    def __enter__(self) -> 'ResourceClosure':
        self.build()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def build(self) -> zipfile.ZipFile:
        if self._wheel is not None:
            return self._wheel
        self._workspace = tempfile.TemporaryDirectory(prefix='fcc-supply-closure-')
        workspace = Path(self._workspace.name)
        staging = workspace / 'src'
        staging.mkdir()

        # 빌드 백엔드가 요구하는 최소 트리만 사본으로 옮긴다. 저장소 전체를 복사하면
        # apps/web/node_modules 까지 딸려와 이 검사가 분 단위가 된다.
        for name in ('pyproject.toml', 'README.md', 'LICENSE'):
            source = self.distribution.root / name
            if source.is_file():
                shutil.copy2(source, staging / name)
        for root in self.distribution.package_roots:
            shutil.copytree(
                root, staging / root.name,
                ignore=shutil.ignore_patterns(*NOT_SOURCE, '*.pyc'),
            )
        for path in self.distribution.module_files:
            shutil.copy2(path, staging / path.name)

        output = workspace / 'wheel'
        base = [sys.executable, '-m', 'pip', 'wheel', '--no-deps', '-w', str(output)]
        # 격리 없는 빌드를 먼저 시도한다: 네트워크를 타지 않아 빠르고, 러너가 오프라인
        # 이어도 성립한다. setuptools 가 없는 환경에서만 표준 격리 빌드로 되돌아간다.
        attempts = ([*base, '--no-build-isolation', str(staging)], [*base, str(staging)])
        failures: list[str] = []
        for command in attempts:
            completed = subprocess.run(command, capture_output=True, text=True)
            if completed.returncode == 0:
                break
            failures.append(completed.stderr[-800:])
        else:  # pragma: no cover — 빌드 자체가 불가능한 환경
            raise WheelBuildUnavailable(
                f'{self.distribution.name} 의 휠을 빌드하지 못해 이 축을 잴 수 없다 '
                f'(통과가 아니다):\n' + '\n---\n'.join(failures)
            )

        wheels = sorted(output.glob('*.whl'))
        if not wheels:  # pragma: no cover — pip 이 0 을 돌려줬는데 산출물이 없는 경우
            raise WheelBuildUnavailable('pip 이 0 을 돌려줬는데 휠이 없다')
        self._wheel = zipfile.ZipFile(wheels[-1])
        return self._wheel

    def close(self) -> None:
        if self._wheel is not None:
            self._wheel.close()
            self._wheel = None
        if self._workspace is not None:
            self._workspace.cleanup()
            self._workspace = None

    # ── 판정 ─────────────────────────────────────────────────────────────────

    @property
    def wheel(self) -> zipfile.ZipFile:
        if self._wheel is None:  # pragma: no cover — 사용 순서 방어
            raise RuntimeError('build() 를 먼저 불러야 한다')
        return self._wheel

    def source_resources(self) -> set[str]:
        """패키지 디렉터리 안의 비-.py 파일 전부 (저장소 루트 기준 상대 경로)."""
        resources: set[str] = set()
        for root in self.distribution.package_roots:
            for path in root.rglob('*'):
                if not path.is_file():
                    continue
                relative = path.relative_to(self.repo_root)
                if any(part in NOT_SOURCE for part in relative.parts):
                    continue
                if path.suffix == '.py' or path.suffix in _NOT_A_RESOURCE:
                    continue
                resources.add(str(relative).replace('\\', '/'))
        return resources

    def shipped_names(self) -> set[str]:
        return {name for name in self.wheel.namelist() if not name.endswith('/')}

    def missing_resources(self) -> list[str]:
        """소스에 있는데 휠에 없는 자원. 빈 리스트가 초록이다.

        휠 안의 이름은 **배포판 루트 기준**이고 소스 쪽은 저장소 루트 기준이라, 하위
        트리 배포판(`packages/fcc-test-kernel`)에서 두 좌표계가 어긋난다. 배포판 루트의
        접두사를 벗겨서 맞춘다 — 파생이지 표가 아니다.
        """
        shipped = self.shipped_names()
        try:
            prefix = self.distribution.root.resolve().relative_to(self.repo_root)
        except ValueError:  # pragma: no cover — 저장소 밖 배포판 방어
            prefix = Path('.')
        prefix_text = '' if str(prefix) == '.' else f'{prefix.as_posix()}/'

        missing: list[str] = []
        for resource in sorted(self.source_resources()):
            candidate = resource[len(prefix_text):] if prefix_text and resource.startswith(prefix_text) else resource
            if candidate not in shipped:
                missing.append(resource)
        return missing

    def shipped_module_count(self) -> int:
        """휠이 싣고 있다고 주장하는 `.py` 의 수 — 빈 휠이 통과로 읽히는 것을 막는다."""
        return len([name for name in self.wheel.namelist() if name.endswith('.py')])


def missing_resource_report(missing: list[str]) -> list[str]:
    return [f'  · {name}' for name in missing]
