"""Login lockout + spraying policy — pure domain (P3 하드닝, 2026-08-21).

계정 잠금과 스프레이 탐지는 **다른 질문에 답하는 두 축**이고, 둘을 한 칸으로 접으면
어느 쪽도 읽을 수 없게 된다:

===========  ===================================  ==========================
축           묻는 것                              키
===========  ===================================  ==========================
**잠금**     한 계정이 얼마나 틀렸나              ``user_id`` (해소된 사용자)
**스프레이** 한 출처가 몇 **개의 계정**을 건드렸나  요청 출처 지문
===========  ===================================  ==========================

스프레이 공격은 계정마다 **한두 번씩만** 틀리므로 잠금 임계값에 영원히 닿지 않는다 —
잠금만으로는 구조적으로 보이지 않는 공격이다. 반대로 한 사용자의 오타 반복은 스프레이가
아니다. EMS 가 같은 이유로 두 기전을 따로 갖는다(``login-spraying-detector.service.ts``
는 잠금과 별개이고 **아무것도 차단하지 않는다** — 관측 전용).

## ⚠️ 잠금 판정은 여기서 계산되지만 여기서 *적용*되지 않는다

:func:`fold_failed_attempts` 는 순수하고 테스트 가능하지만, **프로덕션 경로가 그것을
Python 에서 부르지는 않는다.** 실패 카운트를 읽고-고쳐-쓰면 두 요청이 같은 값을 읽어
같은 값을 쓰는 창이 열리고(TOCTOU), 그 창이 정확히 잠금을 무력화하는 자리다. 실제
집행은 **단일 원자적 UPDATE** 이고(``local_user_store.py``), 이 모듈은 그 SQL 이 쓰는
**숫자와 의미**를 소유한다 — SQL 에 리터럴 5/15 가 박히면 정책이 두 곳이 된다.

그러므로 이 모듈의 함수들은 *오라클*이다: 같은 접기 규칙을 순수하게 표현해 SQL 의
동작을 테스트가 대조할 수 있게 한다.

## ⚠️ 잠금은 앞으로 밀리지 않는다

이미 잠긴 계정을 계속 두드릴 때 ``locked_until`` 이 갱신되면, 공격자가 **정당한
사용자를 영구히 잠글 수 있다**(피해자 계정에 대한 DoS). 접기 규칙과 그 SQL 의
``WHERE`` 절이 함께 그것을 막는다 — :func:`should_extend_lock` 참조.
"""
from __future__ import annotations

import hashlib
import hmac
from ipaddress import ip_address as _ip_address
from ipaddress import ip_network as _ip_network
from datetime import datetime, timedelta, timezone
from typing import Optional


__all__ = [
    'LOCKOUT_DURATION_MINUTES',
    'LOCKOUT_MAX_ATTEMPTS',
    'LOCKOUT_WINDOW_MINUTES',
    'SPRAYING_DISTINCT_ACCOUNT_THRESHOLD',
    'SPRAYING_MAX_TRACKED_ACCOUNTS',
    'SPRAYING_MAX_TRACKED_ACCOUNT_ENTRIES',
    'SPRAYING_MAX_TRACKED_SOURCES',
    'SPRAYING_WINDOW_SECONDS',
    'fingerprint_digest',
    'fold_failed_attempts',
    'is_lock_active',
    'lock_expires_at',
    'should_extend_lock',
    'spraying_source_key',
    'spraying_suspected',
]


#: 연속 실패 몇 번에 잠그는가. EMS ``LOCKOUT_POLICY.MAX_ATTEMPTS``.
LOCKOUT_MAX_ATTEMPTS = 5

#: 실패 카운트가 살아 있는 창(분). 이보다 오래 조용하면 카운트는 1부터 다시 센다.
#: EMS ``LOCKOUT_POLICY.WINDOW_MIN``.
LOCKOUT_WINDOW_MINUTES = 15

#: 잠금 지속 시간(분). EMS ``LOCKOUT_POLICY.LOCK_MIN``.
LOCKOUT_DURATION_MINUTES = 15

#: 스프레이 관측 창(초). EMS ``SPRAYING_POLICY.WINDOW_SEC``.
SPRAYING_WINDOW_SECONDS = 600

#: 한 출처가 이 수 이상의 **서로 다른** 계정에 실패하면 의심 신호.
#: EMS ``SPRAYING_POLICY.DISTINCT_ACCOUNT_THRESHOLD``.
SPRAYING_DISTINCT_ACCOUNT_THRESHOLD = 5

#: 한 출처 버킷이 기억하는 계정 다이제스트의 상한. EMS
#: ``SPRAYING_POLICY.MAX_TRACKED_ACCOUNTS``.
#:
#: ⚠️ **상한이 없으면 이 관측 계층이 메모리 소진 경로가 된다.** 버킷 키는 출처 지문이고
#: 그 지문에는 공격자가 고르는 ``User-Agent`` 가 들어간다 — 즉 버킷 **개수**도, 버킷 안
#: 계정 집합의 **크기**도 공격자가 키운다. 임계값을 넘은 뒤로는 더 세어도 답이 바뀌지
#: 않으므로(이미 의심 신호를 냈다) 계속 기억할 이유가 없다. 착지 직전까지 이 상한이
#: 없었고 적대 평가가 그것을 찾았다.
#:
#: ⚠️ **이 상한만으로는 부족했고, 그것이 2026-08-22 축 교정의 출발점이다.** 이 값은 버킷
#: *안* 을 제한하는데 공격자가 키우는 것은 버킷 *개수* 였다 — 아래
#: :data:`SPRAYING_MAX_TRACKED_SOURCES` 와 :func:`spraying_source_key` 참조.
SPRAYING_MAX_TRACKED_ACCOUNTS = 50

#: 전 버킷을 합친 계정 다이제스트 **총량** 상한 — 메모리 봉투의 실제 소유자.
#:
#: 다이제스트 하나가 32자 문자열이므로 파이썬 set 안에서 대략 80바이트다. 5만 개면
#: 최악 ~4MB 이고, 그것이 관측 계층이 써도 되는 양이다.
SPRAYING_MAX_TRACKED_ACCOUNT_ENTRIES = 50_000

#: 동시에 기억하는 출처 버킷 **개수** 상한 — 총량에서 **파생**한다.
#:
#: ⚠️ 파생이 요점이다. 두 상한을 각자 적으면 버킷당 상한을 올린 사람이 총 메모리를
#: 몇 배로 만들고도 아무 단언도 red 가 되지 않는다. 나눗셈이 그 결합을 코드로 만든다 —
#: 계정 상한을 올리면 출처 상한이 자동으로 내려가 봉투가 유지된다.
SPRAYING_MAX_TRACKED_SOURCES = (
    SPRAYING_MAX_TRACKED_ACCOUNT_ENTRIES // SPRAYING_MAX_TRACKED_ACCOUNTS
)

#: 관측 키가 남기는 접두 길이. IPv4 는 ``/24``, IPv6 는 ``/64``.
#:
#: ⚠️ **IPv6 에 /64 가 없으면 D-9 가 이름 붙인 결함이 그대로 살아난다.** 한 호스트는 자기
#: /64 안의 하위 64비트를 **스스로 고른다** — 즉 주소 전체를 키로 쓰면 공격자가 원하는 만큼
#: 버킷을 쪼갤 수 있고, 그것은 User-Agent 를 뺀 이유와 글자 그대로 같은 형태다(적대 평가
#: 실측: 한 /64 에서 5,000 주소 → 버킷 5,000, 계정 1개씩, 경보 0건). 오늘 배포는 게이트웨이
#: IPv4 하나라 잠복 상태이지만, D-11 이 다음 웨이브의 선행 조건으로 지목한 *"실제 peer 주소
#: 복원"* 이 바로 이것을 깨우는 변경이다.
#:
#: ``::ffff:10.0.0.5`` 같은 dual-stack 표기도 ``ipaddress`` 가 IPv6 로 파싱하므로 옛
#: 점표기 분할이 조용히 건너뛰던 형태가 함께 닫힌다.
_IPV4_VERSION = 4
_IPV4_OBSERVATION_PREFIX = 24
_IPV6_OBSERVATION_PREFIX = 64


def fold_failed_attempts(
    previous_attempts: object,
    last_failed_at: Optional[datetime],
    now: datetime,
) -> int:
    """실패 1건을 접어 넣은 새 카운트. 총함수.

    창이 만료됐으면(마지막 실패가 ``LOCKOUT_WINDOW_MINUTES`` 보다 오래됨) **1 로
    재시작**한다 — 어제의 오타 두 번이 오늘의 오타 세 번과 합쳐져 잠기면 그 잠금은
    사용자에게 설명 불가능하다.

    ``previous_attempts`` 가 정수가 아니거나 음수면 0 으로 본다. DB 컬럼은
    ``NOT NULL DEFAULT 0`` 이지만 이 함수는 그 사실에 기대지 않는다 — 오라클이
    저장소 불변식을 가정하면 저장소가 그것을 어긴 날 오라클이 함께 눈을 감는다.
    """
    if _window_expired(last_failed_at, now):
        return 1
    try:
        previous = int(previous_attempts)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        previous = 0
    return max(previous, 0) + 1


def lock_expires_at(attempts: int, now: datetime) -> Optional[datetime]:
    """접힌 카운트가 임계값에 닿았을 때의 잠금 만료 시각, 아니면 ``None``."""
    if attempts < LOCKOUT_MAX_ATTEMPTS:
        return None
    return now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)


def is_lock_active(locked_until: Optional[datetime], now: datetime) -> bool:
    """지금 이 계정이 잠겨 있는가. 총함수.

    ⚠️ ``None`` 은 *"잠긴 적 없다"* 이고 과거 시각은 *"잠겼다가 풀렸다"* 이다. 둘 다
    통과이고, 그래서 **잠금 해제에 별도 수단이 필요 없다** — 시간이 해제한다. 그것이
    이 정책이 관리자 개입 없이도 안전한 이유다(잠금 해제 수단 없는 잠금은 그 자체로
    가용성 사고다).

    naive/aware 혼합은 **거짓 판정 대신 잠김으로** 접는다 — 시간대 정보가 없는 값을
    "안 잠겼다"로 읽는 것이 두 답 중 위험한 쪽이다.
    """
    if locked_until is None:
        return False
    try:
        return _as_aware(locked_until) > _as_aware(now)
    except (AttributeError, TypeError, ValueError):
        return True


def should_extend_lock(locked_until: Optional[datetime], now: datetime) -> bool:
    """이미 잠긴 계정에 실패가 하나 더 왔을 때 잠금을 **다시 밀어야** 하는가.

    답은 항상 ``False`` 다. 이 함수가 존재하는 이유는 그 답을 *실행 가능한 단언*으로
    만들기 위해서다 — 산문으로만 적힌 규칙은 다음 사람이 "잠긴 동안 또 틀렸으니
    연장하는 게 맞지 않나"라고 고칠 수 있고, 그 변경은 **피해자 계정 영구 잠금**이라는
    가용성 공격을 연다. 공격자는 피해자의 비밀번호를 몰라도 15분마다 다섯 번씩
    두드려 계정을 영원히 잠글 수 있다.
    """
    return False


def spraying_suspected(distinct_accounts: int) -> bool:
    """한 출처가 건드린 **서로 다른** 계정 수가 의심 임계값에 닿았는가."""
    return distinct_accounts >= SPRAYING_DISTINCT_ACCOUNT_THRESHOLD


def spraying_source_key(client_host: object) -> str:
    """스프레이 관측이 "한 출처" 라고 부를 값. 총함수 — raise 하지 않는다.

    ## ⚠️ 이 함수의 전부는 **무엇을 빼는가** 다 (축 교정, 2026-08-22)

    2026-08-21 착지분은 관측 키가 ``f'{subnet}|{user-agent}'`` 였다. ``User-Agent`` 는
    **공격자가 고른다.** 그래서 요청마다 UA 를 바꾸면:

    * 버킷 **개수**가 요청 수만큼 늘어 — 버킷 *안* 을 묶는
      :data:`SPRAYING_MAX_TRACKED_ACCOUNTS` 가 아무것도 막지 못하고,
    * 버킷마다 계정이 **하나씩**이라 :func:`spraying_suspected` 가 영원히 거짓이다.

    적대 평가 실측: UA 2만 종 → 버킷 2만 개, 경보 **0건**. 즉 상한은 메모리도 못 막고
    탐지도 못 했다. 상한을 키우는 것은 답이 아니다 — **차원이 틀렸다.**

    그러므로 탐지 키는 **공격자가 고를 수 없는 성분만** 담는다. 관측 대상을 가르는 값을
    관측 대상이 고르게 두면, 탐지기는 그가 원하는 만큼 잘게 쪼개진다.

    ## 왜 정밀도를 잃어도 되는가

    UA 를 빼면 한 NAT 뒤 서로 다른 클라이언트가 한 버킷으로 합쳐진다. 그 대가를 치를 수
    있는 이유는 이 계층이 **아무것도 차단하지 않기** 때문이다 — 오탐의 비용은 로그 한 줄이고,
    미탐의 비용은 공격을 통째로 놓치는 것이다. 비대칭이 축을 결정한다.
    (집행 계층인 계정축 스로틀은 정반대 이유로 정밀한 키를 쓴다.)

    ## 접두로 자르는 것은 유지하되, 두 프로토콜 모두에 적용한다

    한 시험원의 정확한 주소가 아니라 *"어떤 출처가 여러 계정에 계속 실패했다"* 가 답해야
    할 질문이고, 그것이 개인정보 최소화와 같은 방향이다. IPv4 는 ``/24``, IPv6 는 ``/64``.

    ⚠️ **IPv6 를 통째로 쓰던 첫 판은 위 결함을 그대로 남겼다** (적대 평가 2라운드). 한
    호스트는 자기 ``/64`` 안의 하위 64비트를 스스로 고르므로, 주소 전체가 키면 공격자가
    User-Agent 때와 **똑같이** 버킷을 쪼갤 수 있다(실측: 한 /64 에서 5,000 주소 → 버킷
    5,000, 경보 0건). "IPv4 점표기가 아니면 그대로 쓴다" 는 오탐 병합을 걱정한 규칙이었고,
    그것은 이 계층에서 **틀린 축**이다 — 위 §"왜 정밀도를 잃어도 되는가" 가 이미
    비대칭(로그 한 줄 vs 공격 전체를 놓침)으로 답을 정해 두었다.

    ## ⚠️ 이 키의 정밀도는 **배포**가 정한다 (2026-08-22)

    입력 ``client_host`` 는 ASGI 전송 출처이고, 그것이 실 클라이언트인지 리버스 프록시
    하나인지는 서버 경계의 신뢰 hop 설정이 정한다(:mod:`domain.services.proxy_trust_policy`).
    신뢰 hop 이 없으면 **모든 시험원이 프록시 주소 하나**로 보이므로, 이 함수가 아무리
    정확해도 관측 버킷은 하나이고 :func:`spraying_suspected` 는 *"한 출처가 여러 계정에
    실패했다"* 를 **배포 전체**에 대해서만 답한다 — 즉 정상 업무가 스프레이로 보인다.
    위 §"왜 정밀도를 잃어도 되는가" 의 비대칭(로그 한 줄 vs 공격을 놓침)은 그대로지만,
    그것은 *접두로 자르는* 대가에 대한 논거이지 *전원을 한 칸에 넣는* 것의 논거가 아니다.
    ``FORWARDED_ALLOW_IPS`` 가 설정된 배포에서만 이 축이 의도대로 동작한다.

    파싱은 :mod:`ipaddress` 가 한다. 옛 판은 점 4개 + ``str.isdigit()`` 로 판별했는데
    ``isdigit()`` 은 유니코드 숫자(``'١'``)에도 참이었다. IP 로 읽히지 않는 값(유닉스 소켓,
    호스트명, 빈 값)만 **그대로** 쓴다 — 읽을 수 없는 것을 자르면 서로 다른 출처가 합쳐진다.
    """
    host = str(client_host or '').strip()
    try:
        address = _ip_address(host)
    except ValueError:
        # Not an IP at all (unix socket, hostname, empty). Keep it verbatim —
        # truncating something we cannot parse would merge unrelated sources.
        return host
    # ⚠️ Unmap FIRST. A dual-stack listener reports IPv4 peers as ``::ffff:a.b.c.d``,
    # and treating that as IPv6 folds **every** IPv4 client into ``::/64`` — one
    # bucket for the whole internet, which is the opposite error from the one above
    # and just as blinding. That form is what uvicorn actually hands over on a
    # dual-stack socket, so it is the common case, not an edge case.
    mapped = getattr(address, 'ipv4_mapped', None)
    if mapped is not None:
        address = mapped
    if address.version == _IPV4_VERSION:
        return str(_ip_network(f'{address}/{_IPV4_OBSERVATION_PREFIX}', strict=False))
    return str(_ip_network(f'{address}/{_IPV6_OBSERVATION_PREFIX}', strict=False))


def _window_expired(last_failed_at: Optional[datetime], now: datetime) -> bool:
    if last_failed_at is None:
        return True
    try:
        elapsed = _as_aware(now) - _as_aware(last_failed_at)
    except (AttributeError, TypeError, ValueError):
        # 비교 불가한 값은 "창 만료"로 접는다 — 카운트를 1 로 재시작하는 쪽이
        # 알 수 없는 과거 카운트를 이어받는 쪽보다 설명 가능하다.
        return True
    # ⚠️ STRICT ``>``, matching ``RECORD_FAILED_LOGIN_SQL``'s
    # ``last_failed_at < now - make_interval(mins => …)``. With ``>=`` the oracle
    # and the SQL disagree at EXACTLY the window boundary — the SQL accumulates,
    # the oracle resets — and an oracle that claims to express the SQL's meaning
    # must not differ from it anywhere, least of all on the boundary it exists to
    # describe. Found by adversarial review, not by a test.
    return elapsed > timedelta(minutes=LOCKOUT_WINDOW_MINUTES)


def _as_aware(value: datetime) -> datetime:
    """naive datetime 을 UTC 로 본다. 두 축을 비교 가능하게 만드는 최소 변환."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def fingerprint_digest(secret: object, value: object) -> str:
    """익명화된 관측 키. 총함수.

    ⚠️ 스프레이 탐지가 보관하는 것은 **이것뿐**이다 — 원본 IP·user-agent·이메일은
    어디에도 남지 않는다. 그래서 그 구조가 통째로 유출돼도 누가 공격당했는지 나오지
    않는다.

    ⚠️ 이 함수가 도메인에 있는 이유는 두 가지다. (1) 익명화 규칙은 임계값과 같은
    정책 축이고, (2) ``application/platform`` 패키지는 ``hashlib`` 을 import 할 수
    없다 — 그 레이어에는 *condition_hash 를 중앙에서 재계산하지 않는다* 를 지키는 AST
    가드가 있고, 목적이 다른 해시라도 그 가드는 구분하지 못한다. 규칙을 느슨하게
    하는 대신 해시를 규칙이 사는 곳으로 옮긴다.

    ⚠️ **``surrogatepass`` 는 장식이 아니다.** ``str.encode('utf-8')`` 은 짝 없는
    surrogate(``'\\ud800'``)에 ``UnicodeEncodeError`` 를 낸다. 그 문자는 JSON 이스케이프
    (``"\\ud800"``)로 **와이어에서 도달 가능**하므로, 기본 인코딩을 쓰는 순간 이 함수는
    *"총함수"* 라고 선언해 놓고 클라이언트 문자 하나에 500 을 내는 함수가 된다 — 직전
    웨이브가 bcrypt NUL 바이트에서 정확히 같은 형태를 겪었다(2026-08-22 봉인이 발견).

    ``replace`` 가 아니라 ``surrogatepass`` 인 이유: ``replace`` 는 서로 다른 입력을 같은
    다이제스트로 접어 스프레이 탐지의 *서로 다른 계정 수*를 낮춰 셈한다 — 관측을 약하게
    만드는 방향이다. ``surrogatepass`` 는 무손실이라 결정론과 구별성이 함께 남는다.
    """
    key = str(secret or '').encode('utf-8', 'surrogatepass')
    raw = str(value or '').strip().lower().encode('utf-8', 'surrogatepass')
    return hmac.new(key, raw, hashlib.sha256).hexdigest()[:32]
