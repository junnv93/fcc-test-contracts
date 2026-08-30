"""peer 축 관측기 — 판정의 *상태* 절반 (2026-08-23).

:mod:`domain.services.peer_axis_observation` 이 **판정**을 소유하고(순수, 숫자 상수 0),
이 모듈은 순수할 수 없는 것 하나만 소유한다: **프로세스가 실제로 무엇을 봤는가.**
:mod:`application.common.rate_limit` 이 :mod:`domain.services.rate_limit_policy` 에 대해
갖는 것과 같은 분업이고, 같은 이유로 ``application/common`` 에 산다 — 세 웹 표면
(Session / Headless / Platform)이 전부 필요로 하고 dependency-free 여야 한다
(``TestApplicationCommonPurity`` 가 봉인한다).

## ⚠️ 이 관측기에는 상한도 축출도 스윕도 없다 — 필요가 없기 때문이다

형제 :class:`application.common.rate_limit.FixedWindowRateLimiter` 는 키마다 카운터를
들어야 해서 ``max_tracked_keys`` 와 LRU 축출이 필요했고, 스프레이 관측기는 *몇 개인지*
를 알아야 해서 세 겹의 상한이 필요했다. **여기서는 그 문제가 애초에 생기지 않는다.**

판정에 필요한 사실은 *"하나라도 봤는가"* 와 *"둘 이상 봤는가"* 두 불리언뿐이므로,
관측기는 **키를 하나만** 붙잡고 그 뒤로는 같은지 비교만 한다. 서로 다른 키가 백만 개
도착해도 보관량은 **문자열 하나 + 스칼라 셋**이다. 즉 이 관측기는 구조적으로
메모리 소진 경로가 될 수 없고, 그 사실이 상수 하나 없이 성립한다.

## ⚠️ 창이 없다 — 그리고 그 대가를 숨기지 않는다

*"둘 이상 봤다"* 는 **구조적 사실**이라 시간이 지난다고 거짓이 되지 않는다. 창을 두면
길이를 정해야 하고(60초는 두 시험원이 겹치기에 짧고 10분은 왜 10분인지 답이 없다),
그 숫자는 위 도메인 모듈이 없애기로 한 바로 그 종류다.

**대가**: 부팅 이후 토폴로지가 바뀌면(상위 프록시 신설 등) 재기동 전까지 옛 판정이
남는다. 그래서 봉투가 ``sample_count`` 와 ``seconds_since_first_sample`` 을 **함께**
나른다 — 신선도가 보이지 않으면 그 한계가 숨겨진다. 재관측은 **프로세스 재기동**이
수행한다(장부 등재 항목).

## ⚠️ 프로세스 로컬이다 (형제 넷과 같은 축)

토큰 폐기 목록 · 스로틀 카운터 · 보관 분할 · 회전 원자성과 **같은 축**이고 같은 해답
(공유 저장소)을 갖는다. 다중 워커 배포에서 워커 A 가 본 출처를 워커 B 는 모르므로,
각 워커가 자기가 본 것만 답한다. **그 방향은 안전한 쪽이다** — 워커가 늘수록 각자의
관측은 *더 적은* 다양성을 보므로 ``observed-distinct`` 를 **과대 주장하지 않는다**.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from fcc_test_contracts.common.metrics_registry import GaugeFamily
from fcc_test_contracts.common.peer_axis_observation import (
    CALLER_COUNTED,
    CALLER_UNATTRIBUTABLE,
    PEER_AXIS_VERDICTS,
    PeerAxisObservation,
    classify_caller,
    reconcile_peer_axis,
)


__all__ = [
    'PEER_AXIS_GAUGE_FAMILIES',
    'PEER_AXIS_AGE_GAUGE',
    'PEER_AXIS_SAMPLES_GAUGE',
    'PEER_AXIS_UNATTRIBUTABLE_GAUGE',
    'PEER_AXIS_SOURCES_GAUGE',
    'PEER_AXIS_VERDICT_GAUGE',
    'PeerAxisObserver',
    'build_peer_axis_recorder',
    'install_peer_axis_observation',
]


class PeerAxisObserver:
    """*"서로 다른 출처를 둘 이상 봤는가"* 하나만 기억하는 관측기.

    thread-safe — 세 표면 전부 스레드 풀 위의 ASGI 서버에서 돌고, 이 저장소의 다른
    전역 캐시와 같은 ``threading.Lock`` 규율을 따른다. 임계 구역은 비교 한 번이라
    요청 처리 비용 옆에서 무시할 만하다.

    ``clock`` 은 기본이 ``time.monotonic`` 이고 주입 가능하다 — 벽시계 점프(NTP step,
    DST)가 신선도 표시를 음수로 만들면 안 되고, 테스트가 ``sleep`` 없이 돌아야 한다.
    """

    def __init__(
        self,
        *,
        clock: Optional[Callable[[], float]] = None,
        client_ranges: tuple = (),
    ) -> None:
        self._clock = clock or time.monotonic
        # ⚠️ **선언된 시험원 대역** — «이 주소가 시험원의 것인가» 는 코드가 알 수 없고
        # 운영자만 답할 수 있다. 비어 있으면 이 관측기는 아무것도 세지 않고 판정은
        # ``undeclared-clients`` 가 된다(그 상수의 docstring 이 이유를 갖는다).
        self._client_ranges = tuple(client_ranges or ())
        self._lock = threading.Lock()
        self._first_key: Optional[str] = None
        self._saw_other = False
        self._samples = 0
        self._unattributable = 0
        self._first_at: Optional[float] = None

    def observe(self, peer_key: object, restored: bool) -> bool:
        """출처 하나를 관측한다. **판정 상태가 바뀌었으면** ``True``.

        ⚠️ **``restored`` 에 기본값이 없는 것이 의도다.** 기본값 ``True`` 를 두면
        호출자가 그 인자를 **빠뜨려도** 코드가 돌고 모든 요청이 «복원됨» 으로 세어진다
        — 즉 이 축의 CRITICAL 이 조용히 되돌아온다. 변이 배터리가 정확히 그 형태로
        살아남았고(«인자가 존재한다» 는 «값이 흐른다» 가 아니다), 필수로 만들자
        그 변이가 ``TypeError`` 로 죽었다. 호출자는 사실을 **말해야** 한다.

        반환값이 있는 이유: 상태는 프로세스 수명 동안 **최대 두 번** 바뀐다(첫 관측 ·
        두 번째 종류의 첫 관측). 호출자가 그때만 게이지를 갱신하면, 요청마다 하던 일이
        평생 두 번으로 줄어든다.

        ⚠️ **총함수다 — 어떤 입력에도 raise 하지 않는다.** 이 호출은 **모든 요청**의
        경로에 있다. 관측 보조 기능이 요청을 죽이면 그 기능은 꺼지고, 꺼진 관측은
        아무것도 관측하지 않는다.
        """
        try:
            key = self._normalize(peer_key)
        except Exception:  # pragma: no cover — _normalize 는 이미 총함수다
            return False
        # ⚠️ **세 갈래 분류는 도메인이 한 함수에서 소유한다** — 그리고 그것이 한
        # 함수인 것이 설계다. 3R 은 이 축을 두 번 고쳤는데 한 수정(«제외한 사실을
        # 세라»)은 여기 **안**에, 다른 하나(«복원된 요청만 세라»)는 미들웨어의
        # **게이트**로 밖에 있었다. 그래서 복원되지 않은 요청은 이 메서드에 도달조차
        # 하지 않았고 아무 흔적도 남기지 않았다 — 붕괴가 다시 «아직 아무것도 안 왔다»
        # 로 읽혔다(적대 평가 4R 실측: 두 시험원이 같은 버킷을 공유해 한쪽이 다른
        # 쪽을 첫 요청에서 429 시키는 것이 그 자리에서 증명됐는데도 `unobserved`).
        #
        # 주소는 여전히 남기지 않는다: 필요한 것은 *있었는가/얼마나* 이지
        # *무엇이었나* 가 아니다.
        verdict = classify_caller(key, self._client_ranges, restored=restored)
        if verdict != CALLER_COUNTED:
            if verdict == CALLER_UNATTRIBUTABLE:
                with self._lock:
                    self._unattributable += 1
            return False
        with self._lock:
            self._samples += 1
            if self._first_key is None:
                self._first_key = key
                self._first_at = self._safe_now()
                return True
            if not self._saw_other and key != self._first_key:
                self._saw_other = True
                return True
        return False

    def snapshot(self) -> PeerAxisObservation:
        """지금까지 본 것 — **주소는 나가지 않는다**(도메인 봉투가 그 이유를 적는다)."""
        with self._lock:
            saw_any = self._first_key is not None
            saw_other = self._saw_other
            samples = self._samples
            unattributable = self._unattributable
            first_at = self._first_at
        elapsed = 0.0
        if first_at is not None:
            now = self._safe_now()
            # 단조 시계라 음수가 나올 수 없지만, 주입된 시계는 무엇이든 될 수 있다.
            # 음수 경과는 신선도 표시를 거짓말로 만드므로 0 으로 접는다.
            elapsed = max(0.0, now - first_at)
        return PeerAxisObservation(
            clients_declared=bool(self._client_ranges),
            saw_any=saw_any,
            saw_more_than_one=saw_other,
            sample_count=samples,
            seconds_since_first_sample=elapsed,
            saw_unattributable=unattributable > 0,
            unattributable_samples=unattributable,
        )

    @property
    def retained_keys(self) -> int:
        """보관 중인 키 개수 — 봉인이 *상수임*을 단언하는 자리.

        구조적으로 0 또는 1 이다. 이 속성이 있는 이유는 진단이 아니라 **봉인**이다:
        서로 다른 키를 아무리 먹여도 이 값이 자라지 않는다는 사실을 테스트가 물을 수
        있어야 한다.
        """
        with self._lock:
            return 0 if self._first_key is None else 1

    def _safe_now(self) -> float:
        try:
            return float(self._clock())
        except Exception:
            return 0.0

    @staticmethod
    def _normalize(peer_key: object) -> str:
        if isinstance(peer_key, str):
            return peer_key
        if peer_key is None:
            return ''
        try:
            return str(peer_key)
        except Exception:
            return ''


#: gauge base 이름(namespace 미포함 — registry 가 ``fcc_platform_`` 등을 prepend).
PEER_AXIS_SOURCES_GAUGE = 'peer_axis_sources_observed'
PEER_AXIS_VERDICT_GAUGE = 'peer_axis_verdict'
#: ⚠️ **신선도 축** — 창이 없다는 설계의 대가를 **보이게** 하는 두 게이지.
#:
#: 모듈 docstring 이 *"봉투가 sample_count 와 seconds_since_first_sample 을 함께
#: 나른다 — 신선도가 보이지 않으면 그 한계가 숨겨진다"* 라고 적고 있었지만, 착지
#: 직전까지 그 봉투를 **읽는 코드가 0** 이었다(적대 평가 2R 실측). 즉 «보인다» 는
#: 문장이 어디에도 도달하지 않는 주장이었다. 그리고 그 둘은 판정을 «3 요청으로 얻은
#: distinct» 와 «30,000 요청으로 얻은 distinct» 로 가르는 유일한 손잡이다.
PEER_AXIS_SAMPLES_GAUGE = 'peer_axis_samples_total'
PEER_AXIS_AGE_GAUGE = 'peer_axis_observation_age_seconds'
#: 선언된 대역 **밖**에서 온 caller 요청 수. 이것이 ``unobserved``(정말 아무것도
#: 안 왔다)와 ``sources-unattributable``(오는데 귀속이 안 된다)를 가른다.
PEER_AXIS_UNATTRIBUTABLE_GAUGE = 'peer_axis_unattributable_samples_total'

#: ⚠️ ``sources_observed`` 는 **개수가 아니라 3-값 요약**이다: 0 / 1 / "둘 이상".
#: 관측기는 개수를 세지 않으므로(위 docstring — 그것이 상한을 없앤 이유다) 이 게이지도
#: 셀 수 없다. Prometheus 는 숫자를 요구하므로 *둘 이상*을 2 로 **렌더**할 뿐이고,
#: 그 2 는 판정에 쓰이지 않는다(판정은 도메인의 두 불리언이 한다).
_SOURCES_NONE = 0
_SOURCES_ONE = 1
_SOURCES_TWO_OR_MORE = 2

#: 선언 gauge family SSOT — composition 과 테스트가 공유한다.
#:
#: ⚠️ 판정 라벨 값은 도메인 토큰 집합에서 **파생**한다 — 손으로 열거하면 토큰이 늘어난
#: 날 게이지가 조용히 그 판정을 표현하지 못한다(registry 가 미선언 라벨을 **거부**하므로
#: 그날의 증상은 «관측 실패» 가 아니라 «예외» 다).
PEER_AXIS_GAUGE_FAMILIES: tuple[GaugeFamily, ...] = (
    GaugeFamily(
        name=PEER_AXIS_SOURCES_GAUGE,
        help='Distinct request sources this process has seen, summarised as '
             '0 / 1 / 2 (2 means "two or more"). 1 does NOT mean the path '
             'collapsed — it is also one tester working alone.',
    ),
    GaugeFamily(
        name=PEER_AXIS_SAMPLES_GAUGE,
        help='Requests from a declared client range this process has counted '
             'toward the peer-axis verdict. Tells a distinct-sources verdict '
             'built from 3 requests apart from one built from 30,000.',
    ),
    GaugeFamily(
        name=PEER_AXIS_AGE_GAUGE,
        help='Seconds since the first counted request, computed AT SCRAPE '
             'TIME. The verdict has NO window, so a topology change after boot '
             'is not re-observed until restart — this is how old the answer '
             'is, and it keeps advancing while the deployment is idle.',
    ),
    GaugeFamily(
        name=PEER_AXIS_UNATTRIBUTABLE_GAUGE,
        help='Caller requests whose source was NOT in a declared client range. '
             'Non-zero with sources_observed at 0 means traffic is arriving '
             'but none of it can be attributed to a tester — usually a hop '
             'upstream of the trusted proxy, or a wrong declaration.',
    ),
    GaugeFamily(
        name=PEER_AXIS_VERDICT_GAUGE,
        help='1 on the peer-axis verdict that currently holds, 0 on the '
             'others. Answers whether the peer budget is really charged per '
             'caller on THIS deployment.',
        label_key='verdict',
        label_values=PEER_AXIS_VERDICTS,
    ),
)


def build_peer_axis_recorder(
    observer: PeerAxisObserver,
    registry,
    configured_mode: str,
) -> Callable[[object], None]:
    """미들웨어가 요청마다 부르는 ``recorder(peer_key)`` 를 만든다.

    미들웨어가 메트릭을 **모르는 채로** 관측할 수 있게 하는 seam 이다 — 그 모듈은
    자기 docstring 에 *"This module imports no web framework"* 라고 적고 있고, 같은
    이유로 registry 도 몰라야 한다.

    게이지는 **판정이 바뀔 때만** 갱신한다(프로세스 수명 동안 최대 두 번). 부팅 직후
    한 번은 강제로 써서 ``unobserved`` 가 *"게이지가 아직 없다"* 와 구분되게 한다 —
    없는 시계열과 0 인 시계열은 대시보드에서 다른 뜻이다.

    ⚠️ **부팅 시 1회 발행은 감싸지 않고, 요청 중 재발행만 감싼다.** 두 실패가 다른
    사건이기 때문이다 — 부팅 실패는 **오배선**(gauge family 미선언)이고 그것을 삼키면
    게이지가 영원히 없는 채로 아무도 모른다(*"게이지가 0" 과 "게이지가 없음" 은 다른
    뜻인데, 삼키면 후자가 조용해진다*). 요청 중 실패는 **관측성 보조 경로**이고 그것을
    삼키지 않으면 관측 기능이 요청을 500 으로 만든다. 그래서 오배선은 앱 생성 시점에
    **시끄럽게** 터지고, 그 뒤로는 절대 요청을 죽이지 않는다.
    """
    # ⚠️ **자기가 발행하는 것을 자기가 선언한다.** composition 이 대신 선언하게 하면
    # 세 표면(+ registry 를 직접 만드는 모든 테스트)이 이 목록을 기억해야 하고, 한 곳을
    # 빠뜨린 증상은 «관측 실패» 가 아니라 런타임 ``set_gauge`` 예외다. 멱등이라 이미
    # 선언된 registry 에도 안전하고, **선언 자체가 실패하면 시끄럽다** — 그것은
    # 오배선(이름 충돌)이고 앱 생성 시점이 그것을 고칠 수 있는 유일한 순간이다.
    registry.declare_gauge_families(PEER_AXIS_GAUGE_FAMILIES)

    def _publish() -> None:
        observation = observer.snapshot()
        verdict = reconcile_peer_axis(configured_mode, observation)
        if observation.saw_more_than_one:
            sources = _SOURCES_TWO_OR_MORE
        elif observation.saw_any:
            sources = _SOURCES_ONE
        else:
            sources = _SOURCES_NONE
        registry.set_gauge(PEER_AXIS_SOURCES_GAUGE, sources)
        registry.set_gauge(PEER_AXIS_SAMPLES_GAUGE, observation.sample_count)
        registry.set_gauge(
            PEER_AXIS_UNATTRIBUTABLE_GAUGE, observation.unattributable_samples,
        )
        registry.set_gauge(
            PEER_AXIS_AGE_GAUGE, observation.seconds_since_first_sample,
        )
        for token in PEER_AXIS_VERDICTS:
            registry.set_gauge(
                PEER_AXIS_VERDICT_GAUGE,
                1 if token == verdict else 0,
                label_value=token,
            )

    def _safe_publish() -> None:
        try:
            _publish()
        except Exception:  # 관측성 보조 경로가 요청을 죽이지 않는다.
            pass

    # 부팅 시점 1회 — 아직 요청이 없어도 시계열이 존재하게 한다. **감싸지 않는다**
    # (위 docstring): 미선언 family 는 오배선이고, 앱 생성 시점이 그것을 고칠 수 있는
    # 유일한 순간이다.
    _publish()

    # ⚠️ **신선도는 «질문받은 순간» 에만 정의된다** (적대 평가 3R 실측). 발행을
    # 요청 경로에만 두면 나이는 *마지막 사건*에서 굳고, 답이 낡기 시작하는 바로 그
    # 순간에 숫자가 멈춘다 — 실측: 벽시계 150초 동안 bit-identical, 그러다 이 축이
    # **세지 않는다고 선언한** 요청 하나가 그 값을 194초 밀었다(즉 운영자가 읽는
    # 값이 축이 무시한다고 말한 트래픽에 좌우됐다). 스크레이프 훅이 계산을 질문의
    # 순간으로 옮겨 두 결함을 함께 없앤다.
    registry.add_scrape_hook(_safe_publish)

    def recorder(peer_key: object, restored: bool) -> None:
        # ⚠️ **여기서 발행하지 않는다.** 게이지 값은 :meth:`render` 만 읽고 render 는
        # 위 훅으로 매번 새로 계산하므로, 요청 경로의 발행은 아무도 관측할 수 없는
        # 쓰기다 — 변이 배터리가 그것을 증명했다(그 줄을 지워도 봉인 109개 중 어느
        # 것도 달라지지 않았다). 관측할 수 없는 코드는 유지되지 않으므로 지운다.
        # 요청 경로는 이제 «본 것을 기록» 만 한다.
        observer.observe(peer_key, restored)

    return recorder


def install_peer_axis_observation(registry, *, environ=None, active=True):
    """세 표면이 부르는 **한 줄** — recorder 또는 ``None``.

    ``registry`` 가 ``None`` 인 배포(폐쇄망 / 단위 테스트)는 발행할 곳이 없으므로
    관측도 하지 않는다 — 관측만 하고 아무도 못 읽는 상태는 직전 웨이브가 값을 치르고
    배운 실패 모드다(*주입 로거로 "고지한다" 를 단언했는데 실 배포의 ``docker logs``
    는 0줄이었다*).

    세 표면이 각자 조립하지 않고 이 함수를 부르는 이유는 드리프트다 — 관측 지점이
    표면마다 다르면 *"어느 표면이 이 질문에 답하는가"* 가 배포마다 달라진다.
    """
    if registry is None:
        return None
    # ⚠️ **관측자가 없을 게이지는 만들지 않는다** (적대 평가 3R 실측). 스로틀
    # kill-switch 를 켜면 미들웨어가 설치되지 않아 recorder 를 **아무도 부르지
    # 않는데**, 옛 코드는 그래도 family 를 선언하고 부팅 발행으로 ``unobserved`` 를
    # 찍었다 — 실측: 시험원 세 명의 서로 다른 출처가 접근 로그에 그대로 남아 있는
    # 배포가 «재기동 직후의 정상» 이라고 영원히 답했다. 없는 시계열과 0 인 시계열은
    # 대시보드에서 다른 뜻이고, 관측을 끈 배포는 **전자**여야 한다.
    if not active:
        return None
    # 지역 import — ``proxy_trust`` 는 env 를 읽는 경계이고, 이 모듈은 그 의존을
    # 관측이 실제로 배선될 때만 진다(순수 관측기는 env 를 모른다).
    #
    # ⚠️ 선언된 클라이언트 대역은 **새로 만들지 않는다** — proxy-trust 축이 이미 같은
    # 사실을 같은 변수에서 읽고 있고(신뢰 집합이 실 클라이언트를 삼키지 않게), 두 번째
    # 리더를 만들면 «시험원이 어디 사는가» 에 답이 둘 생긴다.
    from fcc_test_contracts.common.proxy_trust import (
        resolve_client_ranges,
        resolve_peer_axis_mode,
    )
    return build_peer_axis_recorder(
        PeerAxisObserver(client_ranges=resolve_client_ranges(environ)),
        registry,
        resolve_peer_axis_mode(environ),
    )
