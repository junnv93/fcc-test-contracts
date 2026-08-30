"""Proxy-trust policy — pure domain (peer 축 신뢰 hop, 2026-08-22).

이 모듈이 답하는 질문은 하나다: **어떤 출처를 "우리 리버스 프록시" 로 믿어도 되는가.**

## 왜 이 질문이 보안 질문인가

ASGI 경계에서 요청의 전송 출처(``scope['client']``)는 두 가지 중 하나다 — 실 클라이언트의
주소이거나, 우리 앞에 선 프록시의 주소다. 후자일 때 실 주소는 ``X-Forwarded-For`` 체인
안에 있고, **그 체인의 왼쪽은 공격자가 채울 수 있다**(프록시는 받은 값 뒤에 자기가 본
주소를 *덧붙일* 뿐이다). 그러므로 "실 주소가 무엇인가" 는 **"어디까지가 우리 hop 인가"**
를 먼저 정해야만 답할 수 있다.

이 저장소에서 그 해석을 실제로 수행하는 것은 uvicorn 의 ``ProxyHeadersMiddleware`` 이고
(``FORWARDED_ALLOW_IPS``), FCC 코드는 **원시 헤더를 어디서도 파싱하지 않는다**. 그것이
설계다: 신뢰 해석의 소유자가 둘이면 둘 중 느슨한 쪽이 실질 정책이 된다. 이 모듈은 그
한 곳에 **무엇을 넣어도 되는지**를 판정한다 — 파싱하지 않고, 판정만 한다.

## ⚠️ 대역을 통째로 신뢰하면 안 되는 이유 (실측 2026-08-22)

uvicorn 의 규칙은 *"체인을 역순으로 훑어 신뢰 목록에 **없는** 첫 호스트"* 이고, 그 규칙
자체는 안전하다. 그러나 **체인의 모든 항목이 신뢰 대상이면 최좌측 — 즉 공격자가 넣은
값 — 을 답한다**(``get_trusted_client_address`` 의 마지막 줄). 그러므로 신뢰 집합이
넓어져 실 클라이언트가 들어오는 순간, 훑기는 실 클라이언트를 **지나쳐** 공격자 값에
도달한다. 그리고 그때 아무 예외도 나지 않는다 — **조용히** 틀린 값이 된다.

컨테이너 브리지 대역을 통째로 신뢰하는 처방이 이 함정을 밟는다: 그 대역에는 브리지
**게이트웨이 주소**가 들어 있고, 게시된 포트로 들어온 트래픽이 게이트웨이 주소로 보이는
배포 형태가 실재한다. 그러면 체인이 전부 신뢰 대상이 되어 위 폴백이 발화한다. 즉
*"대역을 신뢰한다"* 는 이 저장소가 통제하지 않는 데몬 설정에 조용히 의존한다.

**답은 최소권한이다 — 프록시 "한 주소" 를 신뢰한다.** 그 주소는 배포가 선언하고
(compose 가 리버스 프록시에 정적 주소를 준다), 실 클라이언트는 정의상 그 주소일 수 없다.

## 이 모듈의 세 판정

* :func:`parse_trusted_proxies` — 총함수 정규화.
* :func:`trust_defects` — **거부 사유** tuple. 빈 tuple 이 "안전" 이다.
* :func:`peer_axis_mode` — peer 예산이 *출처당*인지 *배포 단위*인지. 사이징 질문이
  가정이 아니라 **관측**이 되게 한다.

## 총함수다 — 어떤 입력에도 raise 하지 않는다

이 판정은 프로세스 **부팅 경로**에서 돌고, 그 호출에는 ``try/except`` 가 없다. 판정기가
던지면 오설정 진단 대신 트레이스백이 나오고, 더 나쁘게는 *판정 자체가 일어나지 않는다*.
그러므로 읽을 수 없는 값은 **거부 사유로 분류**하지 예외로 만들지 않는다.

⚠️ **새 숫자 상수가 없는 것이 의도다.** 이 모듈에는 임계값이 없다 — 모든 판정이
:mod:`ipaddress` 의 술어에서 파생한다. 임계값이 생기는 순간 "얼마나 넓으면 너무 넓은가"
라는 답할 수 없는 질문이 정책이 된다.
"""
from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network
from ipaddress import ip_network as _ip_network
from typing import Iterable, Optional, Tuple, Union


__all__ = [
    'DEFECT_CLIENT_OVERLAP',
    'DEFECT_NOT_ONE_HOP',
    'DEFECT_OWN_GATEWAY',
    'DEFECT_PUBLIC_RANGE',
    'DEFECT_UNREADABLE',
    'DEFECT_WILDCARD',
    'PEER_AXIS_DEPLOYMENT_WIDE',
    'PEER_AXIS_PER_SOURCE',
    'TRUSTED_PROXY_ENV',
    'UNREADABLE_ENTRY_TOKEN',
    'TrustDefect',
    'describe_defect',
    'parse_trusted_proxies',
    'peer_axis_mode',
    'trust_defects',
]


#: uvicorn 이 **이미** 읽는 이름. 우리가 새 이름을 발명하지 않는 것이 요지다 —
#: 별칭을 만들면 "어느 변수가 실제로 신뢰를 정하는가" 가 두 답을 갖게 되고, 운영자가
#: 우리 변수를 설정하고 uvicorn 은 기본값으로 도는 상황이 조용히 성립한다.
TRUSTED_PROXY_ENV = 'FORWARDED_ALLOW_IPS'

#: 신뢰 목록에 있으면 **모든** 요청의 peer 키가 공격자 선택이 되는 값들.
#: uvicorn 은 ``'*'`` 를 "전부 신뢰" 로 읽고, 기본 라우트 CIDR 은 같은 것을 CIDR 문법으로
#: 적은 것이다 — 둘을 다르게 취급하면 후자가 우회로가 된다.
_WILDCARD_TOKEN = '*'

DEFECT_WILDCARD = 'wildcard'
DEFECT_PUBLIC_RANGE = 'public_range'
DEFECT_CLIENT_OVERLAP = 'client_overlap'
DEFECT_UNREADABLE = 'unreadable'
DEFECT_NOT_ONE_HOP = 'not_one_hop'
DEFECT_OWN_GATEWAY = 'own_gateway'

#: peer 예산이 뜻하는 것. 문자열 리터럴이 아니라 상수인 이유는 관측 소비자(로그·런북·
#: 테스트)가 같은 토큰을 봐야 하기 때문이다.
PEER_AXIS_PER_SOURCE = 'per-source'
PEER_AXIS_DEPLOYMENT_WIDE = 'deployment-wide'

_Network = Union[IPv4Network, IPv6Network]

#: 사유 → 사람이 읽는 설명. 거부 메시지가 **무엇이 왜 위험한지** 를 이름으로 대게 한다.
#: (거부 메시지가 "invalid value" 이면 운영자는 값을 바꿔가며 추측하고, 가장 빨리 통과하는
#: 추측은 대개 더 넓은 값이다.)
_DEFECT_DESCRIPTIONS = {
    DEFECT_WILDCARD: (
        'trusts every source, so the forwarded chain is trusted end to end and '
        'the proxy-headers middleware falls back to the LEFTMOST entry — the one '
        'an attacker writes. Every request would then carry an attacker-chosen '
        'peer identity, silently.'
    ),
    DEFECT_PUBLIC_RANGE: (
        'is globally routable, so it is not a hop this deployment owns. A trusted '
        'hop must be an address we placed there ourselves.'
    ),
    DEFECT_CLIENT_OVERLAP: (
        'overlaps a declared client range, so the reverse walk would step PAST the '
        'real client and reach the attacker-supplied entry to its left.'
    ),
    DEFECT_UNREADABLE: (
        'is not an IP address or network. A trusted hop that cannot be read cannot '
        'be checked, and uvicorn would keep it as an opaque literal.'
    ),
    DEFECT_OWN_GATEWAY: (
        "is this host's own default gateway, which is what a connection arriving "
        "through a PUBLISHED PORT looks like from inside the container. Trusting it "
        "therefore trusts every caller that reaches a published port, and the "
        "forwarded chain they send becomes their identity. Name the reverse "
        "proxy's own address instead; if this host has no reverse proxy in front "
        "of it, leave the variable unset."
    ),
    DEFECT_NOT_ONE_HOP: (
        'is a RANGE, and a range is not a hop. Every address it covers becomes a '
        'trusted forwarder, so a chain whose entries all fall inside it is trusted '
        'end to end and the proxy-headers middleware falls back to the LEFTMOST '
        'entry — the one an attacker writes.'
    ),
}


class TrustDefect(tuple):
    """A refusal: ``(reason, entry)``.

    ``tuple`` subclass rather than a dataclass so the value compares, hashes and
    prints as the pair it is — the callers that matter (a boot-time refusal
    message and a test) both want exactly that pair and nothing else.
    """

    __slots__ = ()

    def __new__(cls, reason: str, entry: str) -> 'TrustDefect':
        return super().__new__(cls, (str(reason), str(entry)))

    @property
    def reason(self) -> str:
        return self[0]

    @property
    def entry(self) -> str:
        return self[1]


#: What an entry becomes when it cannot be rendered as text at all. It is
#: deliberately **non-empty and not an IP**, so it survives normalisation and is
#: then classified :data:`DEFECT_UNREADABLE`.
#:
#: ⚠️ Returning ``''`` here — the obvious choice, and the first implementation —
#: is fail-**open**: an entry that cannot be read would drop out of the list and
#: the configuration would be reported as *"not set"*, i.e. a degradation notice
#: instead of a refusal. *"Cannot be read"* and *"was not provided"* are different
#: facts and only one of them is safe to keep quiet about.
UNREADABLE_ENTRY_TOKEN = '<unreadable>'


def _text(value: object, *, unreadable: str = '') -> str:
    """Coerce anything to text without ever raising.

    ⚠️ ``str(value)`` can raise — a hostile ``__str__`` is a real input here
    because this runs on operator-supplied configuration. Total by construction.
    """
    try:
        return str(value)
    except Exception:  # noqa: BLE001 — a hostile __str__ must not break boot
        return unreadable


def parse_trusted_proxies(raw: object) -> Tuple[str, ...]:
    """Normalise a raw ``FORWARDED_ALLOW_IPS`` value into entries.

    uvicorn accepts either a comma-separated string or a list, and splits on
    ``','`` with ``.strip()`` per item. This mirrors that split so the policy
    judges **exactly the entries uvicorn will build its trust set from** — a
    normaliser that disagreed with the consumer would approve a value the
    consumer reads differently.

    Total: ``None``, empty, non-string and hostile inputs all yield entries
    (possibly empty) rather than raising.
    """
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple, set, frozenset)):
        items: Iterable[object] = raw
    else:
        items = _text(raw, unreadable=UNREADABLE_ENTRY_TOKEN).split(',')
    entries = []
    # ⚠️ **반복 자체가 raise 할 수 있다.** ``_text`` 는 원소의 ``__str__`` 을 감쌌지만
    # 컨테이너의 ``__iter__`` 는 감싸지 않았고, 적대 평가가 그 구멍을 실행으로 보였다
    # (``__iter__`` 가 던지는 list 서브클래스 → ``RuntimeError`` 가 부팅 경로로 전파).
    # 저장소 장부의 *"container type checked, element type not"* 을 뒤집은 형태다.
    # 총함수는 컨테이너 축에서도 총함수여야 한다 — 부팅 경로의 그 호출에는
    # ``try/except`` 가 없다.
    try:
        for item in items:
            text = _text(item, unreadable=UNREADABLE_ENTRY_TOKEN).strip()
            if text:
                entries.append(text)
    except Exception:  # noqa: BLE001 — a hostile container must not break boot
        # 같은 이유로 **비우지 않는다** — 아무것도 남기지 않으면 "읽을 수 없었다" 가
        # "설정되지 않았다" 로 보고되고, 둘 중 하나만 조용해도 되는 사실이다.
        entries.append(UNREADABLE_ENTRY_TOKEN)
    return tuple(entries)


def _as_network(entry: str) -> Optional[_Network]:
    """Read one entry the way **uvicorn** reads it, or ``None`` if it cannot.

    A bare address becomes its single-host network, so every downstream question
    ("does it overlap X", "is it globally routable", "is it one hop") has exactly
    one shape to ask.

    ⚠️ **``strict=True`` is a parity requirement, not a preference.** uvicorn calls
    ``ipaddress.ip_network(host)`` — strict — and files a ``ValueError`` into
    ``trusted_literals``, where it can never match an IP. So a host-bits-set CIDR
    (``172.31.240.5/24`` — the ordinary way an operator writes *"my proxy is .5 on
    a /24"*) trusts **nothing** at all in uvicorn. Under a lenient reader this
    module would call that value safe and log ``per-source`` while the deployment
    had silently reverted to one shared bucket: the pre-wave defect, with the
    observability channel asserting the opposite. Measured by adversarial review.

    A value the consumer cannot read is ``unreadable`` here, which is the truthful
    classification and the loud one.
    """
    try:
        network = _ip_network(entry, strict=True)
    except ValueError:
        return None
    # ⚠️ **IPv4-mapped IPv6 은 소비자가 절대 맞추지 못한다.** ``::ffff:172.31.240.10``
    # 은 `ipaddress` 에서 유효한 한 주소지만, uvicorn 은 들어오는 host 를
    # ``ip_address(host)`` 로 읽어 IPv4 로 만들므로 이 IPv6 집합과 영원히 매칭되지
    # 않는다 — 정책이 승인하고 ``per-source`` 라고 로그하는데 **아무도 신뢰되지
    # 않는다**(실측). ``strict`` 파리티와 같은 계열의 나머지 절반이다.
    if getattr(network.network_address, 'ipv4_mapped', None) is not None:
        return None
    return network


def _is_default_route(network: _Network) -> bool:
    """``0.0.0.0/0`` / ``::/0`` — the CIDR spelling of "trust everything"."""
    return network.prefixlen == 0


def _is_public(network: _Network) -> bool:
    """Globally routable — i.e. not a hop this deployment could have placed.

    ⚠️ Delegates to :attr:`ipaddress._BaseNetwork.is_private`, which asks whether
    **both ends land inside one** IANA special-registry block. The obvious
    hand-rolled version — "network address is private *and* broadcast address is
    private" — is **wrong**, and measurably so: ``0.0.0.0/1`` has a private first
    address (``0.0.0.0``) and a private last address (``127.255.255.255``) while
    containing the whole of ``1.0.0.0``–``126.255.255.255``. That value would
    have been accepted as a trusted hop. Derive from the stdlib predicate; do not
    re-derive the registry here.
    """
    return not network.is_private


def _is_loopback_only(entry: str) -> bool:
    """Does this entry name nothing but loopback? (uvicorn's own default.)"""
    network = _as_network(entry)
    if network is None:
        return False
    return network.network_address.is_loopback and network.broadcast_address.is_loopback


def _client_networks(client_ranges: object) -> Tuple[_Network, ...]:
    networks = []
    for entry in parse_trusted_proxies(client_ranges):
        network = _as_network(entry)
        if network is not None:
            networks.append(network)
    return tuple(networks)


def trust_defects(
    entries: object,
    *,
    client_ranges: object = (),
    local_gateways: object = (),
) -> Tuple[TrustDefect, ...]:
    """Every reason this trust configuration must be refused. Empty = safe.

    ``client_ranges`` is the operator's declaration of where real clients live.
    When it is empty the overlap check is **skipped, not failed** — a gate that
    refuses because it cannot observe is a gate that gets deleted, and the other
    checks stand on their own.

    ``local_gateways`` is an **observation**, not a declaration: the addresses this
    host routes through by default. The caller supplies it (this module reads
    nothing), and when it is empty that check is skipped for the same reason.

    ⚠️ **Why the gateway needs its own branch even though every other rule passed
    it.** The design sentence is *"never trust the bridge gateway"* — the compose
    file says it, ``R-11`` says it, and the deployment seal enforces it for the
    *proxy's own address*. But the **trusted set** was never asked. Adversarial
    review brought the real stack up with ``FORWARDED_ALLOW_IPS=172.31.240.1``:
    it booted clean, logged ``per-source``, and then 14 requests rotating
    ``X-Forwarded-For`` were **all allowed** — the throttle was gone, and pinning a
    victim's address exhausted that victim's budget instead. A gateway address is
    one address, is private, is readable, and does not overlap any declared client
    range, so nothing else in this function had a reason to look at it.

    Order is by entry, then by the order the checks are written, so a refusal
    message reads in the order the operator wrote the value.
    """
    parsed = parse_trusted_proxies(entries)
    clients = _client_networks(client_ranges)
    gateways = frozenset(
        network.network_address for network in _client_networks(local_gateways)
    )
    defects = []
    for entry in parsed:
        if entry == _WILDCARD_TOKEN:
            defects.append(TrustDefect(DEFECT_WILDCARD, entry))
            continue
        network = _as_network(entry)
        if network is None:
            defects.append(TrustDefect(DEFECT_UNREADABLE, entry))
            continue
        if _is_default_route(network):
            # Same effect as '*', reached through CIDR syntax. Reported under the
            # same reason on purpose: two names for one hazard means a runbook
            # can close one and believe it closed both.
            #
            # ⚠️ Honest about what this branch buys: a default route is also not
            # private, so the ``public_range`` check below would refuse it too.
            # What this branch changes is the REASON the operator is handed —
            # "you trusted everything" instead of "that hop is not yours" — and
            # for the single most dangerous value that difference is the whole
            # message. The literal ``'*'`` is handled above for the same purpose:
            # without it, uvicorn's own wildcard spelling would be classified
            # ``unreadable``, which is true and useless.
            defects.append(TrustDefect(DEFECT_WILDCARD, entry))
            continue
        if _is_public(network):
            defects.append(TrustDefect(DEFECT_PUBLIC_RANGE, entry))
            continue
        if network.num_addresses != 1:
            # ⚠️ **이 분기가 이 모듈의 요지다.** 위 docstring 전체가 *"대역이 아니라 한
            # 주소"* 를 설명하는데, 초판에는 그것을 묻는 분기가 **없었다** — `*` 와 공인
            # 대역만 막고 사설 대역은 통과시켰다. 적대 평가가 실행으로 보였다:
            # ``FORWARDED_ALLOW_IPS=${CENTRAL_APP_SUBNET}`` — 같은 compose 파일 20줄
            # 아래에 선언된 값 — 이 결함 0으로 부팅했고, 그 구성에서 공격자가
            # ``X-Forwarded-For`` 에 적은 **시험원의 주소**가 그대로 peer 키와 스프레이
            # 관측 키가 됐다(피해자 예산 소진 + 스프레이 귀속). *설계가 거부하는 값을
            # 게이트가 승인하고 있었다.*
            #
            # 임계값을 발명하지 않는다 — ``num_addresses != 1`` 은 ``ipaddress`` 에서
            # 그대로 나오고 IPv4/IPv6 양쪽에 같은 문장으로 참이다(``/32``·``/128`` 은
            # 1). 맨몸 주소도 ``/32`` 로 읽히므로 통과한다.
            defects.append(TrustDefect(DEFECT_NOT_ONE_HOP, entry))
            continue
        if network.network_address in gateways:
            defects.append(TrustDefect(DEFECT_OWN_GATEWAY, entry))
            continue
        if any(network.overlaps(client) for client in clients):
            defects.append(TrustDefect(DEFECT_CLIENT_OVERLAP, entry))
    return tuple(defects)


def describe_defect(defect: object) -> str:
    """One sentence naming the entry and why it is refused.

    Total — an unknown reason still produces a message that names the entry,
    because a refusal that cannot describe itself is indistinguishable from a
    crash to the operator reading the log.
    """
    reason = _text(getattr(defect, 'reason', '')) or ''
    entry = _text(getattr(defect, 'entry', '')) or ''
    if not reason and isinstance(defect, (tuple, list)) and len(defect) >= 2:
        reason, entry = _text(defect[0]), _text(defect[1])
    description = _DEFECT_DESCRIPTIONS.get(
        reason, 'is refused by the proxy-trust policy.',
    )
    return f'{entry!r} ({reason}) {description}'


def peer_axis_mode(entries: object) -> str:
    """What the peer budget actually means on this deployment.

    ``per-source`` — a trusted hop is configured, so the middleware restores the
    real client address and the peer tier is charged per caller.

    ``deployment-wide`` — nothing is trusted beyond uvicorn's loopback default,
    so behind a reverse proxy every caller collapses into ONE bucket. That is a
    **capacity fact**, not a bug on its own: it is exactly why a source ceiling
    may not be tightened until this returns ``per-source``
    (ADR-0021 D-11 recorded the cost of tightening one that had not).

    ⚠️ **``per-source`` means "the source is restored from the chain", not
    "one bucket per human".** Two ways it can be true and still not be per-tester,
    and both are properties of the *network*, not of this code:

    * another proxy sits in front of our own — the reverse walk then stops at
      *that* proxy, because it is the rightmost host we do not trust, and every
      caller behind it shares its address;
    * several testers share one source address (NAT).

    Neither is the shipped topology (nginx publishes to the LAN and each PC has
    its own address), but a deployment that grows one of them will read
    ``per-source`` while behaving like ``deployment-wide``. Sizing a ceiling is
    therefore still a **measurement**, not an inference from this token — which
    is the same warning D-11 earned the hard way.
    """
    parsed = parse_trusted_proxies(entries)
    if not parsed:
        return PEER_AXIS_DEPLOYMENT_WIDE
    # ⚠️ **``127.0.0.1`` 은 uvicorn 의 기본값이므로 "설정했다" 가 아니다.** 초판은 값이
    # 비어 있지 않기만 하면 ``per-source`` 를 답했고, 그래서 이 토큰은 *변수의 재진술*
    # 이었다 — 그리고 다음 웨이브가 그것을 보고 예산을 정하기로 돼 있었다. 리버스 프록시
    # 뒤에서 loopback 만 신뢰하는 것은 아무것도 신뢰하지 않는 것과 **동작이 같다**.
    if all(_is_loopback_only(entry) for entry in parsed):
        return PEER_AXIS_DEPLOYMENT_WIDE
    return PEER_AXIS_PER_SOURCE
