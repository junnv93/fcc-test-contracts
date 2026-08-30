# tests/_migration_db_helper.py
"""마이그레이션 ``.py`` 를 임시 검증 DB 에 적용하는 공유 테스트 헬퍼 — Factory SSOT.

테스트가 마이그레이션 모듈(``up(cursor)``)을 transient 검증 DB 에 적용할 때
raw ``sqlite3.connect()`` 를 매 sprint 재구현하던 중복(``_apply_migration`` /
``_apply_migration_019`` 사본 다수)을 단일 진입점으로 통합한다. 모든 연결은
``SqliteConnectionFactory`` SSOT(PRAGMA 5개 — ``foreign_keys=ON`` 포함)를 거쳐
production SQLite 동작과 정합하며, ``test_wal_checkpoint_durability`` 의
scripts/tests raw-connect ratchet 를 신규 사이트가 깨지 않도록 구조적으로 보장한다
(raw connect 를 재도입할 유인 제거 = 반복 RED 의 근본 봉합).

**호출자가 자기 마이그레이션 패키지를 이름으로 준다 (2026-08-26).** 이 파일은
2026-08-26 까지 ``Path(__file__).parent.parent / 'src' / 'infrastructure' /
'database' / 'migrations'`` 를 스스로 조립하고 ``spec_from_file_location`` 으로
경로 로딩했다. 그 두 가지가 각각 결함이었다:

* **깊이 산술은 트리가 오늘 모양일 때만 옳다.** 저장소가 이미 두 번 같은 결론을
  냈다(마이그레이션 discovery · 성적서 템플릿 로더) — 패키지 아티팩트를
  ``__file__`` 산술로 찾지 말고 *내가 속한 트리*에 물어라. ``_base`` 자신이
  ``spec_from_file_location`` 을 frozen-safe 하지 않다는 이유로 **영구 폐기**
  한다고 적어 두고 있었고, 이 헬퍼만 그것을 계속 쓰고 있었다.
* **경로는 import 가 아니다.** 납품 레인 귀속은 파일이 *무엇을 import 하는가*
  하나만 증거로 읽으므로, 마이그레이션을 문자열 경로로 집어 오는 테스트는
  provider 레인 파일을 통째로 구동하면서도 기계에게는 그 사실을 한 글자도
  말하지 못했다. 그래서 ``044`` 테스트가 자기가 시험하는 마이그레이션이 들어
  있지 않은 ``fcc-test-contracts`` 상자에 실려 그 상자의 standalone import 를
  깼다. 같은 계급의 선례가 이미 매니페스트에 이름으로 있다
  (``tests/test_provider_service_deployment_evidence_cli.py``, 2026-08-16 —
  *"자기가 구동하는 모듈을 이름으로 부르자 기계가 읽을 수 있는 증거가 늘
  참이던 것을 말하게 됐다"*).

⚠️ **여기서 패키지를 대신 골라 주지 않는 것이 요점이다.** 헬퍼가 기본값으로
로컬 마이그레이션 패키지를 import 하면 헬퍼의 귀속만 옮겨 가고 호출자는 여전히
자기 대상에 대해 침묵한다 — 귀속은 파일 단위이기 때문이다. 그리고 그것은
*게이트를 속이려고 쓰지 않는 import 를 더하는 것*과 한 걸음 차이다. 인자로
받으면 호출자의 import 가 **실제로 쓰이는** 것이 되고, 헬퍼는 중앙 platform
마이그레이션처럼 다른 곳에 사는 패키지에도 그대로 쓸 수 있다.

FK-OFF 격리가 필요한 migration-DDL 단위 테스트(부모 row 없이 자식만 insert 해
CHECK/UNIQUE 를 격리 검증하는 경우)는 본 helper 대상이 아니다 — 그 경우는
``SqliteConnectionFactory(..., foreign_keys=False)`` 를 쓴다.

⚠️ **이 문단은 2026-08-26 에 정정됐다.** 옛 문언은 *"``_RAW_SQLITE3_CONNECT_KNOWN_BASELINE``
에 명시 근거와 함께 등재된 raw 사이트를 사용한다"* 였고, 그 처방은 **오늘 금지된 행위**다:
팩토리가 ``foreign_keys`` 축을 열면서 그 목록·증거 규칙·검증기가 소비자를 잃고 함께
삭제됐으며, 기본값이 거부로 뒤집혔다(새 raw 연결을 정당화할 어휘가 존재하지 않는다).
게이트와 어긋나는 처방을 남겨두면 그것을 믿은 세션이 정확히 그 자리에서 넘어진다.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType


def load_migration_module(package: ModuleType, name: str) -> ModuleType:
    """``package`` 안의 마이그레이션 ``name`` 을 import 하여 반환.

    Args:
        package: 그 마이그레이션을 소유한 패키지 모듈 자체 (예:
            ``from infrastructure.database import migrations``). 호출자가
            자기 대상을 이름으로 대는 자리이고, 모듈 이름은 여기서 파생한다 —
            문자열 패키지 경로를 받으면 이 파일이 다시 소유자를 안다고 주장하게
            되고 호출자의 import 는 다시 장식이 된다.
        name: 마이그레이션 파일 이름 또는 stem. ``'044_x.py'`` 와 ``'044_x'``
            둘 다 받는다 — 기존 호출자가 파일 이름으로 부르고 있었다.

    Returns:
        ``CHECKSUM: str`` + ``up(cursor) -> None`` 계약을 노출하는 모듈.
    """
    return importlib.import_module(f'{package.__name__}.{Path(name).stem}')


def apply_migrations(db_path, package: ModuleType, *names: str) -> None:
    """``names`` 를 순서대로 ``db_path`` 에 적용(파일당 ``up(cursor)`` 1회).

    각 마이그레이션은 ``SqliteConnectionFactory`` 연결에서 실행되어 production
    PRAGMA 정합을 유지한다(파일당 새 연결 — 기존 사이트 동작과 byte-equivalent).
    ``package`` 는 :func:`load_migration_module` 과 같은 뜻이고, 같은 이유로
    같은 자리에 있다 — 한 헬퍼가 "누가 패키지를 이름 대는가"에 두 가지로
    답하면 갈라지는 쪽은 늘 덜 쓰이는 쪽이다.
    """
    from fcc_test_contracts.common.sqlite_connection_factory import (
        SqliteConnectionFactory,
    )

    for name in names:
        mod = load_migration_module(package, name)
        conn = SqliteConnectionFactory(Path(db_path)).create()
        try:
            mod.up(conn.cursor())
            conn.commit()
        finally:
            conn.close()
