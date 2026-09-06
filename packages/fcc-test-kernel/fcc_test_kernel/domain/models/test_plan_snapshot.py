"""TestPlanSnapshot 도메인 DTO — TestRunner → GUI 데이터 전달 경계.

**출신**: 모노레포(`FCC_mobile_test_automation`)의 `src/domain/models/test_plan.py`.
2026-09-06 에 커널로 상류 수리됐다. 그 전까지 이 모델은 platform 배포판에만 있었고
(`fcc_test_platform.domain.models.test_plan`), 실소비자는 전부 모노레포 GUI 폐포였다 —
platform 배포판 안에는 소비자가 **0건**이었다. 모노레포 로컬 사본이 그 GUI→platform
의존을 레인 폐포에서 보이지 않게 하고 있었고, 사본을 걷어내자 드러났다. 형제 둘
(`published_test_plan` · `test_plan_authoring`)은 이미 커널에 있었으므로, 한 도메인의
세 모델이 두 배포판에 갈려 있던 상태가 이 이관으로 닫힌다.

**파일명** (`test_plan.py` 가 아닌 이유): `test_plan_authoring` 이 자기 docstring 에
「ADR-0009 가 지정한 `domain/models/test_plan.py` 를 `TestPlanSnapshot` 이 선점했다」고
적으며 대안으로 **`test_plan_snapshot.py` 로의 rename** 을 별도 sprint 로 미뤄 두었다
(2026-05-31). 이관이 어차피 모든 import 자리를 건드리므로 그 sprint 를 여기서 회수한다.
두 모듈은 같은 "test plan" 단어를 쓰지만 다른 bounded context 다 — 본 모듈 = 런타임
Excel 스냅샷, `test_plan_authoring` = capability-driven authoring/generation 도메인.

**purity**: stdlib (dataclass / typing) only. ``pandas`` 직접 import 금지 —
``from_dataframe`` factory 는 duck typing (``df.columns`` / ``df.to_dict('records')`` /
``df.index``) 만 쓴다. ``__len__`` 도 제공하여 호출자가 ``len(snapshot)`` 으로 행 수를
얻는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Display-value 정규화 SSOT — stringified null sentinel 토큰 세트.
#
# GUI 표/스냅샷에서 "null/NA 값" 을 빈 문자열로 렌더링하는 정책의 단일 출처.
# 각 토큰은 Python/pandas 가 null sentinel 을 ``str()`` 한 결과다:
#   - ``str(float('nan'))`` → ``'nan'``
#   - ``str(pandas.NA)``    → ``'<NA>'``
#   - ``str(pandas.NaT)``   → ``'NaT'``
#
# 도메인은 pandas-free 라 실제 null 값을 ``value != value`` (NaN-like) 로 검출하지만
# ``pandas.NA`` 는 ``!=`` 로 잡히지 않으므로 ``'<NA>'`` 토큰이 **기능상 필수**다.
#
# 이 토큰 세트에는 이 패키지 «밖»에 두 번째 자리가 있다: 모노레포 GUI 어댑터
# (`src/ui/table_model.py`) 가 ``pd.isna``/``fillna`` 로 실제 null 을 처리하되 동일
# 토큰 세트를 여기서 import 해 리터럴-문자열 케이스를 일관 처리한다. 두 구현의
# 동치성은 그쪽 저장소의 `tests/test_test_plan_page_invariants.py` 가 3-site
# equivalence invariant 로 봉인한다 — **그 봉인은 이 저장소에 없다.**
NULL_DISPLAY_TOKENS: frozenset[str] = frozenset({'nan', '<NA>', 'NaT'})


@dataclass
class TestPlanSnapshot:
    """테스트 플랜 스냅샷 DTO (Signal 경계용).

    수신 측(GUI/Web 어댑터)은 ``rows``/``columns``/``row_orders`` 만 사용한다 —
    pandas 누출 없음. 이전 ``data`` alias (deprecated DataFrame 첨부) 는
    2026-05-21 제거됨.

    [row_orders 필드 (2026-05-21 신설)]
    ``from_dataframe`` 이 ``df.to_dict('records')`` 로 rows 를 만들면 DataFrame
    의 ``index`` (=Excel 행 순서 row_order) 가 사라진다. ``row_orders`` 가
    이 정보를 별도로 보존하여 GUI 모델 (``TestPlanTableModel``) 이
    ``_row_order_map`` 을 정확히 재구성하고, ``cellsUpdated(row_order, ...)``
    가 올바른 행에 매핑되도록 한다.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: tuple[str, ...] = field(default_factory=tuple)
    row_orders: tuple[int, ...] = field(default_factory=tuple)
    display_rows: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    total_tests: int = 0
    completed_tests: int = 0

    def __len__(self) -> int:
        return self.total_tests

    @classmethod
    def from_dataframe(cls, df: Any) -> 'TestPlanSnapshot':
        """DataFrame-like 객체로부터 스냅샷 생성.

        Args:
            df: ``.columns``, ``.to_dict('records')``, ``.index`` 인터페이스를
                제공하는 객체(pandas.DataFrame). 도메인은 pandas를 import하지
                않고 duck typing만 사용한다.

        ``df.index`` 의 각 값은 ``int`` 로 변환 가능해야 한다 (Excel 행 순서).
        """
        original_columns = tuple(df.columns)
        columns = tuple(str(c) for c in original_columns)
        rows = df.to_dict(orient='records')
        row_orders = tuple(int(i) for i in df.index)
        display_rows = tuple(
            tuple(_normalize_display_value(row.get(col)) for col in original_columns)
            for row in rows
        )
        return cls(
            rows=rows,
            columns=columns,
            row_orders=row_orders,
            display_rows=display_rows,
            total_tests=len(rows),
        )


def _normalize_display_value(value: Any) -> str:
    """Return the same display string used by the GUI table model.

    Kept pandas-free for the domain boundary: DataFrame-like callers may pass
    pandas NA values, but this module still imports no pandas symbols.
    """
    if value is None:
        return ''
    try:
        if value != value:  # NaN/NaT-like values
            return ''
    except Exception:
        pass
    text = str(value)
    if text in NULL_DISPLAY_TOKENS:
        return ''
    return text

