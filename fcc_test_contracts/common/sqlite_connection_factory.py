"""SqliteConnectionFactory — raw ``sqlite3.connect()`` SSOT (2026-05-23).

Industry-standard architectural sealing for SQLite PRAGMA application. All
``sqlite3.Connection`` creation **repository-wide** — ``src/``, ``tests/`` and
``scripts/`` alike — goes through this factory so that the baseline PRAGMAs
(``locking_mode`` optional, ``journal_mode=WAL``, ``synchronous=NORMAL``,
``cache_size``, ``foreign_keys``, ``busy_timeout=SQLITE_BUSY_TIMEOUT_MS``) are
applied uniformly. Caller-side PRAGMA omission is structurally impossible.

Two of those are **axes, not fixed values** — ``locking_mode`` and (since
2026-09-09) ``foreign_keys``. The second one was opened to terminate a census:
fixtures that verify child-table constraints without their parent rows need
``foreign_keys=OFF``, and because this factory could not give them that, they
dropped to raw ``sqlite3.connect`` and lost the **other five** PRAGMAs as
collateral. A registry of "justified raw connections" then grew to roughly
1,100 lines to police the exemption. Opening one axis deleted that surface.

⚠️ ``src/`` may not take the ``foreign_keys`` axis. ``foreign_keys=ON`` on
production connections is a P0 invariant; the axis exists for test fixtures.
``tests/test_sqlite_connection_factory_foreign_keys.py`` seals that asymmetry
by censusing the **keyword** (not its value) across ``src/``.

Two surfaces:

- ``SqliteConnectionFactory`` — for **long-lived** connections (e.g., the
  ``SqliteNotificationOutboxJournal`` holds a connection for the lifetime of
  the journal instance). Caller owns ``close()``.
- ``SqliteConnectionContext`` — standard ``with`` block. ``__enter__`` delegates
  to ``SqliteConnectionFactory.create()``; ``__exit__`` closes the connection.
  Use this in scripts and tests where the connection is transient.

Hexagonal placement: ``application/common/`` (contracts-owned, dependency-free
— stdlib ``sqlite3`` only, 2026-08-13). No domain port — ``sqlite3.Connection``
is not used by the domain layer and the implementation is not pluggable
(single SQLite backend). Not infrastructure: nothing here reads ``domain/``,
``pandas``, ``openpyxl``, ``PySide6``, or ``pyvisa`` — it is a raw-``sqlite3``
connection helper any lane may use directly, not a hexagonal driven adapter.

PRAGMA application order matters:

1. ``locking_mode`` — must be set **before** ``journal_mode=WAL`` so that
   ``EXCLUSIVE`` locking applies to the WAL file when WAL is engaged. On
   Windows, ``EXCLUSIVE`` + WAL reduces OS-level file lock churn.
2. ``journal_mode=WAL`` — enables concurrent readers.
3. ``synchronous=NORMAL`` — durability/throughput tradeoff (committed
   transactions survive OS crash; safe under power loss with WAL).
4. ``foreign_keys`` — SQLite default is OFF; this factory turns it **on** per
   connection unless the caller explicitly opts out.
5. ``busy_timeout`` — final, after WAL is fully configured, so SQLITE_BUSY
   retry window covers concurrent writers via the configured WAL backend.

In-memory databases (``SQLITE_IN_MEMORY_DB``) are supported and are the
recommended target for schema/migration fixtures. ⚠️ ``journal_mode = WAL``
does **not** take on an in-memory database — SQLite keeps ``'memory'``. That is
SQLite semantics, not a defect here; the other four PRAGMAs apply normally.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, Union

from fcc_test_contracts.common.sqlite_pragma_policy import (
    SQLITE_CACHE_SIZE_KB,
    SQLITE_IN_MEMORY_DB,
    apply_baseline_pragmas,
)


__all__ = [
    'SqliteConnectionFactory',
    'SqliteConnectionContext',
    'SQLITE_IN_MEMORY_DB',
]


# Sentinel for ``isolation_level`` kwarg — stdlib ``sqlite3.connect()`` 의
# ``isolation_level`` 은 ``None`` (autocommit) 과 ``''`` (default deferred)
# 가 의미가 다르고, "kwarg 미전달" 의미를 표현할 별도 값이 없다. 본 sentinel
# 은 caller 가 명시적으로 stdlib default 를 원할 때 (kwarg 미전달과 동일 효과)
# 사용 — Python implementation detail (``''`` 가 magic) 에 의존하지 않는
# 산업 표준 패턴 (PEP 661 sentinel pattern).
_ISOLATION_LEVEL_UNSET: object = object()


class SqliteConnectionFactory:
    """Build a ``sqlite3.Connection`` with the project-wide baseline PRAGMAs.

    Long-lived caller pattern::

        factory = SqliteConnectionFactory(
            db_path, check_same_thread=False, locking_mode='EXCLUSIVE',
        )
        conn = factory.create()
        try:
            ...
        finally:
            conn.close()

    Transient caller pattern (prefer ``SqliteConnectionContext``)::

        with SqliteConnectionContext(db_path) as conn:
            conn.execute('SELECT 1')
    """

    def __init__(
        self,
        db_path: Union[str, Path],
        *,
        check_same_thread: bool = True,
        isolation_level: object = _ISOLATION_LEVEL_UNSET,
        locking_mode: Optional[str] = None,
        cache_size_kb: Optional[int] = SQLITE_CACHE_SIZE_KB,
        foreign_keys: bool = True,
    ) -> None:
        """Build factory with PRAGMA baseline.

        Args:
            db_path: SQLite database file path.
            check_same_thread: stdlib ``sqlite3.connect`` kwarg pass-through.
            isolation_level: stdlib ``sqlite3.connect`` kwarg. Default sentinel
                ``_ISOLATION_LEVEL_UNSET`` means "use stdlib default" (kwarg not
                forwarded). Pass ``None`` for autocommit, ``''`` for deferred,
                or ``'DEFERRED'``/``'IMMEDIATE'``/``'EXCLUSIVE'``.
            locking_mode: optional ``PRAGMA locking_mode`` value (e.g.
                ``'EXCLUSIVE'`` for the notification outbox). ``None`` keeps
                SQLite default NORMAL.
            cache_size_kb: ``PRAGMA cache_size`` value in KB. Default
                ``SQLITE_CACHE_SIZE_KB`` (64 MB — same SSOT used by the
                SQLAlchemy engine path). Small metadata DBs (e.g. notification
                outbox) should explicitly pass ``cache_size_kb=None`` to opt
                out and use the SQLite 2 MB default.
            foreign_keys: ``False`` applies ``PRAGMA foreign_keys = OFF``.
                **Test fixtures only** — see the module docstring. The other
                PRAGMAs are unaffected, which is the whole point: a fixture
                that needs FK off no longer has to give up WAL, ``synchronous``
                and ``busy_timeout`` to get it.
        """
        self._db_path = Path(db_path)
        self._check_same_thread = check_same_thread
        self._isolation_level = isolation_level
        self._locking_mode = locking_mode
        self._cache_size_kb = cache_size_kb
        self._foreign_keys = foreign_keys

    def create(self) -> sqlite3.Connection:
        """Return a fully-configured ``sqlite3.Connection``.

        The caller owns the lifetime — must call ``conn.close()`` when done,
        or wrap in ``SqliteConnectionContext`` for automatic cleanup.
        """
        conn_kwargs: dict = {'check_same_thread': self._check_same_thread}
        if self._isolation_level is not _ISOLATION_LEVEL_UNSET:
            # caller 가 명시적으로 ``None`` / ``''`` / ``'DEFERRED'`` 등 전달.
            conn_kwargs['isolation_level'] = self._isolation_level
        # ``str(Path(':memory:')) == ':memory:'`` on every platform (PurePosix
        # and PureWindows alike — measured), so the in-memory target name
        # survives the ``Path`` round-trip unchanged and needs no special case.
        # An earlier revision carried one; an independent review showed it was
        # dead code whose test could not fail. The property it was protecting is
        # asserted directly in
        # ``tests/test_sqlite_connection_factory_foreign_keys.py``.
        conn = sqlite3.connect(str(self._db_path), **conn_kwargs)
        # apply_baseline_pragmas SSOT — connection.py 와 단일 helper 공유.
        # PRAGMA 적용 순서 + 토큰 값이 engine path 와 drift 0 보장.
        apply_baseline_pragmas(
            conn.execute,
            locking_mode=self._locking_mode,
            cache_size_kb=self._cache_size_kb,
            foreign_keys=self._foreign_keys,
        )
        return conn

    @property
    def db_path(self) -> Path:
        return self._db_path


class SqliteConnectionContext:
    """Transient ``with`` block — closes the connection on exit.

    Intended call sites:
    - benchmark / latency measurement scripts (``scripts/bench_*.py``)
    - test fixtures / pytest tests
    - one-off maintenance scripts (DB inspection, ad-hoc queries)

    For connections that must outlive a single block (production code paths
    such as ``SqliteNotificationOutboxJournal``), use
    ``SqliteConnectionFactory.create()`` directly and manage close yourself.

    Production code paths SHOULD NOT introduce new use sites here without an
    architectural review — the long-lived ``Factory.create()`` pattern is the
    default for production wiring.
    """

    def __init__(
        self,
        db_path: Union[str, Path],
        *,
        check_same_thread: bool = True,
        isolation_level: object = _ISOLATION_LEVEL_UNSET,
        locking_mode: Optional[str] = None,
        cache_size_kb: Optional[int] = SQLITE_CACHE_SIZE_KB,
        foreign_keys: bool = True,
    ) -> None:
        self._factory = SqliteConnectionFactory(
            db_path,
            check_same_thread=check_same_thread,
            isolation_level=isolation_level,
            locking_mode=locking_mode,
            cache_size_kb=cache_size_kb,
            foreign_keys=foreign_keys,
        )
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> sqlite3.Connection:
        self._conn = self._factory.create()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # 표준 ContextManager 예외 처리 — caller 의 main exception 보존 우선.
        # ``conn.close()`` 가 자체 예외를 던지면:
        #   - caller block 이 예외 없이 끝났을 때 (exc_type is None): close 예외를
        #     re-raise (silent swallow 안 함 — 산업 표준 PEP 343 가이드).
        #   - caller block 이 예외 발생 (exc_type is not None): close 예외를
        #     silent 로 demote, caller exception 이 우선 propagate (DB cleanup
        #     실패가 user code error 를 masking 하지 않도록).
        if self._conn is None:
            return
        try:
            self._conn.close()
        except Exception:
            if exc_type is None:
                raise  # surface clean-path close failure
            # exc_type is not None → caller exception 우선 보존 (silent drop).
        finally:
            self._conn = None
