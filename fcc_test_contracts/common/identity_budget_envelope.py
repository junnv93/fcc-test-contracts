"""신원 축 예산 봉투 — 순수 도메인 (2026-08-23).

이 모듈이 존재하는 이유는 **숫자 하나가 아니라 인구 하나**다.

## ⚠️ 두 숫자가 같은 인구를 센다 — 따로 정하면 아무도 그 불일치를 설명하지 못한다

이 저장소에는 *"한 시험원이 얼마나 쓰는가"* 에서 파생돼야 하는 예산이 **둘** 있다:

* **리프레시 회전 subject 당 상한** — 오늘 **없다**. ``refresh`` 는 ``public`` 이고
  bcrypt 가 없어 실측 **380 회전/초**가 가능하다.
* **자격증명 경로의 출처당 상한** — 오늘 기본값을 상속한다. ADR-0021 ``D-11`` 이
  그것을 조이려다 **착지 전에 철회**했다(시험원 30명이 정상 비밀번호로 로그인하는데
  절반이 429).

둘은 같은 사실(*한 시험원이 동시에 몇 세션을 운영하는가*)에서 나와야 하고, 각자
정하면 나중에 두 숫자가 같은 인구에 대해 다른 답을 갖는다. ADR-0021 ``R-10`` 이
그것을 이름으로 경고한다 — *"두 웨이브가 각자 봉투를 발명하는 것이 두 숫자가 어긋나는
방법이다"*. **그래서 인구는 이 모듈 하나가 소유한다.**

## ⚠️ 이 모듈은 «지어낸 숫자» 를 하나도 갖지 않는다

입력 넷은 전부 **이미 존재하는 값**이거나 **운영자가 답한 값**이다:

===========================  =========  =====================================
입력                          값         출처
===========================  =========  =====================================
시험원 1인 동시 세션          **4**      운영자 답변 2026-08-22 (*"3~4개"*)
액세스 토큰 수명              900초      ``local_identity`` (application 계층)
클라이언트 갱신 여유          30초       ``session.ts::MIN_REFRESH_MARGIN_SECONDS``
창 길이                       60초       ``rate_limit_policy.DEFAULT_WINDOW_SECONDS``
===========================  =========  =====================================

⚠️ **상한을 취한다("3~4" → 4).** 하한으로 사이징하면 운영자가 *정상이라고 말한 동선*이
거부된다. 이 축에서 과소평가의 대가는 과대평가의 대가보다 훨씬 비싸다 — refresh 429 는
**시험 도중 로그아웃**이다.

⚠️ **TTL 은 인자로 받는다.** ``DEFAULT_LOCAL_JWT_ACCESS_TTL_SECONDS`` 는
``application/common/local_identity.py`` 에 살고 도메인은 application 을 import 하지
않는다. 형제 ``analyzer_reset_policy`` 가 같은 이유로 같은 모양을 갖는다 — 순수 술어는
여기, env/상수 결속은 application 경계.

## 왜 이 예산이 «비율» 이 아니라 «버스트» 인가

한 세션은 액세스 토큰이 만료에 가까워질 때 회전하므로 **정당한 회전 주기**는
``access_ttl − margin`` = 870초다. 60초 창에서 그것은 **1회 미만**이다. 즉 정상
트래픽의 정상 상태 소비는 0에 가깝고, 예산 전체가 **버스트 여유**다.

버스트의 정상 최악은 *"모든 세션이 같은 순간에 회전"* 이고(네트워크 단절 복구,
노트북 절전 해제), 거기에 실패 재시도 한 번이 더해진다 — 세션당 **2회**. 그것이
:data:`REFRESH_RETRY_ALLOWANCE` 의 전부이고 그 이상은 없다.

⚠️ **«안전 계수» 라는 이름의 지어낸 배수를 두지 않는다.** 배수에 이름을 주면 다음
세션이 그것을 늘려도 아무 단언도 red 가 되지 않는다. 이 상수는 *두 번*이라는 관측
가능한 사건을 세고, 그 사건이 무엇인지 이 문단이 적는다.

## ⚠️ 이 모듈은 출처당 상한을 **조이지 않는다**

파생식을 제공할 뿐이다. 실제로 조이는 것은 **관측이 `observed-distinct` 를 답한 뒤**의
판단이고(:mod:`domain.services.peer_axis_observation`), 그 전에 조이면 ``D-11`` 을
글자 그대로 반복한다. 그러므로 여기서 파생되는 출처 예산은 *"조이려면 이 식에서
나와야 한다"* 는 **소유권 선언**이지 적용된 값이 아니다.
"""
from __future__ import annotations

from math import ceil


__all__ = [
    'CONCURRENT_SESSIONS_PER_TESTER',
    'DENIAL_ASYMMETRY_MARGIN',
    'MEASURED_UNTHROTTLED_ROTATIONS_PER_SECOND',
    'MINIMUM_CONTROL_REDUCTION_FACTOR',
    'REFRESH_RETRY_ALLOWANCE',
    'burst_headroom_ratio',
    'control_reduction_factor',
    'modelled_worst_case',
    'modelled_worst_case_headroom',
    'refresh_rotation_budget',
    'seconds_between_legitimate_rotations',
    'source_rotation_budget',
    'steady_state_rotations_per_window',
    'unthrottled_rotations_per_window',
]


#: 한 시험원이 **동시에** 운영하는 세션 수. 운영자 답변 2026-08-22: *"3~4개"*.
#:
#: ⚠️ **상한을 취한 것이 판단이다** — 3 으로 사이징하면 네 번째 탭을 연 시험원이
#: 정상 동선에서 거부된다. 이 축에서 과소평가는 *시험 도중 로그아웃*을 뜻한다.
#:
#: ⚠️ **이 값이 이 모듈의 유일한 인구 사실이고, 두 예산이 여기서 파생한다.** 값을
#: 고치면 두 파생값이 **함께** 움직인다 — 봉인이 그 연동을 단언한다. 하나만 손으로
#: 고칠 수 있게 두면 그 순간 두 숫자가 다른 인구를 세기 시작한다.
CONCURRENT_SESSIONS_PER_TESTER = 4

#: 한 세션이 한 창 안에서 정당하게 회전할 수 있는 **최대 횟수**.
#:
#: 정상 상태는 창당 1회 미만이다(아래 :func:`steady_state_rotations_per_window`).
#: 2 인 이유는 두 사건이 실재하기 때문이다 — 회전이 실패해 클라이언트가 **다시
#: 시도**하는 경우, 그리고 절전에서 깨어난 세션이 만료 직후 **한 번 더** 회전하는 경우.
#:
#: ⚠️ 이것은 «안전 계수» 가 아니라 **사건의 개수**다. 늘리려면 세 번째 사건의 이름을
#: 대야 한다.
REFRESH_RETRY_ALLOWANCE = 2

#: 모델 위에 두는 **여유 배수**. ⚠️ *"안전 계수"* 라는 이름의 지어낸 숫자가 아니라,
#: 두 오류의 값이 다르다는 사실에서 나온다.
#:
#: 초판은 예산을 정확히 ``sessions × allowance`` 로 잡았다. 그것은 **모델 위가 아니라
#: 모델 그 자체**여서, 모델을 한 걸음만 벗어난 정상 동선(``is_allowed`` 는
#: ``count <= max`` 이므로 여덟 번째는 통과하고 아홉 번째가 거부된다)이 곧바로
#: **시험 도중 로그아웃**이 됐다. 적대 평가 2R 이 그 경계를 실행으로 짚었다.
#:
#: 모델이 틀릴 수 있는 자리는 이미 알려져 있다 — 브라우저 세션 저장소는 **탭 단위**라
#: 시험원이 여는 탭 수는 "동시 세션 수" 와 같지 않고, 네트워크 복구가 한 번으로 끝난다는
#: 보장도 없다. 즉 ``sessions × allowance`` 는 *정상의 상한*이 아니라 *정상의 추정*이다.
#:
#: 두 오류의 값:
#:
#: * **거짓 거부** — 시험 도중 로그아웃. 측정이 끊기고 시험원이 재현할 수 없다.
#: * **거짓 허용** — 분당 8회 대신 32회. 이 경로의 실측 공격 속도는 **초당 380회
#:   = 분당 22,800회** 이므로, 32 는 그 **0.14%** 다. 즉 여유를 4배로 넓혀도 이 tier 가
#:   막으려는 것에 대해서는 사실상 아무 차이가 없다.
#:
#: 비대칭이 이만큼 크면 예산은 모델 **위**에 있어야 한다. 4 는 그 판단이고, 위 두
#: 숫자(1.0 배 → 4.0 배 / 공격 대비 0.14%)가 검사 가능한 형태로 남는다.
DENIAL_ASYMMETRY_MARGIN = 4


def _positive(value: object, fallback: float) -> float:
    """총 판독 — 읽을 수 없거나 비양수면 fallback.

    이 함수들은 **부팅 경로**(정책 조립)에서 돌고, 그 호출에는 ``try/except`` 가 없다.
    산술이 던지면 예산 대신 트레이스백이 나오고, 더 나쁘게는 *정책 자체가 조립되지
    않는다*. 형제 ``proxy_trust_policy`` 가 같은 이유로 총함수다.
    """
    try:
        number = float(value)  # type: ignore[arg-type]
    except Exception:
        # ⚠️ **``(TypeError, ValueError)`` 로는 총함수가 성립하지 않는다.**
        # ``__float__`` 은 임의의 예외를 던질 수 있고, 첫 판은 실제로 그렇게 짜여
        # 있다가 자체 총함수 배터리에 잡혔다. 형제 ``peer_axis_observation._flag``
        # 가 ``__bool__`` 에 대해 같은 이유로 같은 모양을 갖는다 — 판독 불가는
        # 예외가 아니라 **fallback** 으로 분류한다.
        return float(fallback)
    if number != number or number in (float('inf'), float('-inf')):
        return float(fallback)
    return number if number > 0 else float(fallback)


def seconds_between_legitimate_rotations(
    *, access_ttl_seconds: object, refresh_margin_seconds: object,
) -> float:
    """한 세션이 회전 사이에 두는 **정당한 간격**(초).

    클라이언트는 액세스 토큰이 만료되기 ``refresh_margin_seconds`` 전에 회전하므로
    간격은 ``ttl − margin`` 이다. 여유가 수명 이상인 병리적 구성에서는 간격이 0 이하가
    되는데, 그때는 *"쉬지 않고 회전한다"* 가 아니라 **구성이 틀린 것**이므로 수명
    전체를 답한다(0 을 답하면 아래 나눗셈이 무한대가 되고 예산이 무한이 된다).
    """
    ttl = _positive(access_ttl_seconds, 1.0)
    margin = _positive(refresh_margin_seconds, 0.0) if refresh_margin_seconds else 0.0
    interval = ttl - margin
    return interval if interval > 0 else ttl


def steady_state_rotations_per_window(
    *,
    access_ttl_seconds: object,
    refresh_margin_seconds: object,
    window_seconds: object,
    sessions_per_tester: object = CONCURRENT_SESSIONS_PER_TESTER,
) -> float:
    """정상 상태에서 한 시험원이 한 창 안에 내는 회전 수 (분수 허용).

    분수를 그대로 답하는 것이 요지다 — 올림하면 *"0.28 회"* 가 *"1 회"* 가 되고,
    아래 :func:`burst_headroom_ratio` 가 측정하려는 여유가 사라진다.
    """
    interval = seconds_between_legitimate_rotations(
        access_ttl_seconds=access_ttl_seconds,
        refresh_margin_seconds=refresh_margin_seconds,
    )
    window = _positive(window_seconds, 1.0)
    sessions = _positive(sessions_per_tester, CONCURRENT_SESSIONS_PER_TESTER)
    return sessions * (window / interval)


def modelled_worst_case(
    *,
    sessions_per_tester: object = CONCURRENT_SESSIONS_PER_TESTER,
    retry_allowance: object = REFRESH_RETRY_ALLOWANCE,
) -> int:
    """모델이 말하는 정상 최악 — 모든 세션이 동시에 회전 + 각자 한 번 재시도.

    ⚠️ **이것은 예산이 아니다.** 예산은 이 값 **위**에 있어야 한다
    (:data:`DENIAL_ASYMMETRY_MARGIN` 참조) — 모델과 같으면 모델을 한 걸음 벗어난
    정상 동선이 곧바로 거부된다.
    """
    sessions = _positive(sessions_per_tester, CONCURRENT_SESSIONS_PER_TESTER)
    allowance = _positive(retry_allowance, REFRESH_RETRY_ALLOWANCE)
    return max(1, int(ceil(sessions * allowance)))


def modelled_worst_case_headroom(
    *,
    sessions_per_tester: object = CONCURRENT_SESSIONS_PER_TESTER,
    retry_allowance: object = REFRESH_RETRY_ALLOWANCE,
    margin: object = DENIAL_ASYMMETRY_MARGIN,
) -> float:
    """예산이 **모델의 몇 배**인가. 1.0 이면 모델이 곧 경계라는 뜻이다.

    ⚠️ 형제 :func:`burst_headroom_ratio` 는 *정상 상태* 대비를 답하고 그 값은 크다
    (29배). 그 숫자만 인용하면 «넉넉하다» 로 읽히지만, 정작 거부가 일어나는 자리는
    **버스트** 이고 거기서의 여유는 이 함수가 답한다. 초판이 그 둘을 섞어 1.0 배를
    29배라고 적었다.
    """
    budget = refresh_rotation_budget(
        sessions_per_tester=sessions_per_tester,
        retry_allowance=retry_allowance,
        margin=margin,
    )
    modelled = modelled_worst_case(
        sessions_per_tester=sessions_per_tester,
        retry_allowance=retry_allowance,
    )
    return budget / modelled if modelled else float('inf')


#: 이 경로에서 **상한이 없을 때** 실측된 공격 속도(초당 회전). ``refresh`` 는
#: ``public`` 이고 bcrypt 가 없어 이 값이 나온다. 여기 있는 이유는 하나다 — 예산이
#: 여전히 **통제**인지 판정하려면 «통제가 없을 때 무슨 일이 일어나는가» 라는 외부
#: 기준점이 필요하고, 그것 없이는 어떤 예산이든 «충분히 넉넉하다» 를 만족시킬 수
#: 있다(적대 평가 4R: 두 줄만 고치면 예산이 32→320 이 되는데 봉인 넷이 전부 초록).
MEASURED_UNTHROTTLED_ROTATIONS_PER_SECOND = 380

#: 예산이 «통제» 로 남기 위해 무상한 속도 대비 줄여야 하는 최소 배율.
#:
#: ⚠️ 이 숫자에 이론적 유도는 없다 — 있는 것은 **판단**이고, 판단이므로 이름을 갖고
#: 여기 적혀 있다: 스로틀이 달성 가능 속도를 **두 자릿수 이상** 줄이지 못하면 그것은
#: 통제가 아니라 장식이다. 이 상수를 올려서 봉인을 통과시키려는 다음 사람은, 바로
#: 그 순간 자기가 무엇을 하고 있는지 읽게 된다.
MINIMUM_CONTROL_REDUCTION_FACTOR = 100


def unthrottled_rotations_per_window(*, window_seconds: object) -> float:
    """상한이 없을 때 한 창 안에 가능한 회전 수 — 측정에서 파생.

    창 길이를 **인자로 받는** 이유는 형제들과 같다: 이 모듈은 정책 모듈을 import 하지
    않는다(순수 도메인, import root 가 봉인돼 있다). 창을 아는 쪽이 준다.
    """
    window = _positive(window_seconds, 1.0)
    return MEASURED_UNTHROTTLED_ROTATIONS_PER_SECOND * window


def control_reduction_factor(*, window_seconds: object) -> float:
    """예산이 무상한 속도를 **몇 배** 줄이는가. 산문이 아니라 함수."""
    budget = refresh_rotation_budget()
    if not budget:
        return float('inf')
    return unthrottled_rotations_per_window(
        window_seconds=window_seconds) / budget


def refresh_rotation_budget(
    *,
    sessions_per_tester: object = CONCURRENT_SESSIONS_PER_TESTER,
    retry_allowance: object = REFRESH_RETRY_ALLOWANCE,
    margin: object = DENIAL_ASYMMETRY_MARGIN,
) -> int:
    """한 **subject** 가 한 창 안에 쓸 수 있는 회전 수.

    ``sessions × allowance × margin`` — 정상 최악의 **모델 위**에 여유를 둔다.

    ⚠️ **TTL 이 이 식에 없는 것이 의도다.** 예산이 답하는 것은 *"버스트가 얼마나 클 수
    있는가"* 이고, TTL 이 답하는 것은 *"그 버스트가 얼마나 자주 올 수 있는가"* 다.
    둘을 곱하면 창 하나에 대한 예산이 사용 빈도에 따라 흔들린다.

    ⚠️ **오늘 이 축의 상한은 무한이므로 어떤 유한한 값도 엄밀히 개선이다.** 그러나
    정상 동선을 자르면 ``D-11`` 보다 비싼 실패(시험 도중 로그아웃)가 되므로, 방향은
    **넉넉한 쪽**이고 그 넉넉함은 :func:`burst_headroom_ratio` 로 **측정 가능**하다.
    """
    return max(1, int(ceil(
        modelled_worst_case(
            sessions_per_tester=sessions_per_tester,
            retry_allowance=retry_allowance,
        ) * _positive(margin, DENIAL_ASYMMETRY_MARGIN)
    )))


def source_rotation_budget(
    *,
    testers_per_source: object,
    sessions_per_tester: object = CONCURRENT_SESSIONS_PER_TESTER,
    retry_allowance: object = REFRESH_RETRY_ALLOWANCE,
) -> int:
    """한 **출처**가 한 창 안에 낼 수 있는 회전 수 — 같은 인구에서 파생.

    ⚠️ **이 값은 아무 데도 적용되지 않는다. 그것이 설계다.** 출처 축을 조이는 것은
    관측이 ``observed-distinct`` 를 답한 배포에서만 정당하고(그 전에는 «한 출처» 가
    «한 사람» 을 뜻하지 않는다), 그 판단은 이 모듈이 아니라 그 웨이브의 몫이다.

    그럼에도 여기 있는 이유는 **소유권**이다: 언젠가 그 상한을 정하는 세션이 인구
    사실을 새로 발명하지 않고 :data:`CONCURRENT_SESSIONS_PER_TESTER` 에서 파생하도록,
    식을 미리 이 모듈에 둔다. ADR-0021 ``R-10`` 이 요구한 *"둘을 함께 집어라"* 의
    실현이 이것이다.
    """
    testers = _positive(testers_per_source, 1.0)
    return max(1, int(ceil(
        testers * refresh_rotation_budget(
            sessions_per_tester=sessions_per_tester,
            retry_allowance=retry_allowance,
        )
    )))


def burst_headroom_ratio(
    *,
    access_ttl_seconds: object,
    refresh_margin_seconds: object,
    window_seconds: object,
    sessions_per_tester: object = CONCURRENT_SESSIONS_PER_TESTER,
    retry_allowance: object = REFRESH_RETRY_ALLOWANCE,
) -> float:
    """예산이 정상 상태 소비의 **몇 배**인가.

    이 함수가 있는 이유는 *"넉넉하다"* 를 **측정 가능한 문장**으로 만들기 위해서다.
    산문으로 «넉넉하게 잡았다» 라고 적으면 다음 세션이 그것을 확인할 방법이 없고,
    조였을 때 무엇을 잃는지도 알 수 없다.
    """
    steady = steady_state_rotations_per_window(
        access_ttl_seconds=access_ttl_seconds,
        refresh_margin_seconds=refresh_margin_seconds,
        window_seconds=window_seconds,
        sessions_per_tester=sessions_per_tester,
    )
    budget = refresh_rotation_budget(
        sessions_per_tester=sessions_per_tester,
        retry_allowance=retry_allowance,
    )
    if steady <= 0:
        return float('inf')
    return budget / steady
