"""DB-API compatible output ports for platform adapters."""
from __future__ import annotations

from typing import Protocol


class DbCursor(Protocol):
    """PEP 249 커서 중 이 레인이 실제로 쓰는 부분.

    ⚠️ 이 세 줄은 «DB-API 호환»을 표방하면서 실물 드라이버를 탈락시키고 있었다.
    실측 2026-09-06 (mypy 2.3.1, psycopg 3.3.5) — **탈락 사유는 둘이다**::

        execute    반환     포트 ``-> None`` · psycopg ``-> Self``
        rowcount           "expected settable variable, got read-only attribute"

    둘 중 하나만 있어도 ``psycopg.Connection`` 이 ``DbConnection`` 을 만족하지 못하고
    (``cursor()`` 반환이 ``DbCursor`` 가 아니게 되어 연결까지 파생 탈락한다), 그 탈락은
    **소비 레인의 합성 지점에서만** 보인다 — 어댑터 인자가 ``Any`` 면 조용하다.
    소비 레인이 그동안 이 포트를 우회하고 있었던 이유다.

    ⚠️ **인자 «이름»은 사유가 아니다.** 포트는 ``statement``/``parameters``, psycopg 은
    ``query``/``params`` 인데 그것만으로는 안 걸린다 — mypy 는 positional-or-keyword
    인자의 이름을 서브타입 판정에서 무시한다. 축을 분리해 재서 확인했다(형제 세션의
    독립 측정과 일치)::

        class P(Protocol):
            def execute(self, statement: str, parameters: tuple) -> Any: ...
        class Impl:
            def execute(self, query: str, params: tuple) -> Any: ...
        take(Impl())                      # → Success

    ⚠️ 그래도 아래에서 ``/`` 를 쓴다. **이유가 다르다** — 구현을 통과시키려는 것이
    아니라, 이름을 노출하면 이 포트가 «어떤 드라이버도 못 지키는 호출 형태»를
    소비자에게 약속하게 되기 때문이다. 실측::

        def f(c: <이름 있는 포트>) -> None:
            c.execute(statement='x', parameters=())   # mypy: 통과
        psycopg.Cursor.execute(..., statement='x')    # 런타임: TypeError
                                                      #   unexpected keyword 'statement'
    """

    @property
    def rowcount(self) -> int:
        """PEP 249 는 이것을 «읽는» 속성으로 정의한다.

        ⚠️ ``rowcount: int`` (설정 가능 변수)로 적으면 읽기 전용 property 로 구현한
        실물이 탈락한다. 읽기 전용으로 적으면 property 도 평범한 속성도 둘 다
        만족한다 — 실측: 시험 대역들은 ``self.rowcount = 0`` 으로 두고 있고
        그대로 통과한다.
        """
        ...

    def execute(self, statement: str, parameters: tuple, /) -> object:
        """SQL 하나를 파라미터와 함께 보낸다.

        ⚠️ **위치 전용(`/`)이다.** 이름으로 부를 수 있게 두면 mypy 는 통과시키고
        실물이 런타임에 죽는다(위 클래스 docstring 의 실측). 이 레인은 그 형태를
        쓰지 않으므로 잃는 것이 없다 — 실측: 호출 66곳 전부 위치 인자, 키워드 0건.

        ⚠️ **반환을 쓰지 마라.** PEP 249 는 반환을 정의하지 않는다 — 드라이버마다
        다르다(psycopg 은 커서 자신을 준다). ``-> None`` 으로 못 박으면 «커서를
        돌려주는 모든 드라이버»가 탈락하므로 «정의되지 않음»을 ``object`` 로 적는다.
        실측: 이 포트를 통해 반환을 소비하는 자리 0건.
        """
        ...

    def close(self) -> None:
        ...


class DbConnection(Protocol):
    def cursor(self) -> DbCursor:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...
