"""Provider UI descriptor 가 쓰는 **컬럼 어휘의 계약 부분집합** (2026-08-31).

⚠️ 이것은 `column_names.Col` 의 **사본이 아니라 부분집합**이다. 그 모듈은 89개
토큰을 갖고 엑셀 읽기 전체를 떠받치며 **모노레포에 남는다** — 사용자의 측정
자산이기 때문이다. 여기 나온 것은 `provider_ui_descriptor` 가 **실제로 참조하는**
것뿐이고, AST 로 골랐지 손으로 나열하지 않았다.

⚠️ **왜 올렸나**: `fcc-test-platform` 의 소스 3파일(`platform_routes` 포함)이
`provider_ui_descriptor` 를 부르는데 그 모듈이 `column_names` 를 임포트해
**상자가 자족적이지 않았다.** 통째로 배송하면 89개가 전부 공개된다.
운영자 판정(2026-08-31): **어휘를 계약으로 올려 끊는다** — 나가는 것은
*이 화면이 표시하는 필드 이름들*이지 엑셀 읽기 코드가 아니다.

⚠️ **모든 토큰이 문자열인 것은 아니다.** 실측으로 셋이 걸렸다:
  * `ANT_GAIN` 과 `SHEET_ANT_GAIN` 이 **같은 값**(`'Ant gain'`) — Enum 은 뒤엣것을
    별칭으로 접어 32개가 31개가 된다. 화면이 두 필드를 구분하지 못하므로
    별칭 관계를 이름으로 남긴다.
  * `HISTORY_CONDITION` · `MATCH_DEFAULT` 는 **리스트**(매칭 키 목록)다 — Enum 값이
    될 수 없어 별도 상수로 둔다. 그냥 넣었다면 조용히 잘못됐을 것이다.
"""
from __future__ import annotations

from enum import Enum


class ProviderUiColumn(str, Enum):
    """`str` 상속 — 기존 `Col.*` 값과 동치 비교가 그대로 성립한다.

    ⚠️ 선언은 30개인데 멤버는 29개다 — 아래 별칭 때문이다.
    """

    ANTENNA = 'Antenna'
    ANT_GAIN = 'Ant gain'
    CENTER_FREQUENCY = 'Center Frequency'
    CHANNEL = 'Channel'
    CORE_SELECT = 'Core Select'
    DIRECTIONAL_GAIN = 'Directional Gain'
    LIMIT = 'Limit'
    MARGIN = 'Margin'
    ON_TIME = 'On Time'
    PASS_FAIL = 'Pass/Fail'
    PERIOD = 'Period'
    POWER_RESULT2 = 'Result2'
    RBW = 'RBW'
    REFERENCE_LEVEL = 'Reference Level'
    RESULT1 = 'Result1'
    RESULT2 = 'Result2(optional)'
    SHEET_ANALYZER_SETTINGS = 'Analyzer Settings'
    SHEET_ANT_GAIN = 'Ant gain'
    SHEET_CHAMBER_CONFIG = 'Chamber Config'
    SHEET_FREQUENCY_TABLE = 'Frequency Table'
    SHEET_SWITCH_PORT_MAPPING = 'Switch port mapping'
    SHEET_TEST_INFO = 'Test Info'
    SHEET_TEST_PLAN = 'Test Plan'
    SHEET_TEST_PLAN_POWER = 'Test Plan(Power)'
    SPAN = 'Span'
    SWEEP_POINTS = 'Sweep Points'
    SWEEP_TIME = 'Sweep Time'
    SWITCH_PORT = 'Switch port'
    TARGET_POWER = 'Target power'
    VBW = 'VBW'


#: ⚠️ 값이 같아 Enum 이 접은 쌍 — **의도된 별칭**임을 이름으로 남긴다.
#: 이것이 없으면 다음 사람이 «토큰 하나가 사라졌다»로 읽는다.
ALIASED_TOKENS: dict[str, str] = {'SHEET_ANT_GAIN': 'ANT_GAIN'}

#: Duty 측정이 사는 시트들.
DUTY_SHEETS: frozenset[str] = frozenset(['Duty', 'ax_Duty', 'be_Duty'])

#: ⚠️ 리스트 값 토큰 — Enum 이 담을 수 없어 상수로 둔다. 매칭 키 **목록**이고
#: 순서가 의미를 갖는다(비교 키를 그 순서로 조립한다).
HISTORY_CONDITION: tuple[str, ...] = ('Test', 'Technology', 'Band', 'Bandwidth', 'Channel', 'Tone', 'Location', 'Mode', 'Modulation', 'Antenna', 'Power Setting', 'Target power', 'Target power(ALL1)', 'Target power(ALL2)')
MATCH_DEFAULT: tuple[str, ...] = ('Test', 'Technology', 'Band', 'Bandwidth', 'Channel', 'Tone', 'Location', 'Mode', 'Modulation', 'Antenna')
