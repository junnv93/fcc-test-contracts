"""Identity key policy shared by API auth and central RBAC.

⚠️ **This module is in the ``fcc-test-contracts`` lane, which is declared
dependency-free** (``docs/api/headless_contract_extraction_manifest.v1.json``:
``fcc-test-contracts -> shared-kernel @ src: 0``). That is why the local-identity
value object lives HERE and not under ``src/domain/`` — an earlier draft put it in
``domain/models/user_identity.py`` and re-exported it, which staged a contracts box
that imported ``domain`` and could not stand up on its own. Contract M-1 asks for
the sentinel in exactly this module, so the lane boundary and the contract agree.

## 왜 nullable 이 아니라 센티넬인가 (계획서 D-1, 실 PostgreSQL 16.14 로 증명)

``users`` 의 유일 인덱스는 ``(issuer, subject)`` 이고 JIT upsert 가
``ON CONFLICT ("issuer","subject")`` 로 그것을 쓴다. 로컬 사용자를 위해 두 칸을
nullable 로 만드는 갈래가 있었고, **기각됐다** — PostgreSQL 에서 ``NULL`` 은 서로
distinct 이므로 유일 인덱스가 로컬 사용자에게 **아무것도 보장하지 않는다**::

    (a) nullable 신원키 -> rows=2      ← 같은 (NULL, NULL) 두 행이 나란히 산다
    (b) 센티넬 신원키   -> rows=1
        ERROR: duplicate key value violates unique constraint

즉 (a) 에서는 같은 이메일로 행이 무한히 생기고 **그 중 어느 행으로 로그인되는지가
정의되지 않는다**. 이것은 추론이 아니라 실측이고,
``tests/test_local_identity_live_postgres.py`` 가 그 실행을 봉인한다.

## 왜 ``subject`` 가 정규화된 이메일인가

EMS 의 신원 키가 ``email`` 이고 그 표는 ``lower(email)`` 유일 인덱스로 대소문자를
무시한다(EMS ``0075_normalize_email_lowercase_unique.sql``). 같은 규칙을 쓰면 나중에
EMS ``users`` 를 옮길 때 키 번역이 필요 없다.

⚠️ **정규화는 한 번만 하고 정규화된 값을 저장한다.** 저장은 원본, 조회는 정규화 —
이렇게 갈라두면 Python ``str.lower()`` 와 PostgreSQL ``lower()`` 의 로케일 차이가
그대로 결함이 된다. 정규화된 값을 저장하면 ``lower(email) == email == subject`` 가
**구성으로** 참이 되어 세 축이 갈라질 자리가 없다.
"""
from __future__ import annotations

from typing import Tuple


__all__ = [
    'EMAIL_MAX_LENGTH',
    'LEGACY_IDENTITY_ISSUER',
    'LOCAL_IDENTITY_ISSUER',
    'canonical_issuer',
    'is_local_issuer',
    'local_identity_key',
    'normalize_email',
]


# Stable non-OIDC issuer for trusted-header/local-dev principals and pre-migration
# rows. OIDC principals carry their real validated issuer URL instead.
#
# ⚠️ LEGACY and LOCAL are NOT the same sentinel and must never be merged.
# LEGACY means *"nobody established who this was"*; LOCAL means *"we minted this
# identity and hold its password hash"*. Merging them would put legacy rows on the
# local-login lookup path — they carry no password so no login would actually
# succeed, but the boundary itself would be gone, and the next change to that
# lookup would have nothing left to protect it.
LEGACY_IDENTITY_ISSUER = 'urn:fcc:identity:legacy'


#: 로컬(우리가 발급한) 신원의 ``users.issuer`` 센티넬.
#:
#: 형식은 형제 ``LEGACY_IDENTITY_ISSUER = 'urn:fcc:identity:legacy'`` 를 따른다. URN 인
#: 이유는 이 값이 ``users.issuer`` 라는 **OIDC issuer URL 을 담는 칸**에 들어가기 때문이다
#: — 실재하는 URL 과 절대 충돌하지 않는 네임스페이스여야 한다.
#:
LOCAL_IDENTITY_ISSUER = 'urn:fcc:identity:local'

#: ``users.email`` / EMS ``users.email`` 의 ``varchar(255)`` 상한.
EMAIL_MAX_LENGTH = 255


def normalize_email(value: object) -> str:
    """이메일의 정규 형태(소문자 + 앞뒤 공백 제거). 총함수 — raise 하지 않는다.

    총함수인 것이 계약이다. 이 함수는 로그인 본문에서 온 값을 받고, 호출자는 인증
    경로 한복판이라 예외를 500 으로 바꾼다. *"이메일이 아니다"* 는 오류가 아니라
    ``''`` 이고, 빈 문자열은 어떤 저장된 신원과도 일치하지 않는다.

    비-문자열은 ``''`` 로 접는다 — ``str(value)`` 로 강제하면 ``None`` 이
    ``'none'`` 이라는 **실재할 수 있는 로컬파트**가 된다.

    ⚠️ **UTF-8 로 인코딩할 수 없는 문자열도 ``''`` 로 접는다** (2026-08-22). 짝 없는
    surrogate(``'\\ud800'``)는 JSON 이스케이프로 **와이어에서 도달 가능**한데, 이 함수가
    그것을 그대로 통과시키면 값이 저장소까지 내려가 ``psycopg`` 의 파라미터 인코딩에서
    ``UnicodeEncodeError`` 로 터진다 — 실 PostgreSQL 16.14 로 확인했다. 그 예외는
    ``ValueError`` 라 플랫폼 경계가 잡아 **500** 으로 렌더하고, 그러면 로그인 응답이
    *"모든 실패는 구분 불가한 401"* 이라는 이 축의 핵심 불변식을 클라이언트 문자 하나로
    깨뜨린다(적대 평가 발견).

    ``''`` 는 이미 *"어떤 저장된 신원과도 일치하지 않는다"* 를 뜻하므로 로그인은 평소의
    401 경로로 빠지고, :func:`local_identity_key` 는 빈 이메일에 시끄럽게 raise 하므로
    그런 값으로 사용자를 만들 수도 없다. 즉 이 접기는 **거부를 옳은 자리로 옮길 뿐**
    새 동작을 만들지 않는다.
    """
    if not isinstance(value, str):
        return ''
    normalized = value.strip().lower()
    if not _is_storable_identity(normalized):
        return ''
    return normalized


#: Characters PostgreSQL `text` cannot hold, or that cannot be encoded at all.
#:
#: ⚠️ ``U+0000`` is perfectly UTF-8-encodable, so an encodability probe alone lets
#: it through — and psycopg then raises ``DataError`` (*"PostgreSQL text fields
#: cannot contain NUL (0x00) bytes"*), which is **not** a ``ValueError`` and so
#: does not even land in the same boundary branch as the surrogate case. Measured
#: end to end: ``{"email": "a\u0000b@x.com"}`` answered **503**, breaking the
#: uniform-401 invariant with one client-supplied character (adversarial review
#: round 2). The other C0 controls are refused with it — none of them can appear
#: in a real address, and enumerating only the one that was reported would leave
#: the next sibling to be found the same way.
_UNSTORABLE_CODEPOINTS = frozenset(chr(c) for c in range(0x20)) | {chr(0x7F)}


def _is_storable_identity(text: str) -> bool:
    """Can this string be encoded AND stored as a PostgreSQL text value?"""
    if any(ch in _UNSTORABLE_CODEPOINTS for ch in text):
        return False
    try:
        text.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def local_identity_key(email: object) -> Tuple[str, str]:
    """로컬 사용자의 ``(issuer, subject)`` 유일키.

    ⚠️ 빈 이메일에는 **raise 한다** — 여기서 총함수를 고르면 ``(local, '')`` 이라는
    *실재하는 행 키*가 만들어지고, 그 행은 아무 이메일도 없는 사용자가 되어 두 번째
    빈 이메일 등록을 유일 인덱스가 거부한다. 조용한 데이터 오염보다 시끄러운 거부다.
    호출자는 :func:`normalize_email` 로 먼저 검사한다 — 로그인 경로는 그 검사에서
    *"자격증명 불일치"* 로 빠지므로 이 예외에 도달하지 않는다.
    """
    normalized = normalize_email(email)
    if not normalized:
        raise ValueError(
            'local identity requires a non-empty email — an empty subject would '
            'become a real row key that no user can ever log in as'
        )
    if len(normalized) > EMAIL_MAX_LENGTH:
        raise ValueError(
            f'email exceeds {EMAIL_MAX_LENGTH} characters '
            f'(users.email is varchar({EMAIL_MAX_LENGTH}))'
        )
    return LOCAL_IDENTITY_ISSUER, normalized


def is_local_issuer(issuer: object) -> bool:
    """이 ``issuer`` 가 로컬 신원인가. 총함수.

    비밀번호 검증·변경처럼 **로컬 사용자에게만 의미가 있는** 연산이 OIDC 로 들어온
    principal 에 적용되지 않도록 거는 술어다.
    """
    return isinstance(issuer, str) and issuer == LOCAL_IDENTITY_ISSUER


def canonical_issuer(value: object) -> str:
    cleaned = '' if value is None else str(value).strip()
    return cleaned or LEGACY_IDENTITY_ISSUER
