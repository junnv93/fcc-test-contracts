# application/common/sqlite_pragma_policy.py
"""SQLite baseline PRAGMA token + application-order SSOT (contracts-owned, 2026-08-13).

Split out of ``infrastructure/database/connection.py`` — applying a fixed
sequence of PRAGMA statements to a raw ``sqlite3`` connection is DB backend
plumbing, not measurement-domain knowledge, and it needed no SQLAlchemy engine
to define. Two callers share this module so the tokens and the order they are
applied in can never drift between them:

- ``infrastructure/database/connection.py`` — SQLAlchemy engine-managed
  connections via the ``'connect'`` event handler.
- ``application/common/sqlite_connection_factory.py`` — raw ``sqlite3.connect()``
  connections (the project's sole entry point for that call).

Both import ``apply_baseline_pragmas`` and the token constants from here
rather than redefining them; ``connection.py`` keeps exposing them as its own
module attributes for its existing consumers (P0 AST guards included) —
delegation, not a second definition.

PRAGMA application order matters (see ``apply_baseline_pragmas`` docstring).
Dependency-free: stdlib only, no ``sqlite3`` import required at this level
(the executor callable is injected by the caller).
"""
from __future__ import annotations


# PERF-2 SHOULD S-1 (2026-05-22) — SQLITE_BUSY tail-latency 봉합 SSOT (defense-in-depth).
#
# 산정 근거 (data-driven, magic number 회피):
# - WORST_CASE_WRITE_LATENCY_MS = 100ms — 가장 긴 단일 write tx 측정 상한.
# - BUSY_TIMEOUT_SAFETY_MARGIN = 50 — concurrent writer + WAL checkpoint +
#   GC pause outlier 흡수.
# - SQLITE_BUSY_TIMEOUT_MS = 100 x 50 = 5000ms. Django ORM default 와 동일.
WORST_CASE_WRITE_LATENCY_MS = 100
BUSY_TIMEOUT_SAFETY_MARGIN = 50
SQLITE_BUSY_TIMEOUT_MS = WORST_CASE_WRITE_LATENCY_MS * BUSY_TIMEOUT_SAFETY_MARGIN

# PRAGMA 토큰 SSOT (2026-05-23) — magic string 폐기, 모든 사용처 본 상수 import.
SQLITE_JOURNAL_MODE = 'WAL'
SQLITE_SYNCHRONOUS = 'NORMAL'
SQLITE_FOREIGN_KEYS = 'ON'
#: ``PRAGMA foreign_keys`` 를 끄는 토큰 (2026-09-09). 이 리터럴은 본 모듈 밖
#: ``src/`` 어디에도 있어서는 안 된다 — 끄는 결정은 ``foreign_keys_token`` 한
#: 곳을 지나야 하고, 그래야 "누가 껐는가" 가 grep 한 번으로 답해진다.
SQLITE_FOREIGN_KEYS_DISABLED = 'OFF'
# Engine-managed connection cache 용량 (KB). negative = -KB convention.
SQLITE_CACHE_SIZE_KB = 64000

#: SQLite in-memory database target (``sqlite3.connect(':memory:')`` 의 그 값).
#: 상수로 두는 이유는 편의가 아니라 **센서스** 다 — 이 리터럴을 각 테스트가
#: 다시 적으면 "in-memory 로 여는 자리가 어디인가" 를 이름으로 물을 수 없다.
#:
#: ⚠️ in-memory DB 에서 ``journal_mode = WAL`` 은 **조용히 적용되지 않는다**
#: (SQLite 는 ``'memory'`` 를 유지한다 — 의미론이지 결함이 아니다). 나머지
#: 넷(``synchronous``/``cache_size``/``foreign_keys``/``busy_timeout``)은 그대로
#: 적용된다. 실측 2026-09-09.
SQLITE_IN_MEMORY_DB = ':memory:'


def foreign_keys_token(enabled: bool) -> str:
    """``PRAGMA foreign_keys`` 값 토큰 — 켬/끔 두 철자의 단일 정의.

    호출자가 ``'ON'``/``'OFF'`` 를 직접 적지 않게 만드는 것이 요점이다. 두
    철자가 두 곳에 흩어지면 *"이 연결은 무결성을 검사하는가"* 라는 질문이
    문자열 비교가 되고, 그 질문은 이 저장소에서 측정값을 조용히 바꾼 적이 있다.
    """
    return SQLITE_FOREIGN_KEYS if enabled else SQLITE_FOREIGN_KEYS_DISABLED


def apply_baseline_pragmas(
    executor,
    *,
    locking_mode: str | None = None,
    cache_size_kb: int | None = SQLITE_CACHE_SIZE_KB,
    foreign_keys: bool = True,
) -> None:
    """SQLite PRAGMA baseline 적용 SSOT — single source of truth.

    raw ``sqlite3.Connection`` 의 ``conn.execute`` 와 SQLAlchemy event
    handler 의 ``cursor.execute`` 모두 동일 callable 시그니처를 사용하므로
    하나의 helper 가 양쪽 진입점에 적용 가능.

    Args:
        executor: ``conn.execute`` 또는 ``cursor.execute`` callable
            (SQL 문자열 1개 받음).
        locking_mode: ``None`` 시 미적용 (SQLite default — NORMAL).
            ``'EXCLUSIVE'`` 시 Windows file-lock churn 감소 (outbox 패턴).
        cache_size_kb: SQLite page cache 크기 (KB). ``None`` 시 미적용.
        foreign_keys: ``False`` 시 ``PRAGMA foreign_keys = OFF``. **기본값
            ``True`` 에서 발행 SQL 은 옛 형상과 byte-identical 이다.**

            이 인자가 존재하는 이유 (2026-09-09): 이 helper 는 여섯 PRAGMA 를
            **한 묶음으로만** 주었고, 그래서 그중 하나만 원하지 않는 자리 —
            부모 행 없이 자식 테이블의 CHECK/UNIQUE/NOT NULL 을 검사하는
            픽스처 — 가 **여섯 전부를 버리고** raw ``sqlite3.connect`` 로
            내려갔다. 그 이탈을 정당화하려고 증거 규칙 레지스트리가 1,100여
            줄까지 자랐다. 축을 하나 열어 그 표면 전체를 없앤다.

            ⚠️ **``src/`` 는 이 인자를 적을 수 없다.** production 연결의
            ``foreign_keys=ON`` 은 P0 불변식이고, 여기 열린 축은 테스트
            픽스처 전용이다. 그 비대칭은 사고가 아니라 설계이며
            ``tests/test_sqlite_connection_factory_foreign_keys.py`` 가
            ``src/`` 에서 이 키워드의 부재를 (값이 아니라 **키**로) 봉인한다.

    적용 순서 (drift 방지 단일 SSOT):
        1. ``locking_mode`` (옵션) — WAL 모드 진입 전 lock 결정
        2. ``journal_mode = WAL`` — 동시 readers 허용
        3. ``synchronous = NORMAL`` — durability + 처리량 균형
        4. ``cache_size = -KB`` (옵션) — SQLite spec § cache_size: 음수=KB
        5. ``foreign_keys = ON|OFF`` — referential integrity (per-connection)
        6. ``busy_timeout = SQLITE_BUSY_TIMEOUT_MS`` — SQLITE_BUSY retry window
    """
    if locking_mode:
        executor(f'PRAGMA locking_mode = {locking_mode}')
    executor(f'PRAGMA journal_mode = {SQLITE_JOURNAL_MODE}')
    executor(f'PRAGMA synchronous = {SQLITE_SYNCHRONOUS}')
    if cache_size_kb is not None:
        # SQLite spec § PRAGMA cache_size — 음수 N 은 N KB 의미.
        executor(f'PRAGMA cache_size = -{cache_size_kb}')
    executor(f'PRAGMA foreign_keys = {foreign_keys_token(foreign_keys)}')
    executor(f'PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}')
