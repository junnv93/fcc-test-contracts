"""peer 축 관측 판정 — 순수 도메인 (2026-08-23).

이 모듈이 답하는 질문은 하나다: **이 배포에서 peer 예산이 실제로 사람마다인가.**

## 왜 기존 답으로는 부족한가

:func:`domain.services.proxy_trust_policy.peer_axis_mode` 는 그 질문에 답하는 것처럼
보이지만 실제로는 **환경변수를 다시 말할 뿐**이다 — 그 함수가 보는 것은
``FORWARDED_ALLOW_IPS`` 이고, 그것은 *"서버가 체인에서 실 주소를 복원할 준비가 됐는가"*
에 답한다. **준비가 됐다는 것과 실제로 서로 다른 주소가 도착한다는 것은 다른 사실이다.**

그 간극은 가설이 아니라 실측이다. 중앙 허브는 WSL 위에서 돌고, 기본 WSL2 NAT 모드에서
LAN 클라이언트는 Windows 쪽 릴레이를 거쳐 컨테이너에 닿는다 — 그 경로에서 SNAT 이
**Docker 바깥**에서 일어나므로 nginx 는 서로 다른 PC 의 요청을 **한 주소**로 본다(형제
시스템이 2026-08-11 에 같은 중앙 PC 에서 겪었고, 그 사건의 판별식이 ``wsl-relay-snat``
이다). 그 배포에서 부팅 로그는 여전히 ``per-source`` 라고 적고, 예산은 전원이 한 버킷을
공유한다. **아무 예외도 나지 않는다.**

그러므로 축이 **둘**이고 권위가 다르다 — 이 저장소가 챔버 모드 축
(:mod:`domain.services.chamber_mode_policy`)에서 이미 세운 구조 그대로다:

=========  ==========================================  ===================
축         묻는 것                                     권위
=========  ==========================================  ===================
**기대**   신뢰 hop 이 지목됐는가                      배포 설정
**관측**   실제로 서로 다른 출처가 도착했는가          프로세스
**판정**   둘을 대조하면 무엇을 해야 하는가            이 모듈 (순수)
=========  ==========================================  ===================

⚠️ **한 칸으로 접지 마라.** 둘의 *불일치가 곧 신호*다 — 배선은 ``per-source`` 라고
적는데 관측은 출처가 하나면, 그것이 정확히 위 릴레이 형상이다.

## ⚠️ ``observed-single`` 은 붕괴를 주장하지 않는다 — 그것이 이 모듈의 핵심이다

출처가 하나라는 관측은 두 사실을 **원리적으로** 구분하지 못한다:

* 릴레이가 여러 PC 를 한 주소로 접었다, 또는
* 그냥 **쓴 사람이 한 명이다**.

그 둘을 가르는 임계값(*"N 요청 이상인데 출처가 하나면 붕괴"*)은 **존재하지 않는다** —
한 사람이 하루 종일 쓰면 어떤 N 도 넘는다. 그래서 이 토큰의 이름은 *붕괴*가 아니라
**아직 모른다**이고, 딸린 조치는 *"두 번째 PC 로 접속한 뒤 다시 봐라"* 이다.

형제 축이 같은 규율을 갖는다 — ``chamber_mode_policy`` 의 ``NOT_OBSERVED`` 는 heartbeat
부재의 **원인을 주장하지 않는다**. 이름이 *배포 미완*이면 운영자가 매일 아침 없는 문제를
조사한다. 여기서도 같다: 1인 근무 아침마다 릴레이 사고를 조사하게 만들면, 이 게이지는
꺼진다.

반대로 **서로 다른 두 출처가 실제로 도착했다면 그 경로는 출처를 보존한다** — 한 번의
관측이면 충분하고, 그래서 ``observed-distinct`` 는 추정이 아니라 **증명**이다.

## ⚠️ 이 모듈의 **판정에는 임계값이 없다** — 그리고 그것이 의도다

형제 :mod:`domain.services.proxy_trust_policy` 가 자기 docstring 에 적는 규율을 그대로
물려받는다: *"임계값이 생기는 순간 «얼마나 넓으면 너무 넓은가» 라는 답할 수 없는 질문이
정책이 된다."* 관측 축에서 그 함정은 위 문단이 이름 붙인 바로 그것이다.

**질문의 모양이 상수를 없앤다.** 판정에 필요한 사실은 *"하나라도 봤는가"* 와
*"둘 이상 봤는가"* 두 **불리언**뿐이므로, 개수를 세는 임계값도 개수를 기억하는 상한도
필요 없다. :class:`PeerAxisObservation` 이 숫자가 아니라 그 두 술어를 나르는 이유다.

⚠️ **정확히 말하면 «모듈에 숫자가 없다» 가 아니라 «판정 함수 안에 숫자가 없다» 이다.**
초판 docstring 이 전자로 적었고 그것은 과장이었다(값 객체의 기본값 ``0``/``0.0`` 이
있다). 봉인도 그 과장을 따라 **모듈 레벨**만 훑었고, 그래서 판정 함수 *안*에 넣은 진짜
임계값(신선도 만료)이 살아남았다(적대 평가 실측 2026-08-23). 지금 봉인은 함수 본문을
본다 — 규율이 사는 곳이 거기이기 때문이다.

## 총함수다 — 어떤 입력에도 raise 하지 않는다

이 판정은 **요청 경로**와 **메트릭 스크레이프 경로**에서 돌고, 둘 다 판정기의 예외를
감쌀 이유가 없는 자리다. 관측 보조 기능이 요청을 죽이거나 ``/metrics`` 를 500 으로
만들면, 그 기능은 꺼진다. 그러므로 읽을 수 없는 입력은 **가장 보수적인 답**으로
분류하지 예외로 만들지 않는다 — 보수적인 답이란 *per-source 라고 주장하지 않는 것*이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network
from ipaddress import ip_address as _ip_address
from ipaddress import ip_network as _ip_network

from fcc_test_contracts.common.proxy_trust_policy import (
    PEER_AXIS_DEPLOYMENT_WIDE,
    PEER_AXIS_PER_SOURCE,
    TRUSTED_PROXY_ENV,
)
from fcc_test_contracts.common.rate_limit_policy import IP_KEY_PREFIX


__all__ = [
    'PEER_AXIS_OBSERVED_DISTINCT',
    'PEER_AXIS_OBSERVED_SINGLE',
    'PEER_AXIS_UNDECLARED_CLIENTS',
    'PEER_AXIS_UNOBSERVED',
    'PEER_AXIS_SOURCES_UNATTRIBUTABLE',
    'PEER_AXIS_VERDICTS',
    'RESTORED_PEER_PORT',
    'arrived_through_trusted_hop',
    'PeerAxisObservation',
    'CALLER_COUNTED',
    'CALLER_IGNORED',
    'CALLER_UNATTRIBUTABLE',
    'classify_caller',
    'counts_as_caller',
    'is_unattributable_caller',
    'describe_peer_axis_verdict',
    'reconcile_peer_axis',
]


#: 서로 다른 출처를 **둘 이상** 실제로 봤다. 경로가 출처를 보존한다는 **증명**이고,
#: 운영자가 할 일은 없다.
PEER_AXIS_OBSERVED_DISTINCT = 'observed-distinct'

#: 출처를 **하나만** 봤다. ⚠️ *붕괴했다* 가 아니라 **아직 모른다** 이다 — 위 docstring 참조.
PEER_AXIS_OBSERVED_SINGLE = 'observed-single'

#: 아직 아무 요청도 오지 않았다. 판정할 것이 없다(부팅 직후의 정상 상태).
PEER_AXIS_UNOBSERVED = 'unobserved'

#: 신뢰 hop 은 있는데 **시험원이 어디 사는지 아무도 선언하지 않았다**.
#:
#: ⚠️ **이 토큰이 «붕괴를 증명으로 표시하는» 마지막 채널을 닫는다** (적대 평가 2R 실측).
#: 두 API 포트는 LAN 에 게시돼 있으므로 프록시를 **거치지 않고** 직접 닿는 요청이
#: 존재한다 — 이웃 컨테이너, 브리지 게이트웨이, LAN 스캐너, 포트를 잘못 친 운영자.
#: 그런 요청도 «서로 다른 출처» 이므로, 전원이 릴레이로 접힌 배포에서 **요청 하나**가
#: 판정을 ``observed-distinct`` 로 올렸다(404 여도 상관없다 — 관측은 인가 앞이다).
#:
#: 그 요청들이 *시험원의 것이 아님*을 코드가 알 방법은 하나뿐이다 — **운영자가
#: 시험원이 사는 대역을 선언하는 것**. 그 값은 이미 존재하고(`FCC_CENTRAL_CLIENT_RANGES`)
#: proxy-trust 축이 이미 같은 이유로 그것을 요구한다(신뢰 집합이 실 클라이언트를
#: 삼키지 않게). 선언이 없으면 «이 주소는 시험원이다» 는 **아무도 한 적 없는 주장**이고,
#: 그 위에서 «증명» 을 말할 수 없다.
#:
#: ⚠️ 헤더를 새로 읽어 푸는 방법은 **금지돼 있다** — 신뢰 해석의 소유자는 하나여야
#: 하고(`TestTrustResolutionHasExactlyOneOwner`), FCC 코드는 forwarded 계열 헤더를
#: 이름으로도 들지 않는다. 그러므로 답은 **이미 소유된 사실**에서 나와야 한다.
PEER_AXIS_UNDECLARED_CLIENTS = 'undeclared-clients'

#: 요청은 **오고 있는데 그중 어느 것도 선언된 시험원에게 귀속되지 않는다**.
#:
#: ⚠️ **이 토큰이 없으면 이 축은 자기가 검출하려던 붕괴에 «아직 아무것도 없다» 고
#: 답한다** (적대 평가 3R 실측, 실 스택). 시나리오는 런북이 이 축의 존재 이유로
#: 직접 지목한 바로 그것이다 — *상위 프록시 신설*. 신뢰 hop 앞에 프록시가 하나 더
#: 생기면 모든 시험원이 **그 프록시의 주소**로 도착하고, 그 주소는 인프라이지
#: 시험원 PC 가 아니므로 선언된 대역 **밖**이다. 그러면:
#:
#: * ``counts_as_caller`` 가 전부 False → ``saw_any`` False → 옛 판정은 ``unobserved``
#: * 런북은 ``unobserved`` 에 «재기동 직후의 정상. 시험원이 일하기 시작한 뒤 다시 봐라»
#:   라고 적는다 → 운영자는 **영원히 기다린다**
#:
#: 즉 경로가 완전히 접힐수록 이 축은 더 확실하게 «아직 모른다» 고 답했다. 실측:
#: 시험원 세 대를 붙여도 판정은 ``unobserved`` 였고 부팅 로그는 여전히 ``per-source``
#: 였다. 제외는 거짓 *증명*을 막으려고 넣었는데 거짓 *침묵*을 만들고 있었다.
#:
#: 그래서 «선언 밖 출처를 봤다» 는 사실을 **버리지 않고 세되 주소는 남기지 않는다**.
#: 그 하나로 ``unobserved``(정말 아무것도 안 왔다)와 이 상태(오는데 귀속이 안 된다)가
#: 갈린다 — 형제 축의 규율 그대로다: **불일치가 곧 신호다.**
#:
#: ⚠️ 이것은 «붕괴했다» 가 **아니다**. 선언이 틀렸을 수도 있고, 게시 포트로 직접
#: 닿는 트래픽일 수도 있다. 조치 문장이 그 셋을 모두 이름으로 댄다.
PEER_AXIS_SOURCES_UNATTRIBUTABLE = 'sources-unattributable'

#: 판정 토큰 전량 — 소비자(게이지 라벨 · 런북 · 테스트)가 같은 집합을 봐야 한다.
#: ``PEER_AXIS_DEPLOYMENT_WIDE`` 는 **기대 축의 토큰을 그대로 재사용**한다: 배선이 없으면
#: 관측이 무엇이든 예산은 배포 단위이고, 그 사실에 두 번째 이름을 주면 런북이 두 토큰을
#: 같은 뜻으로 설명하게 된다.
PEER_AXIS_VERDICTS: tuple[str, ...] = (
    PEER_AXIS_DEPLOYMENT_WIDE,
    PEER_AXIS_UNDECLARED_CLIENTS,
    PEER_AXIS_UNOBSERVED,
    PEER_AXIS_SOURCES_UNATTRIBUTABLE,
    PEER_AXIS_OBSERVED_SINGLE,
    PEER_AXIS_OBSERVED_DISTINCT,
)


#: ASGI 서버가 신뢰 hop 의 forwarded 체인으로 실 주소를 **복원했을 때** 남기는 포트.
#: uvicorn 의 ``ProxyHeadersMiddleware`` 는 ``scope["client"]`` 를
#: ``(restored_host, 0)`` 으로 다시 쓴다 — 즉 이 값은 «주소를 우리가 복원했다» 는
#: 사실의 흔적이고, 직접 연결은 실 ephemeral 포트를 그대로 갖는다(0 은 유효한 출발
#: 포트가 아니므로 두 상태가 섞이지 않는다).
#:
#: ⚠️ **모듈 레벨 상수인 것이 의도다.** 이 모듈의 «판정 함수 본문에 숫자 없음» 봉인은
#: 임계값을 막으려는 것이고, 이것은 임계값이 아니라 **프로토콜 사실의 이름**이다.
RESTORED_PEER_PORT = 0


def arrived_through_trusted_hop(peer_port: object) -> bool:
    """이 요청의 주소가 **신뢰 hop 을 통해 복원된 것인가**. 총함수.

    ⚠️ **선언된 대역 요구만으로는 «증명» 채널이 닫히지 않는다** (적대 평가 3R 실측).
    2R 은 게시 포트로 직접 오는 트래픽이 ``observed-distinct`` 를 제조하는 것을 막으려
    *선언된 시험원 대역* 을 요구하게 했다. 그런데 **직접 닿는 호스트들이 사는 곳이
    바로 그 대역**이다 — 포트를 잘못 친 시험원 브라우저, 챔버 노드 PC, LAN 스캐너,
    모니터링 에이전트. 실측: 리버스 프록시가 **한 번도 뜬 적 없는** 스택에서
    선언 대역의 두 호스트가 보낸 **인증도 안 된 403 두 개**로 판정이
    ``observed-distinct``(= *"경로가 출처를 보존한다. 할 일 없음"*)가 됐다.

    답은 이미 그 자리에 있다: 이 판정이 말하려는 것은 *프록시 경로가 출처를 보존하는가*
    이므로, **프록시 경로를 지난 요청만** 세면 된다. 그리고 «지났다» 는 사실은 복원의
    흔적으로 관측 가능하다.

    ⚠️ **헤더를 새로 읽지 않는다.** 신뢰 해석의 소유자는 하나여야 하고
    (``TestTrustResolutionHasExactlyOneOwner``), 이 술어는 헤더가 아니라 *서버가 이미
    내린 결정의 결과*를 본다 — 두 번째 신뢰 소유자를 만들지 않는다.

    ⚠️ 방향은 여기서도 보수적이다. 포트를 읽을 수 없으면 «복원되지 않았다» 로 읽고,
    그러면 그 요청은 다양성 주장에 기여하지 못한다(최악은 *"귀속 불가"* 라는 시끄러운
    상태이지 *"증명됨"* 이라는 조용한 거짓이 아니다).
    """
    if peer_port is None or isinstance(peer_port, bool):
        return False
    try:
        return int(peer_port) == RESTORED_PEER_PORT
    except Exception:
        return False


def counts_as_caller(peer_key: object, client_ranges: object = ()) -> bool:
    """이 출처가 **시험원일 수 있는가**. 총함수.

    ⚠️ **이 술어가 없으면 이 축 전체가 무의미하다** (적대 평가 2R 실측, 2026-08-23).
    배포는 자기 자신에게 요청을 보낸다 — compose 의 healthcheck 가 컨테이너 **안에서**
    ``127.0.0.1`` 로 15초마다 probe 를 친다. 그 요청은 nginx 를 지나지 않으므로
    릴레이가 시험원 30명을 한 주소로 접은 배포에서도 **두 번째 출처**가 되고, 부팅
    15초 뒤부터 판정은 영원히 ``observed-distinct`` 다. 즉 이 축이 검출하려던 바로
    그 붕괴가 *"경로가 출처를 보존한다는 증명"* 으로 표시된다.

    측정된 사실: 50 요청이 전부 한 주소로 접힌 뒤 healthcheck **한 번**으로
    ``sources=1 / observed-single`` → ``sources=2 / observed-distinct``.

    ⚠️ **이 술어의 방향은 «줄이는 쪽» 뿐이다.** 출처를 세지 *않는* 것은 다양성 주장을
    약화시킬 뿐 강화하지 않는다. 그러므로 잘못 제외해도 답은 *"아직 모른다"* 로
    떨어지고, 잘못 포함하면 *"증명됐다"* 로 올라간다. 두 오류의 값이 다르므로
    보수적인 쪽으로 판정한다 — **읽을 수 없는 주소도 세지 않는다.**

    루프백을 빼는 이유는 «시험원은 서버 안에 없다» 이고, 그것은 토폴로지가 아니라
    **정의**다. 챔버 노드처럼 리버스 프록시 없이 직접 서빙하는 호스트에서도 같다 —
    같은 기계에서 온 요청은 *네트워크 경로가 출처를 보존하는가* 에 답하지 않는다.
    """
    # ⚠️ ``removeprefix`` — ``split(prefix, 1)[-1]`` 은 같은 일을 하면서 **숫자
    # 리터럴 둘**을 들여오고, 이 모듈의 «판정 본문에 숫자 없음» 봉인이 그것을 거부한다.
    # 그 봉인은 오탐이 아니다: maxsplit 과 임계값을 구분하려면 예외 목록이 필요하고,
    # 예외 목록은 다음 숫자가 들어오는 문이 된다.
    host = _text(peer_key).removeprefix(IP_KEY_PREFIX).strip()
    if not host:
        return False
    try:
        address = _ip_address(host)
    except ValueError:
        # ``unknown`` (ASGI 가 출처를 못 알려준 전송) 을 포함해 주소로 읽히지 않는
        # 값은 전부 여기로 온다. 판독 불가는 **세지 않는다**(위 방향 논거).
        return False
    # ⚠️ **IPv4-mapped 를 먼저 푼다.** ``ipaddress`` 는 ``::ffff:127.0.0.1`` 을
    # 접지 않으므로 ``IPv6Address.is_loopback``(``self._ip == 1``)이 **False** 다 —
    # 즉 위 판정만으로는 매핑된 루프백이 «시험원» 으로 세어진다(적대 평가 2R 실측).
    # 오늘 배포는 ``--host 0.0.0.0`` 이라 도달하지 않지만, ``--host ::`` 한 글자가
    # 그 잠복을 깨우고 그때 되살아나는 것은 1R 이 보고한 «붕괴가 증명으로» 그대로다.
    mapped = getattr(address, 'ipv4_mapped', None)
    if mapped is not None:
        address = mapped
    if address.is_loopback or address.is_unspecified:
        return False
    # ⚠️ **선언된 시험원 대역 안에 있어야 «시험원일 수 있다».** 그러지 않으면 프록시를
    # 거치지 않고 게시 포트에 직접 닿는 아무 호스트나 «출처» 가 되고, 그 하나가
    # 붕괴한 배포를 «증명» 으로 올린다(적대 평가 2R 실측: 이웃 컨테이너의 404 요청
    # 하나로 ``observed-single`` → ``observed-distinct``).
    #
    # ⚠️ **선언이 비어 있으면 아무것도 세지 않는다** — «이 주소는 시험원이다» 가
    # 아무도 한 적 없는 주장이기 때문이다. 그 상태는 ``unobserved`` 로 접히지 않고
    # :data:`PEER_AXIS_UNDECLARED_CLIENTS` 라는 자기 이름을 갖는다(운영자가 할 일이
    # 다르다 — «기다려라» 가 아니라 «선언해라»).
    declared = _networks(client_ranges)
    if not declared:
        return False
    return any(address in network for network in declared)


#: 관측 분류 — 이 요청이 판정에 무엇으로 들어가는가. **세 값이고 셋 다 필요하다.**
CALLER_COUNTED = 'counted'
CALLER_UNATTRIBUTABLE = 'unattributable'
CALLER_IGNORED = 'ignored'


def classify_caller(
    peer_key: object,
    client_ranges: object = (),
    *,
    restored: bool = True,
) -> str:
    """이 caller 요청을 **세 갈래 중 하나**로 분류한다. 총함수.

    ⚠️ **이 함수는 두 수정이 서로를 무효화한 자리다** (적대 평가 4R 실측).

    3R 은 두 가지를 고쳤다: (a) 선언 밖 출처를 *버리지 말고 세라*(그래야 붕괴가
    침묵으로 읽히지 않는다), (b) *신뢰 hop 을 지나 복원된 요청만 세라*(그래야 프록시를
    우회한 트래픽이 «증명» 을 만들지 못한다). 그런데 (a) 는 관측기 **안**에 있었고
    (b) 는 관측기 **밖**의 게이트였다. 그래서 복원되지 않은 요청은 관측기에 **도달조차
    하지 않았고**, 아무 흔적도 남기지 않았다 — 다시 ``unobserved``, 다시 런북이
    «재기동 직후의 정상» 이라고 말하는 그 상태다.

    실측된 재현: 신뢰 hop 설정이 실제 프록시와 어긋난 배포에서 시험원 A 의 50 요청이
    시험원 B 를 **B 의 첫 요청에서 429** 시켰고(같은 버킷을 공유했다 = 붕괴가 그 자리에서
    증명됐다) 게이지는 `unobserved / samples 0 / unattributable 0` 이었다.

    그러므로 판정은 **한 함수 안에서** 세 갈래여야 한다:

    * :data:`CALLER_IGNORED` — 시험원일 수 **없다**(루프백·미지정·판독 불가). 배포가
      자기 자신에게 보낸 요청이고, 이것을 경보로 세면 정상 배포가 영원히 경보다.
    * :data:`CALLER_UNATTRIBUTABLE` — 실 트래픽인데 **프록시 경로의 시험원으로 귀속할 수
      없다**. 복원 흔적이 없거나, 선언된 대역 밖이다. 이것이 침묵과 다른 답이다.
    * :data:`CALLER_COUNTED` — 복원됐고 선언된 대역 안이다. 다양성 주장에 기여한다.

    ⚠️ 선언이 **비어 있으면** 귀속 불가가 아니라 :data:`CALLER_IGNORED` 다 — 그 상태는
    이미 자기 토큰(:data:`PEER_AXIS_UNDECLARED_CLIENTS`)을 갖고, 두 토큰이 동시에
    성립하면 운영자는 서로 다른 조치 두 개를 받는다.
    """
    if not _is_routable_peer(peer_key):
        return CALLER_IGNORED
    if not _networks(client_ranges):
        return CALLER_IGNORED
    if not _flag(restored):
        # ⚠️ 복원 흔적이 없다 = *"이 요청이 프록시 경로를 지났다고 말할 수 없다"* 이지
        # *"아무 일도 없었다"* 가 아니다. 그 둘을 같게 만든 것이 4R 의 CRITICAL 이다.
        return CALLER_UNATTRIBUTABLE
    if counts_as_caller(peer_key, client_ranges):
        return CALLER_COUNTED
    return CALLER_UNATTRIBUTABLE


def _is_routable_peer(peer_key: object) -> bool:
    """주소로 읽히고 **루프백·미지정이 아닌가**. 총함수."""
    host = _text(peer_key).removeprefix(IP_KEY_PREFIX).strip()
    if not host:
        return False
    try:
        address = _ip_address(host)
    except Exception:
        return False
    mapped = getattr(address, 'ipv4_mapped', None)
    if mapped is not None:
        address = mapped
    return not (address.is_loopback or address.is_unspecified)


def is_unattributable_caller(peer_key: object, client_ranges: object = ()) -> bool:
    """이 출처가 **라우팅 가능한 주소인데 선언된 어느 대역에도 없는가**. 총함수.

    ⚠️ *"세지 않는다"* 에는 **두 가지 다른 이유**가 있고, 그 둘을 한 칸으로 접으면
    이 축이 자기 배포에 경보를 울린다:

    * **시험원일 수 없다** — 루프백·미지정·판독 불가. 배포가 자기 자신에게 보낸
      요청이고, 그것을 «귀속 불가» 로 세면 정상 배포가 영원히 경보 상태다.
    * **시험원일 수는 있는데 선언 밖이다** — 라우팅 가능한 실 주소가 왔는데
      운영자가 그 대역을 시험원으로 선언하지 않았다. 상위 프록시가 신설된 배포가
      정확히 이 모양이고, 이것이 :data:`PEER_AXIS_SOURCES_UNATTRIBUTABLE` 의 근거다.

    선언이 **비어 있으면 False** 다 — 그 상태는 이미 자기 토큰
    (:data:`PEER_AXIS_UNDECLARED_CLIENTS`)을 갖고, 두 토큰이 동시에 성립하면
    운영자는 조치 두 개를 받는다.
    """
    return classify_caller(
        peer_key, client_ranges, restored=True) == CALLER_UNATTRIBUTABLE


def _networks(client_ranges: object):
    """선언된 대역을 :mod:`ipaddress` 객체로. **총함수** — 읽을 수 없는 항목은 버린다."""
    if client_ranges is None:
        return ()
    if isinstance(client_ranges, (str, bytes)):
        return ()
    try:
        items = list(client_ranges)
    except Exception:
        return ()
    networks = []
    for item in items:
        if isinstance(item, (IPv4Network, IPv6Network)):
            networks.append(item)
            continue
        try:
            networks.append(_ip_network(_text(item), strict=False))
        except (ValueError, TypeError):
            continue
    return tuple(networks)


def _flag(value: object) -> bool:
    """``bool(value)`` 이 **터지지 않는** 판독.

    ⚠️ 평범한 ``bool(x)`` 로는 총함수가 성립하지 않는다 — ``__bool__`` 이 예외를 던지는
    객체 하나가 이 판정을 통째로 죽인다. 형제 ``chamber_mode_policy`` 가 같은 함정을
    같은 이유로 이름 붙였고(챔버 **목록 전체**가 죽었다), 판독 불가는 **참으로 읽지
    않는다** — 참으로 읽으면 읽을 수 없는 값이 ``per-source`` 주장으로 승격한다.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    try:
        return bool(value)
    except Exception:
        return False


@dataclass(frozen=True)
class PeerAxisObservation:
    """프로세스가 실제로 본 것 — **개수가 아니라 두 술어**.

    ``saw_any`` / ``saw_more_than_one`` 이 판정의 전부이고, ``sample_count`` 와
    ``seconds_since_first_sample`` 은 **신선도 표시용**이라 판정에 들어가지 않는다.

    ⚠️ **그 둘이 판정에 들어가지 않는 것이 설계다.** 표본 수를 판정에 넣는 순간
    *"표본 N개인데 출처가 하나면 붕괴"* 라는 임계값이 필요해지고, 그 임계값은 위
    docstring 이 적은 이유로 존재하지 않는다.
    """

    saw_any: bool = False
    saw_more_than_one: bool = False
    #: 운영자가 «시험원이 어디 사는가» 를 선언했는가. 판정의 **선행 조건**이고
    #: 관측이 아니다 — 그래서 개수가 아니라 술어다.
    clients_declared: bool = False
    sample_count: int = 0
    seconds_since_first_sample: float = 0.0
    #: caller 경로로 왔으나 **선언된 시험원에게 귀속되지 않은** 요청을 한 번이라도
    #: 봤는가. ⚠️ **개수가 아니라 술어인 것이 설계다** — 이 모듈의 다른 두 관측
    #: (``saw_any``/``saw_more_than_one``)과 같은 이유이고, 개수를 판정에 넣는 순간
    #: *"몇 개부터 문제인가"* 라는 존재하지 않는 임계값이 필요해진다.
    saw_unattributable: bool = False
    #: 그 요청의 **개수**. 운영자가 규모를 봐야 하므로 나르지만, ``sample_count`` 와
    #: 같이 **판정에는 들어가지 않는다**.
    unattributable_samples: int = 0

    @classmethod
    def empty(cls) -> 'PeerAxisObservation':
        """아무것도 관측되지 않은 상태 — 부팅 직후."""
        return cls()

    def as_dict(self) -> dict:
        """진단 봉투.

        ⚠️ **주소가 실리지 않는다.** 이 봉투는 게이지·로그·런북으로 나가는데,
        peer 키는 실 클라이언트 주소일 수 있고 형제 축은 그것을 PII 로 취급해
        ``/24`` 로 자른다. 여기서는 애초에 나르지 않는 것이 정공이다 — 판정에
        필요한 것은 *몇 종류인가* 이지 *무엇인가* 가 아니다.
        """
        return {
            'clients_declared': bool(self.clients_declared),
            'saw_any': bool(self.saw_any),
            'saw_more_than_one': bool(self.saw_more_than_one),
            'sample_count': int(self.sample_count),
            'seconds_since_first_sample': float(self.seconds_since_first_sample),
            'saw_unattributable': bool(self.saw_unattributable),
            'unattributable_samples': int(self.unattributable_samples),
        }


def reconcile_peer_axis(configured_mode: object, observation: object) -> str:
    """기대 축과 관측 축을 대조해 판정 토큰 하나를 답한다. **총함수.**

    ⚠️ **기대가 관측보다 먼저다.** 신뢰 hop 이 없으면 서버는 체인을 복원조차 하지
    않으므로, 그때 관측된 다양성은 *우리가 만든 것이 아니다* — 리버스 프록시가 없는
    호스트(챔버 노드)에서 실 주소가 그대로 보이는 것뿐이고, 그 배포의 peer 예산은
    여전히 배포가 정한 것이지 이 축이 보장한 것이 아니다. 형제 ``chamber_mode_policy``
    가 ``UNDECLARED`` 를 관측보다 앞에 두는 것과 같은 순서다.

    ⚠️ **읽을 수 없는 기대 값은 ``per-source`` 로 읽지 않는다.** ``configured_mode`` 가
    정확히 :data:`PEER_AXIS_PER_SOURCE` 일 때만 관측 축으로 넘어간다 — 오타·``None``·
    새 토큰은 전부 보수적인 쪽(배포 단위)으로 떨어진다. 반대로 하면 판독 실패가
    *"사람마다 과금된다"* 는 주장으로 승격한다.
    """
    if _text(configured_mode) != PEER_AXIS_PER_SOURCE:
        return PEER_AXIS_DEPLOYMENT_WIDE

    # ⚠️ **선언이 관측보다 먼저다** — 기대가 관측보다 먼저인 것과 같은 순서, 같은 이유.
    # 시험원이 어디 사는지 아무도 선언하지 않았으면, 도착한 주소가 시험원의 것인지
    # 이웃 컨테이너의 것인지 이 코드는 알 수 없다. 그 위에서 «증명» 을 말할 수 없다.
    if not _flag(getattr(observation, 'clients_declared', None)):
        return PEER_AXIS_UNDECLARED_CLIENTS

    saw_any = _flag(getattr(observation, 'saw_any', None))
    saw_more = _flag(getattr(observation, 'saw_more_than_one', None))
    # 둘 이상을 봤다면 하나는 당연히 봤다. 모순된 입력(관측기 결함·손으로 만든 값)에서
    # "둘은 봤는데 하나도 못 봤다" 를 ``unobserved`` 로 답하면 더 강한 사실을 버린다.
    if saw_more:
        return PEER_AXIS_OBSERVED_DISTINCT
    if saw_any:
        return PEER_AXIS_OBSERVED_SINGLE
    # ⚠️ **«아무것도 안 왔다» 와 «오는데 귀속이 안 된다» 는 다른 사실이고, 옛 코드는
    # 둘을 같은 토큰으로 접었다** (적대 평가 3R). 접으면 상위 프록시가 신설된 배포가
    # 영원히 «재기동 직후의 정상» 으로 읽힌다 — 그리고 그 시나리오는 이 축의 존재
    # 이유로 런북이 직접 지목한 것이다. 여기서만 개수를 술어로 좁힌다(> 0).
    if _flag(getattr(observation, 'saw_unattributable', None)):
        return PEER_AXIS_SOURCES_UNATTRIBUTABLE
    return PEER_AXIS_UNOBSERVED


def describe_peer_axis_verdict(verdict: object) -> str:
    """판정 → 운영자가 **할 일** 한 문장. 총함수.

    설명이 *상태*가 아니라 *조치*인 이유: 게이지를 보는 사람은 이미 상태를 봤다.
    모르는 토큰도 이름을 대며 답한다 — 자기를 설명하지 못하는 판정은 운영자에게
    고장과 구분되지 않는다(형제 ``describe_defect`` 와 같은 규율).
    """
    token = _text(verdict)
    described = _VERDICT_ACTIONS.get(token)
    if described is None:
        return (
            f'{token!r} is not a peer-axis verdict this build knows; '
            f'known verdicts are {", ".join(PEER_AXIS_VERDICTS)}.'
        )
    return described


def _text(value: object) -> str:
    """총 문자열화 — ``__str__`` 이 터지는 값도 판정을 죽이지 않는다."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    try:
        return str(value).strip()
    except Exception:
        return ''


#: 판정 → 조치. **런북 §2-bis 와 집합 상등**이어야 한다(봉인이 그것을 단언한다) —
#: 게이지가 답하는 토큰에 대해 런북이 침묵하면 운영자는 관측만 하고 아무것도 못 한다.
_VERDICT_ACTIONS: dict[str, str] = {
    PEER_AXIS_UNDECLARED_CLIENTS: (
        'nobody has declared where real clients live, so an address arriving here '
        'cannot be told apart from a neighbouring container, a LAN scanner or an '
        'operator who typed the API port. Declare the client ranges; until then '
        'this axis refuses to call anything proof.'
    ),
    PEER_AXIS_UNOBSERVED: (
        'no request from a declared client range has been seen yet, so there is '
        'nothing to judge. This is the normal state just after a restart — look '
        'again once testers are working.'
    ),
    PEER_AXIS_SOURCES_UNATTRIBUTABLE: (
        'requests ARE arriving, but not one of them came from a declared client '
        'range, so none can be attributed to a tester. Do NOT read this as the '
        'normal post-restart state. Three things produce it and you must tell '
        'them apart: (1) the declared ranges are wrong or incomplete; (2) a hop '
        'UPSTREAM of the trusted proxy is folding every caller onto its own '
        'address — the very collapse this axis exists to detect; (3) traffic is '
        'reaching the published API port directly instead of through the proxy. '
        'Compare the source addresses in the gateway access log with the '
        'declared ranges to decide which. Two more causes to rule out: your '
        'proxy may forward "host:port" rather than a bare address (this build '
        'cannot recognise that as a restored request, so it answers here '
        'rather than claiming proof), and immediately after a restart a single '
        'infrastructure probe can raise this before any tester has connected — '
        'look again once someone is working.'
    ),
    PEER_AXIS_OBSERVED_SINGLE: (
        'exactly one source has been seen. That does NOT mean the path collapsed '
        '— it is also what one tester working alone looks like. Have a SECOND '
        'tester PC connect, then read this gauge again.'
    ),
    PEER_AXIS_DEPLOYMENT_WIDE: (
        'no trusted hop is configured, so every caller behind a reverse proxy '
        # ⚠️ 변수 **철자는 파생한다** — 이 문장이 리터럴로 그 이름을 적으면 저장소에
        # 두 번째 사본이 생기고, ``TestTrustResolutionHasExactlyOneOwner`` 가 즉시
        # red 가 된다(실제로 그렇게 잡혔다). 그 봉인이 지키는 것은 철자 위생이 아니라
        # *"어느 변수가 신뢰를 정하는가" 에 답이 하나* 라는 사실이다.
        f'shares ONE budget. Fix the wiring first ({TRUSTED_PROXY_ENV} must name '
        'the reverse proxy by its own address); the observation cannot help '
        'until it is set.'
    ),
    PEER_AXIS_OBSERVED_DISTINCT: (
        'two or more distinct sources have been seen, so this path preserves the '
        'origin and the peer budget really is charged per caller. Nothing to do.'
    ),
}
