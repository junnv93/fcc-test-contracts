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


⭐ 2026-09-05 — 원본 모노레포로 올리며 **가정 셋이 깨졌다**
────────────────────────────────────────────────────────────

두 상자는 이 모듈이 추출된 원본(`FCC_mobile_test_automation`)에서 나왔다. 원본에 이
축이 없으면 다음 추출이 같은 계급의 결함을 다시 상자로 실어 나르고, 그때는 상자의
게이트가 **배송 이후에** 그것을 발견한다. 그래서 판정기를 원본에 그대로 대 봤고,
암묵 가정 셋이 전부 거짓이었다. 셋 다 **조용히** 틀린다 — 그것이 요점이다.

  ① **「한 저장소 = `[project]` 절」** — 원본 `pyproject.toml` 에는 `[tool.pytest]`
     뿐이고 선언은 `requirements*.txt` 넷에 있다. 그 위에서 이 판정기는 배포판을
     **0개**로 세고, 0개는 「위반 없음」과 **같은 모양**이다.
     → 선언 출처를 파생으로 만들었다(`discover_distributions`).

  ② **「가상환경은 `.venv` 라는 이름을 갖는다」** — 원본은 그것을 `fcc_test_env/` 로
     부르고 **저장소 안에** 둔다. 그 안의 `pandas/pyproject.toml` 은 `[project]` 을
     가지므로, 이름으로 거르는 판정기는 **pandas 를 이 저장소가 내는 배포판**으로
     읽는다. 이름 목록은 반드시 낡는다 — 가상환경에는 정의가 있다(PEP 405).
     → `is_virtual_environment()` · `iter_source_files()`.

  ③ **「이름이 배포판과 다른 것(PyYAML→yaml)은 선언돼 러너에 설치되므로 정확한
     경로로 판정된다」** — 하드웨어 전용 의존이 많은 저장소에서 거짓이다.
     `Appium-Python-Client` 와 `python-docx` 는 **챔버 레인**의 것이라 중앙 러너에
     깔리지 않고, 이름도 달라 문자열 대조도 실패한다. 실측: 그 가정 위에서 계급 B 가
     러너에 따라 5건과 7건 사이를 오간다 — **같은 커밋에 대해**. 게이트의 답이 러너에
     의존하면 초록이 무엇을 뜻하는지 말할 수 없다.
     → `conventional_import_names()` 가 세 번째 경로다. 그리고 그것은 **대응표가
     아니다** — 손 대응표는 우리 의존성의 이름을 적으므로 의존성이 늘 때마다 낡는다.
     접사 규약은 PyPI 의 이름 짓기에 대한 것이고 우리 목록과 무관하다.
     ⚠️ 규약은 틀릴 수 있으므로 **믿지 않고 잰다** — `convention_misattributions()`
     가 설치돼 있어 진실을 알 수 있는 배포판 전량에 대고 예측을 대조한다.
"""
from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
import fnmatch
from importlib.metadata import packages_distributions
import os
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

#: 선언 출처가 `pyproject.toml` 이 아닐 때 그것을 대신하는 파일들.
#: ⚠️ 목록이 아니라 **글롭**이다 — 다섯 번째 레인이 생기면 이 게이트가 그것을 **본다**.
#: 나열했다면 늘어난 그것만 조용히 빠졌을 것이고, 그 조용함이 소비 레인의
#: `test_install_lists_pin_what_each_lane_imports.py` 가 이름 붙인 결함의 기전이다.
REQUIREMENTS_GLOB = 'requirements*.txt'

#: pip 이 주석으로 읽는 것 — 줄머리이거나 **공백 뒤**의 `#` 부터 끝까지.
#: ⚠️ 공백 조건이 필요하다. PEP 508 direct reference 의 URL 조각
#: (`…@kernel-v0.5.0#subdirectory=packages/fcc-test-kernel`) 에도 `#` 이 있고,
#: 조건 없이 자르면 그 줄이 이름만 남는 것이 아니라 **다른 줄이 된다**.
_INLINE_COMMENT = re.compile(r'(?:^|\s)#.*$')

#: 다른 목록을 끌어오는 지시자. 따라가지 않으면 include 너머의 선언이 「없는 것」이 되고
#: 이 게이트가 **실재하지 않는 결함**을 보고한다 — `requirements-web.txt` 가 정확히 그
#: 형상이다(`-r requirements.txt` 로 스무 줄을 끌어온다).
_REQUIREMENTS_INCLUDE = re.compile(r'^(?:-r|--requirement)[=\s]+(?P<path>\S+)')


# ──────────────────────────────────────────────────────────────────────────────
# 무엇이 소스가 **아닌가** — 이름이 아니라 성질로 판정한다
# ──────────────────────────────────────────────────────────────────────────────

def is_virtual_environment(directory: Path) -> bool:
    """이 디렉터리가 가상환경인가. PEP 405 가 `pyvenv.cfg` 로 그것을 정의한다.

    ⚠️ **이름으로 걸러서는 안 된다.** `NOT_SOURCE` 는 `.venv` 라는 철자를 알지만
    소비 레인 하나는 가상환경을 `fcc_test_env/` 로 부르고 **그것을 저장소 안에 둔다**.
    실측 2026-09-05: 그 트리에서 ``rglob('pyproject.toml')`` 은 설치된 `pandas` 의
    `pyproject.toml` 을 집어 와 **pandas 를 이 저장소가 내는 배포판으로** 읽는다.
    그리고 그 오독은 「배포판이 하나 더 있다」와 같은 모양이라 조용하다.

    이름을 하나 더 적는 것은 답이 아니다 — 그것이 이 축이 없애려는 형태다.
    가상환경에는 **정의가 있고**, 그 정의는 파일 하나의 존재로 판정된다.
    """
    return (directory / 'pyvenv.cfg').is_file()


def iter_source_files(root: Path, pattern: str = '*.py') -> Iterator[Path]:
    """`root` 아래의 소스 파일 — 비-소스 디렉터리를 **가지치기하며** 훑는다.

    ⚠️ `rglob` 이 아니라 `os.walk` 인 이유: `rglob` 은 가지치기를 못 한다. 걸러도
    **들어간 뒤에 버리는 것**이라, `node_modules/` 와 `fcc_test_env/` 를 가진 트리에서
    비용이 트리 크기가 아니라 **의존성 크기**로 정해진다. 실측 2026-09-05: 소비
    레인 모노레포는 소스 1,939 파일인데 그 두 디렉터리에 그 몇 배가 있다.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in NOT_SOURCE
            and not name.endswith('.egg-info')
            and not is_virtual_environment(here / name)
        )
        for filename in sorted(filenames):
            if fnmatch.fnmatch(filename, pattern):
                yield here / filename


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
# 선언 출처 ② — `requirements*.txt`
# ──────────────────────────────────────────────────────────────────────────────

def _requirement_lines(path: Path, *, seen: set[Path] | None = None) -> Iterator[tuple[Path, str]]:
    """이 목록이 **실제로** 선언하는 줄 전부 — `-r` 를 따라간 뒤의 것.

    돌려주는 것은 `(그 줄이 실제로 적힌 파일, 줄)` 이다. 어느 파일을 고치라고 말할 수
    있어야 하기 때문이다 — `requirements-web.txt` 의 선언 대부분은 `requirements.txt`
    에 적혀 있고, 「web 에 선언하라」는 처방은 거기서 틀린 답이 된다.
    """
    seen = set() if seen is None else seen
    resolved = path.resolve()
    if resolved in seen or not resolved.is_file():
        # ⚠️ 순환 include 를 무한 재귀로 만들지 않는다. 그리고 없는 파일을 가리키는
        #    `-r` 은 이 축의 결함이 아니다 — 설치기가 그것을 먼저 이름 대고 막는다.
        return
    seen.add(resolved)
    for raw in resolved.read_text(encoding='utf-8').splitlines():
        line = _INLINE_COMMENT.sub('', raw).strip()
        if not line:
            continue
        include = _REQUIREMENTS_INCLUDE.match(line)
        if include:
            yield from _requirement_lines(resolved.parent / include.group('path'), seen=seen)
            continue
        if line.startswith('-'):
            # `--index-url` · `--find-links` 같은 설치기 옵션. 배포판 선언이 아니다.
            continue
        yield resolved, line


def requirements_declarations(repo_root: Path) -> dict[Path, frozenset[str]]:
    """`requirements*.txt` 각각이 (include 를 따라간 뒤) 선언하는 배포판.

    ⚠️ **파일마다 따로 돌려준다.** 넷을 한 집합으로 합쳐 놓고 시작하면 「중앙에만
    필요한 것」과 「챔버 노드에도 필요한 것」이 같은 값이 되고, 그러면 *챔버에서만
    죽는 결함*을 볼 수 있는 축 자체가 사라진다. 합치는 것은 판정하는 쪽의 선택이고,
    그 선택을 하려면 합치기 **전의** 값이 남아 있어야 한다.
    """
    found: dict[Path, frozenset[str]] = {}
    for path in sorted(iter_source_files(repo_root, REQUIREMENTS_GLOB)):
        names = {requirement_name(line) for _, line in _requirement_lines(path)}
        found[path] = frozenset(name for name in names if name)
    return found


# ──────────────────────────────────────────────────────────────────────────────
# 배포판 이름 → import 이름, **설치 없이**
# ──────────────────────────────────────────────────────────────────────────────

#: 배포판 이름과 import 이름 사이에서 PyPI 가 실제로 쓰는 접사.
#:
#: ⚠️ **이것은 대응표가 아니다.** 표는 `appium-python-client → appium` 처럼 *우리
#: 의존성의 이름*을 적으므로 의존성을 추가할 때마다 자라고, 자라는 것을 잊으면 낡는다.
#: 아래는 *PyPI 의 이름 짓기 규약*이고 우리 의존성 목록과 무관하다 — 새 의존성이
#: 들어와도 이 튜플은 그대로다.
#:
#: ⚠️ 그리고 규약은 **틀릴 수 있다.** 그래서 이 모듈은 그것을 믿지 않고 잰다 —
#: `convention_misattributions()` 가 *설치돼 있어 진실을 알 수 있는* 배포판 전량에 대고
#: 규약의 예측을 대조한다. 재지 않는 규약은 손 대응표보다 나쁘다(틀려도 조용하다).
_LEADING_AFFIXES = ('python-', 'py')
_TRAILING_AFFIXES = ('-python-client', '-python', '-client')


def conventional_import_names(distribution_name: str) -> frozenset[str]:
    """이 배포판이 **아마도** 제공할 최상위 import 이름 (설치 없이 파생).

    실측되는 규약: `python-docx`→`docx` · `PyYAML`→`yaml` · `PyJWT`→`jwt` ·
    `Appium-Python-Client`→`appium` · `python-multipart`→`multipart`.

    ⚠️ 이 경로는 **계급 B 에만** 쓰인다. 이름이 러너에 설치돼 있으면
    `packages_distributions()` 가 정확한 답을 주고 그것이 언제나 이긴다. 규약은 설치가
    없어 정확한 답이 **존재하지 않는** 자리에서만 마지막으로 물어진다.
    """
    base = normalize(distribution_name)
    stems = {base}
    for prefix in _LEADING_AFFIXES:
        if base.startswith(prefix) and len(base) > len(prefix):
            stems.add(base[len(prefix):])
    for suffix in _TRAILING_AFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            stems.add(base[: -len(suffix)])
    # import 이름에는 `-` 가 올 수 없다. 규약은 `_` 로 바꾸거나 붙여 쓴다.
    names: set[str] = set()
    for stem in stems:
        names.add(stem.replace('-', '_'))
        names.add(stem.replace('-', ''))
    return frozenset(names)


def convention_misattributions(
    declared: frozenset[str] | set[str],
    provided: Mapping[str, list[str]] | None = None,
) -> list[str]:
    """규약이 **틀린 배포판에** 이름을 붙이는가 — 진실을 알 수 있는 자리에서 잰다.

    위험한 오예측은 「규약이 배포판 D 가 이름 N 을 준다고 했는데, 설치본에서 N 을
    실제로 주는 것은 **다른 배포판**인 경우」다. 그때 이 게이트는 선언되지 않은 의존을
    선언된 것으로 읽고 **조용히 통과**시킨다 — 규약을 넓힐 때 정확히 그 값이 든다.

    빈 리스트가 초록이다.
    """
    truth = packages_distributions() if provided is None else provided
    errors: list[str] = []
    for distribution_name in sorted(declared):
        for guess in sorted(conventional_import_names(distribution_name)):
            owners = truth.get(guess)
            if not owners:
                continue
            if normalize(distribution_name) not in {normalize(owner) for owner in owners}:
                errors.append(
                    f'  · 규약이 {distribution_name!r} 가 {guess!r} 를 제공한다고 했는데, '
                    f'설치본에서 그것을 제공하는 것은 {sorted(owners)} 다'
                )
    return errors


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
    #: 그 `pyproject.toml` 자신. `requirements*.txt` 에서 파생했으면 `None` 이다.
    pyproject_path: Path | None
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
    #: 그 선언을 **어느 파일이** 했는가 — `(경로, 이름 집합)` 의 정렬된 쌍.
    #:
    #: ⚠️ `declared` 는 이것의 합집합이지만, 합치기 **전의** 값이 여기 남아야 한다.
    #: 선언이 레인별 목록 넷으로 나뉜 저장소에서 그 넷을 한 집합으로만 들고 있으면
    #: 「중앙에만 필요한 것」과 「챔버 노드에도 필요한 것」이 같은 값이 되고, 그러면
    #: *챔버에서만 죽는 결함*을 볼 수 있는 축 자체가 사라진다. 이 모듈은 그 값을
    #: **보존만** 하고 판정하지 않는다 — 어느 코드가 어느 레인에 실리는가는 이 모듈이
    #: 알 수 없고(빌드 스크립트가 그 SSOT 다), 모르는 것을 판정하면 그것은 발명이다.
    declared_by: tuple[tuple[str, frozenset[str]], ...] = ()
    #: 이 선언에 매이는 것이 **트리 전체**인가.
    #:
    #: `[project]` 이 있으면 거짓이다 — 그 선언은 자기가 싣는 패키지에 대한 것이고,
    #: 스캔 범위도 거기서 파생된다. `requirements*.txt` 뿐인 저장소에서는 참이다:
    #: 그 목록들이 이 저장소가 가진 선언의 **전부**이므로, 저장소의 모든 파이썬이
    #: 그 선언에 매인다. 범위를 좁힐 근거가 트리 안에 없다.
    whole_tree: bool = False

    @property
    def is_installable(self) -> bool:
        """이 선언 단위가 **휠을 내는가.**

        `requirements*.txt` 는 설치 목록이지 배포 선언이 아니다 — 그것으로는 휠을
        만들 수 없고, 따라서 축 ②(패키지 자원 폐포)는 그 저장소에서 **잴 수 없다**.
        ⚠️ 잴 수 없는 것을 초록으로 읽지 마라. 부르는 쪽이 이 값을 보고 그 축을
        건너뛰되, **건너뛰었다는 사실을 말해야** 한다.
        """
        return self.pyproject_path is not None

    @property
    def declaration_label(self) -> str:
        """「어느 파일을 고치라」고 말할 때 쓰는 이름."""
        if self.pyproject_path is not None:
            return self.pyproject_path.name
        return ' · '.join(name for name, _ in self.declared_by) or REQUIREMENTS_GLOB

    def sources_declaring(self, name: str) -> tuple[str, ...]:
        """그 배포판을 선언한 파일들. 비어 있으면 아무도 선언하지 않았다는 뜻이다."""
        needle = normalize(name)
        return tuple(source for source, names in self.declared_by if needle in names)

    @property
    def scan_roots(self) -> tuple[Path, ...]:
        """이 배포판에 딸린 파이썬 전부 — 실리는 패키지 + 옆에서 도는 tests/scripts."""
        if self.whole_tree:
            return (self.root,)
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


def _distribution_from_requirements(repo_root: Path) -> Distribution | None:
    """`requirements*.txt` 들을 **하나의** 선언 단위로 읽는다. 없으면 `None`.

    ⭐ **왜 넷을 하나로 읽는가 — 그리고 그것이 무엇을 포기하는가.**

    이 저장소의 설치 목록은 넷(GUI · central · session-node · web)이고 서로 다르다.
    그러니 「목록마다 선언 단위 하나」가 자연스러워 보인다. **그런데 그렇게 하면 각
    단위의 스캔 범위가 전부 같은 트리가 된다** — 목록은 넷인데 소스는 하나뿐이기
    때문이다. 그 결과 이 게이트는 *모든* 목록이 *모든* import 를 선언하라고 요구하고,
    그것은 실측된 결정을 뒤집는다: 소비 레인은 `psycopg` 를 중앙에만 두고 세션 노드에는
    **두지 않기로** 판정했으며 그 부재를 시험 하나가 봉인하고 있다
    (`test_session_node_package.py::test_node_requirements_do_not_add_central_db_driver`).
    즉 「목록마다 하나」는 이미 옳다고 판정된 상태를 red 로 만든다.

    코드를 레인별로 가르려면 *어느 진입점이 어느 모듈을 담는가*를 알아야 하고, 그
    SSOT 는 빌드 스크립트다 — 이 모듈이 볼 수 없는 곳이다. 그것을 여기서 짐작하면
    두 번째 SSOT 가 생기고, 그것이 이 계열이 이미 값을 치른 형태다.

    그래서 이 모듈은 **합집합으로 판정하고, 나뉜 값은 `declared_by` 로 보존한다.**
    포기한 것은 분명하다: *어느 목록에도 없다*는 잡지만 *이 목록에만 없다*는 못 잡는다.
    후자의 축은 소비 레인의 `test_install_lists_pin_what_each_lane_imports.py` 가 이미
    갖고 있고 그쪽이 SSOT 다. 두 축은 겹치지 않는다 — 그쪽은 공유 레인 배포판
    (`fcc_test_*`)만 보고 레인별로 판정하며, 이쪽은 서드파티 전량을 보되 저장소
    단위로 판정한다.
    """
    declarations = requirements_declarations(repo_root)
    if not declarations:
        return None
    declared_by = tuple(
        (str(path.relative_to(repo_root)), names)
        for path, names in sorted(declarations.items())
    )
    return Distribution(
        name=repo_root.name,
        pyproject_path=None,
        root=repo_root,
        package_roots=(),
        module_files=(),
        declared=frozenset().union(*declarations.values()) if declarations else frozenset(),
        declared_by=declared_by,
        whole_tree=True,
    )


def discover_distributions(repo_root: Path) -> tuple[Distribution, ...]:
    """이 저장소의 **선언 단위** 전부 (파생).

    ⚠️ 목록을 인자로 받지 않는다. 목록을 적어 두는 순간 그 목록이 다음에 낡을 자리가
    되고, 그것이 이 축이 없애려는 바로 그 형태다. 실측: 이 레인은 배포판 2개
    (루트 `fcc-test-contracts` + `packages/fcc-test-kernel`), 소비 상자는 1개다.

    ⭐ **선언 출처도 파생이다.** 초판은 「한 저장소 = `[project]` 절」을 암묵 가정했다.
    두 상자에서는 참이지만 그 원본 모노레포에서는 **거짓**이다 — 그쪽 `pyproject.toml`
    에는 `[tool.pytest.ini_options]` 뿐이고 선언은 `requirements*.txt` 넷에 있다.
    그 가정 위에서 이 판정기는 배포판을 **0개**로 세고, 0개는 「위반 없음」과 같은
    모양이라 **조용히 초록**이다(실측 2026-09-05).

    그래서 출처를 파일 존재로 판정한다 — `[project]` 을 가진 `pyproject.toml` 이 하나라도
    있으면 그것들이 출처이고, 하나도 없으면 `requirements*.txt` 가 출처다. 둘 다 없으면
    선언 단위가 없고, 그때 이 함수는 **빈 튜플**을 돌려준다. ⚠️ 빈 튜플을 통과로 읽지
    마라 — 부르는 쪽이 그것을 이름 대고 막아야 한다.
    """
    found: list[Distribution] = []
    for path in sorted(iter_source_files(repo_root, 'pyproject.toml')):
        distribution = _distribution_from_pyproject(path)
        if distribution is not None:
            found.append(distribution)
    if found:
        return tuple(found)
    fallback = _distribution_from_requirements(repo_root)
    return (fallback,) if fallback is not None else ()


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
    #: 그 선언이 있어야 할 파일 — `pyproject.toml` 이거나 설치 목록들이다.
    declaration: str
    wheres: tuple[str, ...]

    def describe(self) -> str:
        return (
            f'  · {self.module!r} — {list(self.providers)} 가 제공하는데 '
            f'{self.declaration} 선언에 없다 (우연히 깔려 있을 뿐이다). '
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
    '고치는 법 — 선언 출처가 무엇인지에 따라 두 모양이다:\n'
    '  · `pyproject.toml` 이 출처이면 [project.dependencies](소스가 쓰면) 또는 '
    '[project.optional-dependencies] 의 적절한 extra(그 도구만 쓰면) 에 선언하라.\n'
    '  · `requirements*.txt` 가 출처이면 **어느 목록에** 적을지가 판정이다. 그 코드가 '
    '어느 레인에서 도는지 보고 그 레인의 목록에 적어라 — 넷 다에 적는 것은 답이 아니다 '
    '(그러면 챔버 노드가 중앙 전용 드라이버를 받는다).\n'
    '⚠️ import 에 try/except 가드를 다는 것으로 통과시키지 마라 — 그것은 '
    '그 경로의 검사를 조용히 끄는 것이고, 이 계열이 lane_check 에서 이미 이름 붙여 거부한 '
    '형태다("기준선을 관측값으로 덮어써서 초록을 만들지 마라 — 그것은 검사를 끄는 것이다").'
)

LEDGER_REMEDY = (
    '해소 불가 import 원장이 관측과 어긋난다:\n{report}\n\n'
    '[새로 생김] 의 고치는 법은 선언이 아니다. ⚠️ 원인이 **둘**이고 처방이 다르다:\n'
    '  (가) 그 코드가 이 저장소에 없다 — 협력자가 어느 레인에 사는지 보고, 이 상자가 그 '
    '레인을 통해 닿게 하거나, 그 코드가 이 상자의 것이 아니면 옮겨라.\n'
    '  (나) 그 코드는 이 저장소에 **있는데** 부르는 쪽이 `sys.path` 를 손봐서만 닿는다 '
    '(`sys.path.insert(0, .../어떤_하위디렉터리)` 뒤 그 자식을 최상위 이름으로 부르는 형상). '
    '이것은 공급 결함이 아니라 import 위생이다 — 패키지 경로로 부르게 고치면 사라진다. '
    '판정기의 first-party 파생은 최상위 소스 디렉터리의 **직계** 자식까지만 보고, 더 넓히면 '
    '트리 어딘가의 동명 파일이 실재하는 서드파티 미선언을 가린다.\n'
    '어느 쪽이든 그 판정을 내리기 전까지 원장에 넣는 것은 **사유와 날짜를 함께 적을 때만** '
    '정당하다.\n'
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
        self._conventional_cache: dict[str, frozenset[str]] = {}
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
            if distribution.whole_tree:
                # ⚠️ 이 저장소에는 **실리는 패키지가 없다.** 코드가 서로에게 닿는
                #    방법은 최상위 소스 디렉터리를 `sys.path` 에 얹는 것뿐이고
                #    (`sys.path.insert(0, str(SRC))`), 그러면 그 디렉터리의 **직계
                #    자식이 최상위 import 이름**이 된다 — `import application`,
                #    `import domain`. 저장소 루트만 훑으면 그 전부가 서드파티로
                #    오독된다. 실측 2026-09-05: 그렇게 오독되는 이름이 63개였다.
                for child in sorted(self.repo_root.iterdir()):
                    if (child.is_dir() and child.name not in NOT_SOURCE
                            and not child.name.startswith('.')
                            and not is_virtual_environment(child)):
                        names |= _importable_children(child)
                continue
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
                targets_files.extend(iter_source_files(root))
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

    def _conventional(self, distribution: Distribution) -> frozenset[str]:
        """이 선언 단위가 **설치 없이도** 제공한다고 규약이 말하는 import 이름 (캐시).

        ⚠️ 규약은 마지막 경로다. 설치본이 있으면 그것이 언제나 이긴다.
        """
        cached = self._conventional_cache.get(distribution.name)
        if cached is None:
            cached = frozenset().union(
                *(conventional_import_names(name) for name in distribution.declared)
            ) if distribution.declared else frozenset()
            self._conventional_cache[distribution.name] = cached
        return cached

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
                        distribution.declaration_label,
                    )
                continue
            # 설치돼 있지 않다. 이 검사가 도는 환경은 `[test]` 만 깔린 러너일 수 있고,
            # 다른 extra 나 다른 레인의 목록으로 선언된 것(챔버 전용 장비 드라이버 등)은
            # 여기 없는 것이 **정상**이다. 그때 남은 증거는 이름뿐이다.
            if normalize(site.module) in distribution.declared:
                continue
            # ⚠️ **세 번째 경로.** 초판은 여기서 멈추면서 이렇게 적었다: *"이름이
            # 배포판과 다른 경우(PyYAML→yaml)는 이 우회를 못 타지만, 그런 것은 선언돼
            # 러너에 설치되므로 위 정확한 경로로 판정된다."* **그 가정이 하드웨어 전용
            # 의존이 많은 저장소에서 깨진다** — `Appium-Python-Client` 와 `python-docx`
            # 는 선언돼 있지만 챔버 레인의 것이라 중앙 러너에는 깔리지 않고, 이름도
            # 달라 위 대조도 실패한다. 그러면 **선언을 지키고 있는 저장소가 red** 가
            # 된다(실측 2026-09-05).
            #
            # 그 결함은 오탐 둘보다 나쁘다: 이 게이트의 답이 **러너에 무엇이 깔려 있는지**
            # 에 따라 달라진다는 뜻이고, 그러면 초록이 무엇을 뜻하는지 말할 수 없다.
            # 규약으로 이름을 파생하면 그 의존이 끊긴다 — 설치 여부와 무관하게 같은 답이다.
            if site.module in self._conventional(distribution):
                continue
            unresolvable.setdefault(key, []).append(site.where)

        undeclared_result = [
            UndeclaredImport(
                module=module,
                providers=undeclared_meta[(module, dist_name)][0],
                distribution=dist_name,
                declaration=undeclared_meta[(module, dist_name)][1],
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
