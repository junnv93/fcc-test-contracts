"""``SqliteConnectionFactory`` 의 ``foreign_keys`` 축 봉인 (2026-09-09).

이 축은 편의 기능이 아니라 **표면 제거 도구**로 열렸다. 팩토리가 PRAGMA 여섯을
한 묶음으로만 주었기 때문에, 그중 하나(``foreign_keys=ON``)를 원하지 않는 픽스처는
**여섯 전부**를 버리고 raw ``sqlite3.connect`` 로 내려갔고, 그 이탈을 정당화하려고
증거 규칙 레지스트리가 1,100여 줄까지 자랐다. 축을 하나 열자 그 표면 전체가 사라졌다
(``tests/test_wal_checkpoint_durability.py::…::test_scripts_and_tests_have_no_raw_sqlite3_connect``).

그러므로 이 파일이 지켜야 하는 것은 셋이고 서로 다른 질문에 답한다:

1. **축이 실제로 흐르는가** — 키워드의 존재가 아니라 연결의 행동으로 묻는다.
   ``foreign_keys=…`` 를 받아 놓고 무시하는 구현은 키워드 검사를 통과한다.
2. **나머지 다섯은 그대로인가** — 이 축의 존재 이유가 *"하나 때문에 다섯을 잃지
   않는 것"* 이므로, 다섯이 딸려 꺼지면 축은 목적을 잃는다.
3. **``src/`` 는 이 축을 쓸 수 없는가** — production 연결의 ``foreign_keys=ON`` 은
   P0 불변식이다. 축을 여는 순간 그 불변식은 *기본값에 대해서만* 참이 되므로,
   그것을 다시 무조건 참으로 만드는 것은 이 봉인이다.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / 'src'
sys.path.insert(0, str(SRC_DIR))

from fcc_test_contracts.common import sqlite_pragma_policy  # noqa: E402
from fcc_test_contracts.common.sqlite_connection_factory import (  # noqa: E402
    SQLITE_IN_MEMORY_DB,
    SqliteConnectionContext,
    SqliteConnectionFactory,
)
from fcc_test_contracts.common.sqlite_pragma_policy import (  # noqa: E402
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_CACHE_SIZE_KB,
    SQLITE_FOREIGN_KEYS,
    SQLITE_FOREIGN_KEYS_DISABLED,
    apply_baseline_pragmas,
    foreign_keys_token,
)


#: 부모(``parent``)와 자식(``child``) 한 쌍. 자식은 부모를 참조하고, 부모는 비어 있다.
#: 그러므로 아래 INSERT 는 **FK 가 켜져 있으면 반드시 거부되고 꺼져 있으면 반드시
#: 통과한다** — 두 연결의 차이를 상태가 아니라 결과로 드러내는 최소 스키마다.
_SCHEMA = (
    'CREATE TABLE parent (id TEXT PRIMARY KEY);'
    'CREATE TABLE child ('
    '  id TEXT PRIMARY KEY,'
    '  parent_id TEXT NOT NULL REFERENCES parent(id)'
    ');'
)
_ORPHAN_INSERT = "INSERT INTO child (id, parent_id) VALUES ('c1', 'no-such-parent')"


def _pragma(conn: sqlite3.Connection, name: str):
    return conn.execute(f'PRAGMA {name}').fetchone()[0]


def _docstrings(tree: ast.AST) -> set[ast.AST]:
    """모듈/클래스/함수의 docstring 노드 집합.

    규칙을 **설명하는** 문장이 그 규칙의 위반으로 판정되면 사람들이 설명을
    지운다 — 이 저장소가 이미 이름 붙인 실패 모드다.
    """
    return {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }


#: ``PRAGMA foreign_keys`` **문장 머리**. 값이 아니라 머리를 세는 것이 요점이다.
#:
#: ⚠️ 초판은 값의 철자 두 개(``= OFF`` / ``=OFF``)를 열거했고 독립 적대적 평가가
#: 그 자리에서 셋을 뚫었다(2026-09-09): ``'PRAGMA foreign_keys = ' + 'OFF'`` ·
#: ``'PRAGMA foreign_keys = %s' % 'OFF'`` · 그리고 **``PRAGMA foreign_keys = 0``**
#: — 마지막 것은 열거의 실수가 아니라 SQLite 의 **1급 철자**다. 값을 세는 술어는
#: 값을 쓰는 방법의 수만큼 구멍을 갖고, 그 수는 닫히지 않는다.
#:
#: 머리를 세면 그 전부가 한 번에 닫힌다 — 이어 붙이든 포맷하든 보간하든 **첫
#: 조각에 머리가 들어 있어야** 그 문장이 되기 때문이다. 그리고 정당한 발행자는
#: 둘뿐이므로(아래 ``_pragma_emitter_paths``) 이 census 는 값을 몰라도 완전하다.
_FOREIGN_KEYS_PRAGMA_HEAD = 'PRAGMA foreign_keys'

#: 이 봉인이 **어느 트리에서 도는지**. 모노레포는 ``src/`` 지만, 이 파일은
#: 납품 ``fcc-test-contracts`` 상자에도 실려서 거기에는 ``src/`` 가 아예 없고
#: 모듈이 ``fcc_test_contracts/`` 아래로 재배치돼 있다. 경로 모양으로 적은 규칙은
#: 그 상자에서 **공허하게 통과**한다 — 실측 2026-09-09, 납품 트리 실행 축이 잡았다.
#: 프로덕션 소스로 세지 **않는** 최상위 디렉터리. 이 축이 묻는 것은 *production
#: 연결이 무결성을 끄는가* 이므로 테스트·문서·서드파티는 대상이 아니다.
_NON_PRODUCTION_DIRS = frozenset({
    'tests', 'docs', 'scripts', 'apps', 'packages', 'infra', 'resources', 'web',
    'migrations', 'artifacts', 'config', '.git', '__pycache__', 'node_modules',
    'fcc_test_env', 'build_nuitka',
})


def _source_root() -> Path:
    """이 트리의 프로덕션 소스 루트 — 모노레포면 ``src/``, 납품 상자면 상자 루트."""
    if (PROJECT_ROOT / 'src').is_dir():
        return PROJECT_ROOT / 'src'
    return PROJECT_ROOT


def _production_python_files():
    """프로덕션 ``*.py`` — 테스트 트리를 **뺀다**.

    ⚠️ 납품 상자에는 ``src/`` 가 없어서 루트가 상자 자체가 되고, 그러면 이 파일
    자신(``tests/…``)이 스캔에 들어와 **자기 프로브를 위반으로 고발**한다(실측
    2026-09-09). 축의 질문은 *production 연결*에 관한 것이므로 테스트 트리는
    애초에 대상이 아니다 — 상자에서만 드러난 것은 모노레포에서 ``src/`` 가
    그 배제를 우연히 해 주고 있었기 때문이다.
    """
    root = _source_root()
    for py in root.rglob('*.py'):
        rel = py.relative_to(root)
        if rel.parts and rel.parts[0] in _NON_PRODUCTION_DIRS:
            continue
        yield py, rel.as_posix()


#: 그 PRAGMA 를 발행해도 되는 모듈 — **경로가 아니라 모듈 정체성**으로 센다.
#: 납품 상자는 모듈을 재배치하므로 경로 문자열은 이식되지 않지만, import 이름은
#: 러너가 함께 재작성하므로 ``module.__file__`` 은 어느 트리에서든 그 모듈을
#: 정확히 가리킨다. 트리에 없는 발행자는 자연스럽게 부재로 답해진다.
#:
#: 둘 다 값을 **이름으로** 넣는다(``foreign_keys_token(...)`` /
#: ``SQLITE_FOREIGN_KEYS``) — 그래서 아래 문장-머리 census 에 걸리는 것은
#: *발행 사실*이지 *끄는 값*이 아니다.
def _pragma_emitter_paths() -> set[Path]:
    """이 트리에 **실재하는** 발행자들의 절대 경로."""
    import importlib

    found: set[Path] = set()
    for name in ('application.common.sqlite_pragma_policy',
                 'infrastructure.database.connection',
                 'fcc_test_contracts.common.sqlite_pragma_policy'):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        origin = getattr(module, '__file__', None)
        if origin:
            found.add(Path(origin).resolve())
    return found


def _static_text(node: ast.AST) -> str | None:
    """문자열 상수는 그 값, f-string 은 **보간되지 않는 부분**을 이어 붙인 텍스트."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return ''.join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return None


def _spells_foreign_keys_pragma(node: ast.AST) -> bool:
    text = _static_text(node)
    if text is None:
        return False
    return _FOREIGN_KEYS_PRAGMA_HEAD in text


def _foreign_keys_pragma_nodes(tree: ast.AST) -> list[ast.AST]:
    """트리 안에서 그 PRAGMA 를 적은 노드들 — f-string 은 **한 번만** 센다.

    ``ast.walk`` 는 ``JoinedStr`` 과 그 안의 ``Constant`` 조각을 **둘 다** 방문
    하므로 소박한 walk 는 f-string 하나를 둘로 세고, 그러면 "몇 곳인가" 를 묻는
    비-공허성 단언이 탐지 실패와 중복 계수를 구별하지 못한다. f-string 을
    만나면 그것을 세고 **내려가지 않는다**.
    """
    found: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.JoinedStr):
            if _spells_foreign_keys_pragma(node):
                found.append(node)
            return  # 조각을 다시 세지 않는다
        if _spells_foreign_keys_pragma(node):
            found.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return found


class TestTheForeignKeysAxisActuallyFlows(unittest.TestCase):
    """표기가 아니라 **효과**. 상태 조회와 행동 대조군을 모두 요구한다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix='fk_axis_')
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / 'fk.db'

    def _connect(self, **kwargs) -> sqlite3.Connection:
        conn = SqliteConnectionFactory(self.db, **kwargs).create()
        self.addCleanup(conn.close)
        return conn

    def test_default_connection_enforces_foreign_keys(self) -> None:
        conn = self._connect()
        self.assertEqual(_pragma(conn, 'foreign_keys'), 1)

    def test_opting_out_disables_foreign_keys(self) -> None:
        conn = self._connect(foreign_keys=False)
        self.assertEqual(_pragma(conn, 'foreign_keys'), 0)

    def test_the_two_connections_disagree_about_an_orphan_row(self) -> None:
        """행동 축 — 같은 스키마, 같은 INSERT, 반대 결과.

        ``PRAGMA foreign_keys`` 조회만 단언하면 *"토큰이 도착했다"* 까지만 말한다.
        픽스처들이 실제로 사는 이유는 **부모 없는 자식 행이 들어가는 것**이므로,
        그 사건 자체를 양방향으로 단언한다. 대조군(기본 연결)이 없으면 이 봉인은
        "무엇이든 통과시킨다" 와 구별되지 않는다.
        """
        setup = self._connect()
        setup.executescript(_SCHEMA)
        setup.commit()

        relaxed = self._connect(foreign_keys=False)
        relaxed.execute(_ORPHAN_INSERT)
        relaxed.commit()
        self.assertEqual(
            relaxed.execute('SELECT count(*) FROM child').fetchone()[0], 1,
            'FK-off connection failed to accept the orphan row it exists to accept',
        )

        strict = self._connect()
        with self.assertRaises(sqlite3.IntegrityError):
            strict.execute(
                "INSERT INTO child (id, parent_id) VALUES ('c2', 'no-such-parent')"
            )

    def test_opting_out_keeps_every_other_pragma(self) -> None:
        """축의 존재 이유 — 하나를 끄려고 나머지를 잃지 않는다.

        옛 형상에서 이 픽스처들은 raw ``sqlite3.connect`` 였고, 그것은 FK 하나를
        끄는 대가로 WAL · ``synchronous`` · ``busy_timeout`` · ``cache_size`` 를
        **전부** 기본값(각각 delete / FULL / 0 / -2000)으로 되돌렸다. 즉 한 축을
        이탈하려고 다섯 축을 이탈했다.
        """
        conn = self._connect(foreign_keys=False)
        self.assertEqual(_pragma(conn, 'journal_mode').upper(), 'WAL')
        self.assertEqual(_pragma(conn, 'synchronous'), 1)
        self.assertEqual(_pragma(conn, 'busy_timeout'), SQLITE_BUSY_TIMEOUT_MS)
        self.assertEqual(_pragma(conn, 'cache_size'), -SQLITE_CACHE_SIZE_KB)

    def test_context_manager_carries_the_axis(self) -> None:
        """``SqliteConnectionContext`` 는 팩토리의 얇은 래퍼지만 인자를 **잃을 수 있다**."""
        with SqliteConnectionContext(self.db, foreign_keys=False) as conn:
            self.assertEqual(_pragma(conn, 'foreign_keys'), 0)
        with SqliteConnectionContext(self.db) as conn:
            self.assertEqual(_pragma(conn, 'foreign_keys'), 1)


class TestTheDefaultPathIsUnchanged(unittest.TestCase):
    """기본 경로는 옛 형상과 **발행 SQL 문자열 단위로** 같아야 한다.

    PRAGMA 순서·철자는 이 저장소가 이미 SSOT 로 못박은 성질이고(순서가 의미를
    갖는다 — ``locking_mode`` 는 WAL 진입 **전**), 축을 하나 더하면서 그것을
    건드렸는지는 *결과 상태*가 아니라 *발행된 문장*을 봐야 알 수 있다.
    """

    _EXPECTED_DEFAULT = (
        'PRAGMA journal_mode = WAL',
        'PRAGMA synchronous = NORMAL',
        f'PRAGMA cache_size = -{SQLITE_CACHE_SIZE_KB}',
        'PRAGMA foreign_keys = ON',
        f'PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}',
    )

    def test_default_emission_sequence_is_byte_identical(self) -> None:
        emitted: list[str] = []
        apply_baseline_pragmas(emitted.append)
        self.assertEqual(tuple(emitted), self._EXPECTED_DEFAULT)

    def test_locking_mode_still_precedes_wal(self) -> None:
        emitted: list[str] = []
        apply_baseline_pragmas(emitted.append, locking_mode='EXCLUSIVE')
        self.assertEqual(emitted[0], 'PRAGMA locking_mode = EXCLUSIVE')
        self.assertEqual(tuple(emitted[1:]), self._EXPECTED_DEFAULT)

    def test_opting_out_changes_exactly_one_statement(self) -> None:
        """차분이 **한 줄**임을 단언한다 — 어느 줄인지까지 이름으로 댄다."""
        default: list[str] = []
        relaxed: list[str] = []
        apply_baseline_pragmas(default.append)
        apply_baseline_pragmas(relaxed.append, foreign_keys=False)
        self.assertEqual(len(default), len(relaxed))
        differing = [
            (a, b) for a, b in zip(default, relaxed) if a != b
        ]
        self.assertEqual(
            differing,
            [('PRAGMA foreign_keys = ON', 'PRAGMA foreign_keys = OFF')],
        )


class TestTheTokenHasOneDefinition(unittest.TestCase):
    def test_token_helper_answers_both_ways(self) -> None:
        self.assertEqual(foreign_keys_token(True), SQLITE_FOREIGN_KEYS)
        self.assertEqual(foreign_keys_token(False), SQLITE_FOREIGN_KEYS_DISABLED)
        self.assertNotEqual(SQLITE_FOREIGN_KEYS, SQLITE_FOREIGN_KEYS_DISABLED)

    def test_only_the_sanctioned_emitters_write_that_pragma(self) -> None:
        """``src/`` 에서 ``PRAGMA foreign_keys`` 를 적는 자리는 **둘뿐**이다.

        ⚠️ 이 질문은 두 번 바뀌었고 두 번 다 실측이 바꿨다.

        1. 초판은 *"토큰 ``'OFF'`` 가 정책 모듈에만 있는가"* 를 물었다. ``'OFF'`` 는
           SCPI(``INIT:CONT OFF``)와 삼성 AT 어휘에도 정당하게 살아서 무관한 네
           파일을 고발했다(``sidebar.py`` · ``measurements/IBE.py`` ·
           ``domain/models/eut_at_command.py`` · ``at_response_parser.py``).
           무관한 도메인을 고발하는 가드는 allowlist 를 얻고, allowlist 를 얻은
           가드는 다음 위반을 그 목록 뒤에 숨긴다.
        2. 2판은 *"끄는 값의 철자가 있는가"* 를 물었고 **독립 적대적 평가가 그
           자리에서 셋을 뚫었다** — 이어 붙이기 · ``%`` 포맷 · 그리고
           ``PRAGMA foreign_keys = 0``(SQLite 의 1급 철자). 값을 세는 술어는
           값을 쓰는 방법의 수만큼 구멍을 갖고 그 수는 닫히지 않는다.

        지금 묻는 것은 **문장 머리**다. 값을 몰라도 완전하고, 위 셋이 한 번에
        닫힌다 — 어떻게 조립하든 **첫 조각에 머리가 있어야** 그 문장이 된다.
        그리고 정당한 발행자가 둘뿐이라 예외 목록이 짧고 그 둘은 사유를 갖는다:
        정책 모듈은 SSOT 이고, ``connection.py`` 의 read-only 엔진은
        ``journal_mode`` 가 write 라서 baseline helper 를 쓸 수 없다.

        docstring 은 대상이 아니다 — 규칙을 **설명하는** 문장이 그 규칙의 위반이면
        사람들이 설명을 지운다.
        """
        emitters = _pragma_emitter_paths()
        offenders: list[str] = []
        emitters_seen: set[Path] = set()
        for py, rel in _production_python_files():
            text = py.read_text(encoding='utf-8', errors='ignore')
            if _FOREIGN_KEYS_PRAGMA_HEAD not in text:
                continue
            resolved = py.resolve()
            tree = ast.parse(text, filename=str(py))
            docstrings = _docstrings(tree)
            for node in _foreign_keys_pragma_nodes(tree):
                if node in docstrings:
                    continue
                if resolved in emitters:
                    emitters_seen.add(resolved)
                    continue
                offenders.append(f'{rel}:{node.lineno}')
        self.assertFalse(
            offenders,
            f'production source writes PRAGMA foreign_keys outside the '
            f'sanctioned emitters: {offenders}. Production keeps referential '
            'integrity on (P0); the value belongs to foreign_keys_token().',
        )
        # ⚠️ Judge against the emitters **this tree actually has**. This file
        # travels in the delivered ``fcc-test-contracts`` box, where there is no
        # ``src/`` at all and ``infrastructure/database/connection.py`` is a
        # different lane's module — a path-shaped rule passes vacuously there
        # (measured 2026-09-09 by the delivered-tree run axis, which is the only
        # axis that could see it). Resolving the emitters through *module
        # identity* asks the same question in both trees.
        self.assertTrue(
            emitters, 'no sanctioned emitter is importable in this tree at all',
        )
        self.assertEqual(
            emitters_seen, emitters,
            'a sanctioned emitter stopped writing that PRAGMA — the exemption '
            'list now shelters a path that does not need it, and this census '
            'would keep passing while an emitter silently moved elsewhere.',
        )

    def test_the_pragma_detector_is_not_vacuous(self) -> None:
        """탐지기가 실제 위반을 보고, 이웃 도메인을 고발하지 않는지 합성으로 묻는다.

        아래 offending 넷은 **독립 적대적 평가가 실제로 뚫은 형상**이다(2026-09-09).
        값의 철자를 세던 술어는 그 넷 중 셋을 통과시켰다.
        """
        offending = {
            'spaced OFF': "x = 'PRAGMA foreign_keys = OFF'",
            'unspaced OFF': "x = 'PRAGMA foreign_keys=OFF'",
            'the numeric spelling': "x = 'PRAGMA foreign_keys = 0'",
            'string concatenation': "x = 'PRAGMA foreign_keys = ' + 'OFF'",
            'percent formatting': "x = 'PRAGMA foreign_keys = %s' % 'OFF'",
            'f-string with the token helper': (
                "x = f'PRAGMA foreign_keys = {foreign_keys_token(False)}'"
            ),
            'inside executescript': "c.executescript('PRAGMA foreign_keys = OFF;')",
        }
        for label, source in offending.items():
            tree = ast.parse(f'def f(c, foreign_keys_token):\n    {source}\n')
            hits = _foreign_keys_pragma_nodes(tree)
            self.assertEqual(len(hits), 1, f'{label}: detector missed a real offender')

        harmless = {
            'an SCPI OFF': "x = 'INIT:CONT OFF'",
            'an AT command OFF': "x = '+FCBTTEST:OFF'",
            'a different pragma': "x = 'PRAGMA query_only = OFF'",
            'a neighbouring pragma': "x = 'PRAGMA foreign_key_list(child)'",
            'the bare word': "x = 'foreign_keys'",
        }
        for label, source in harmless.items():
            tree = ast.parse(f'def f():\n    {source}\n')
            hits = _foreign_keys_pragma_nodes(tree)
            self.assertEqual(hits, [], f'{label}: detector invented an offender')


def _calls_passing_foreign_keys(tree: ast.Module) -> list[ast.Call]:
    """``foreign_keys=`` 키워드를 **넘기는** 호출들.

    판정은 값이 아니라 **키**다. ``foreign_keys=False`` 만 찾으면
    ``foreign_keys=flag`` 한 줄에 진다 — 이 저장소가 이미 이름 붙인 실패
    모드("A keyword that exists is not a value that flows" 의 반대 방향).
    정의부(``def apply_baseline_pragmas(..., foreign_keys=True)``)는
    ``ast.Call`` 이 아니므로 구조적으로 대상이 아니다.

    ⚠️ **``**`` 언팩도 offender 다.** ``SqliteConnectionFactory(p, **opts)`` 의
    키는 정적으로 알 수 없으므로 *"그 키를 안 넘겼다"* 를 말할 수 없다. 독립
    적대적 평가가 정확히 ``**{'foreign_keys': False}`` 로 이 술어를 뚫었다
    (2026-09-09). 모르는 것을 통과시키는 방향은 이 봉인이 막으려는 바로 그
    실패이므로 **모르면 고발한다** — ``src/`` 의 이 세 이름에 대한 ``**`` 호출은
    오늘 0건이라 비용도 0이다.
    """
    targets = {
        'SqliteConnectionFactory',
        'SqliteConnectionContext',
        'apply_baseline_pragmas',
    }
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if any(kw.arg == 'foreign_keys' for kw in node.keywords):
            found.append(node)
            continue
        if _call_target_name(node) in targets and any(
            kw.arg is None for kw in node.keywords
        ):
            found.append(node)
    return found


def _call_target_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _assignments_to_private_axis(tree: ast.Module) -> list[ast.AST]:
    """``obj._foreign_keys = …`` — 생성자를 우회해 축을 뒤집는 자리.

    독립 적대적 평가가 ``f._foreign_keys = False`` 로 키워드 census 를 우회했다
    (2026-09-09). 인자를 막고 그 인자가 쓰는 슬롯을 열어 두면 봉인은 관용구
    하나를 막은 것이지 능력을 막은 것이 아니다.
    """
    found: list[ast.AST] = []
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == '_foreign_keys':
                found.append(node)
    return found


class TestProductionCannotTakeTheAxis(unittest.TestCase):
    """P0 보존 — ``src/`` 는 이 인자를 적을 수 없다.

    이 봉인이 없으면 ``CLAUDE.md`` 의 *"PRAGMA 5개 … ``foreign_keys=ON`` 자동
    적용"* 은 **기본값에 대해서만** 참인 문장이 되고, 그것이 언제 깨졌는지
    아무 게이트도 답하지 못한다.
    """

    #: 이 축을 정의하는 두 모듈은 자기 시그니처 안에서 이름을 쓴다. 판정은
    #: **파일 이름**이다 — 납품 상자가 모듈을 재배치하므로 경로 모양은 이식되지
    #: 않고, 경로로 적은 면제는 그 상자에서 조용히 빗나간다(2026-09-09 실측).
    _OWNER_FILENAMES = frozenset({
        'sqlite_pragma_policy.py',
        'sqlite_connection_factory.py',
    })

    def test_src_passes_no_foreign_keys_keyword(self) -> None:
        offenders: list[str] = []
        for py, rel in _production_python_files():
            if py.name in self._OWNER_FILENAMES:
                continue
            text = py.read_text(encoding='utf-8', errors='ignore')
            if 'foreign_keys' not in text:
                continue
            tree = ast.parse(text, filename=str(py))
            for call in _calls_passing_foreign_keys(tree):
                offenders.append(f'{rel}:{call.lineno} (passes the axis)')
            for node in _assignments_to_private_axis(tree):
                offenders.append(f'{rel}:{node.lineno} (writes the private slot)')
        self.assertFalse(
            offenders,
            'src/ reaches the foreign_keys axis: '
            f'{offenders}. Production connections keep referential integrity on '
            '(P0). The axis exists for test fixtures only.',
        )

    def test_the_detector_sees_a_planted_offender(self) -> None:
        """비-공허성 — 스캔 집합이 아니라 **탐지기**에 건다.

        위 단언의 정상 결과는 빈 목록이므로 그 목록에 앵커를 걸 수 없다(정상
        상태에서 red 가 난다). 대신 탐지기가 실제 offender 를 보는지, 그리고
        가까운 비-offender 를 보지 **않는지**를 합성 소스로 묻는다.
        """
        offending = {
            'literal False': 'SqliteConnectionFactory(p, foreign_keys=False)',
            'a variable': 'SqliteConnectionFactory(p, foreign_keys=flag)',
            'literal True': 'SqliteConnectionFactory(p, foreign_keys=True)',
            'the context class': 'SqliteConnectionContext(p, foreign_keys=False)',
            'alongside a sibling kwarg': (
                'apply_baseline_pragmas(e, locking_mode=None, foreign_keys=False)'
            ),
            # ⚠️ 아래 셋은 독립 적대적 평가가 **실제로 뚫은** 형상이다 (2026-09-09).
            'a dict-splat hiding the key': (
                "SqliteConnectionFactory(p, **{'foreign_keys': False})"
            ),
            'a splat of an opaque mapping': 'SqliteConnectionContext(p, **opts)',
            'a splat into the policy helper': 'apply_baseline_pragmas(e, **opts)',
        }
        for label, expression in offending.items():
            tree = ast.parse(f'def f(p, flag, e, opts):\n    return {expression}\n')
            self.assertEqual(
                len(_calls_passing_foreign_keys(tree)), 1,
                f'{label}: the detector missed a call that passes the axis',
            )

    def test_the_detector_sees_a_write_to_the_private_slot(self) -> None:
        """생성자를 막고 슬롯을 열어 두면 관용구 하나를 막은 것에 그친다."""
        offending = {
            'plain assignment': 'f._foreign_keys = False',
            'annotated assignment': 'f._foreign_keys: bool = False',
            'self assignment outside the owner': 'self._foreign_keys = False',
        }
        for label, statement in offending.items():
            tree = ast.parse(f'def g(f, self):\n    {statement}\n')
            self.assertEqual(
                len(_assignments_to_private_axis(tree)), 1,
                f'{label}: the detector missed a write to the private slot',
            )
        for label, statement in {
            'a read, not a write': 'x = f._foreign_keys',
            'a similarly named slot': 'f._foreign_keys_off = False',
            'a local of that name': '_foreign_keys = False',
        }.items():
            tree = ast.parse(f'def g(f):\n    {statement}\n')
            self.assertEqual(
                _assignments_to_private_axis(tree), [],
                f'{label}: the detector invented an offender',
            )

        harmless = {
            'no kwarg at all': 'SqliteConnectionFactory(p)',
            'a similarly named kwarg': 'SqliteConnectionFactory(p, foreign_keys_off=1)',
            'the word in a string': "SqliteConnectionFactory(p, locking_mode='foreign_keys')",
            'an attribute of that name': 'SqliteConnectionFactory(p.foreign_keys)',
        }
        for label, expression in harmless.items():
            tree = ast.parse(f'def f(p):\n    return {expression}\n')
            self.assertEqual(
                _calls_passing_foreign_keys(tree), [],
                f'{label}: the detector invented an offender',
            )

    def test_the_definitions_are_not_mistaken_for_call_sites(self) -> None:
        """정의부는 ``ast.Call`` 이 아니다 — 그 사실에 기대고 있으므로 단언한다."""
        source = textwrap.dedent(
            '''
            def apply_baseline_pragmas(executor, *, foreign_keys=True):
                pass
            '''
        )
        self.assertEqual(_calls_passing_foreign_keys(ast.parse(source)), [])


class TestInMemoryTargetIsSupported(unittest.TestCase):
    """``:memory:`` 는 아홉 픽스처의 도착지이고, 그 넷만 적용된다."""

    def test_constant_is_the_sqlite_target_name(self) -> None:
        self.assertEqual(sqlite_pragma_policy.SQLITE_IN_MEMORY_DB, ':memory:')
        self.assertIs(SQLITE_IN_MEMORY_DB, sqlite_pragma_policy.SQLITE_IN_MEMORY_DB)

    def test_in_memory_connection_is_really_in_memory(self) -> None:
        """두 연결이 같은 이름을 열어도 **서로의 테이블을 보지 못한다**.

        ``PRAGMA database_list`` 의 빈 파일 경로만 보면 *"파일이 아니다"* 까지만
        말한다. 픽스처가 이 대상에 의지하는 성질은 **격리**이므로 그것을 잰다.
        """
        first = SqliteConnectionFactory(SQLITE_IN_MEMORY_DB).create()
        second = SqliteConnectionFactory(SQLITE_IN_MEMORY_DB).create()
        try:
            first.execute('CREATE TABLE only_here (id TEXT)')
            with self.assertRaises(sqlite3.OperationalError):
                second.execute('SELECT * FROM only_here')
        finally:
            first.close()
            second.close()

    def test_wal_does_not_take_on_an_in_memory_database(self) -> None:
        """⚠️ 이것은 결함이 아니라 SQLite 의미론이고, **적어 두는 것이 요점**이다.

        in-memory DB 는 ``journal_mode`` 를 ``'memory'`` 로 유지한다. 이 사실을
        적지 않으면 다음 세션이 *"팩토리가 WAL 을 적용한다"* 는 문장을 그대로
        믿고 여기에 단언을 걸었다가 red 를 만나고 팩토리를 의심한다.
        """
        conn = SqliteConnectionFactory(SQLITE_IN_MEMORY_DB).create()
        try:
            self.assertEqual(_pragma(conn, 'journal_mode').upper(), 'MEMORY')
            # 나머지 넷은 정상 적용된다 — 그래서 이 대상이 팩토리를 쓸 값어치가 있다.
            self.assertEqual(_pragma(conn, 'synchronous'), 1)
            self.assertEqual(_pragma(conn, 'foreign_keys'), 1)
            self.assertEqual(_pragma(conn, 'busy_timeout'), SQLITE_BUSY_TIMEOUT_MS)
            self.assertEqual(_pragma(conn, 'cache_size'), -SQLITE_CACHE_SIZE_KB)
        finally:
            conn.close()

    def test_the_target_name_survives_the_path_round_trip_on_every_platform(self) -> None:
        """팩토리는 대상을 ``Path`` 로 담았다가 ``str`` 로 되돌려 넘긴다.

        ⚠️ 초판은 이 사실을 특수 분기(``_connect_target``)로 **처리**했고, 독립
        적대적 평가가 그 분기를 항등으로 바꿔도 배터리가 초록임을 보였다
        (2026-09-09) — 분기가 no-op 이었고 그것을 단언하던 테스트는 실패할 수
        없었다. 분기는 삭제했다. 남은 것은 그 삭제를 **정당화하는 성질**이고,
        그것은 우리 코드가 아니라 ``pathlib`` 의 성질이므로 양 플랫폼 flavour
        에 직접 묻는다. 언젠가 거짓이 되면 여기가 red 로 알려준다.
        """
        for flavour in (PurePosixPath, PureWindowsPath):
            with self.subTest(flavour=flavour.__name__):
                self.assertEqual(str(flavour(SQLITE_IN_MEMORY_DB)), ':memory:')
        # 그리고 팩토리가 실제로 그 왕복을 거쳐 in-memory DB 를 연다.
        conn = SqliteConnectionFactory(Path(SQLITE_IN_MEMORY_DB)).create()
        try:
            self.assertEqual(
                conn.execute('PRAGMA database_list').fetchall(), [(0, 'main', '')],
            )
        finally:
            conn.close()

    def test_in_memory_still_honours_the_foreign_keys_axis(self) -> None:
        conn = SqliteConnectionFactory(
            SQLITE_IN_MEMORY_DB, foreign_keys=False,
        ).create()
        try:
            self.assertEqual(_pragma(conn, 'foreign_keys'), 0)
            conn.executescript(_SCHEMA)
            conn.execute(_ORPHAN_INSERT)
            self.assertEqual(
                conn.execute('SELECT count(*) FROM child').fetchone()[0], 1,
            )
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
