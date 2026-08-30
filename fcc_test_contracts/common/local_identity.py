"""Local (self-issued) JWT — the fifth auth mode's token format.

platform-api 가 **자기 키로 서명한** 토큰을 발행하고 같은 키로 검증한다. Keycloak 을
버리는 것이 아니라 나란히 둔다(``oidc_jwt`` 는 그대로 남는다) — Azure 승인이 나면
그쪽으로 간다.

## 왜 로컬 로그인이 필요한가

``apps/web/src/auth/oidc-pkce.ts`` 는 PKCE ``code_challenge`` 를 만들려고
``crypto.subtle.digest`` 를 부르는데, **``crypto.subtle`` 은 보안 컨텍스트에서만
정의된다** — ``https://`` 이거나 ``localhost`` 일 때뿐이다. 중앙 PC 는
``http://10.206.34.233:8080`` 이므로 그 API 가 ``undefined`` 이고 로그인은 **원리적으로**
불가능하다. 설정으로 풀 수 있는 문제가 아니다.

EMS 는 같은 사내망에서 평문 HTTP 로 돈다. 그 이유는 우연이 아니라 설계의 직접 귀결이다
— 비밀번호를 폼으로 POST 하고 **백엔드가** JWT 를 발행하므로 브라우저가 해싱할 일이
없고, 따라서 보안 컨텍스트를 요구하지 않는다.

⚠️ **그리고 평문 HTTP 는 안전해서 되는 것이 아니다.** 브라우저가 막지 않을 뿐이고
토큰과 비밀번호는 LAN 에 평문으로 흐른다. 이 모듈은 그 사실을 없애지 않는다 —
**TLS 가 유일한 근본 해결이고 이 축이 그것을 대체하지 않는다**(장부 등재).

## 왜 HS256 인가 (계획서 D-2)

발행자와 검증자가 **같은 프로세스**다. 비대칭이 사줄 것(공개키로 제3자가 검증)이 없고
키 배포 표면만 늘어난다. EMS 도 HS256 이다.

⚠️ **그 판단이 뒤집히는 조건을 적어 둔다**: 세션 노드가 같은 토큰을 검증해야 하는 날.
오늘은 노드가 자기 챔버 토큰(``chamber_token_provider.py``)을 따로 쓰므로 대상이 아니다.
그날이 오면 대칭키를 노드마다 배포해야 하고, 그 순간 **노드 한 대의 유출이 토큰 위조
권한**이 된다 — 그때는 RS256 으로 간다.

## ⚠️ ``iss`` 클레임과 ``users.issuer`` 는 **다른 축**이다

OIDC 에서는 둘이 같은 문자열이라 구분할 이유가 없었다. 로컬에서는 다르다:

* ``iss`` (이 모듈) — *"이 **토큰**을 누가 서명했나"*. 배포 설정값.
* ``users.issuer`` (:data:`application.common.identity.LOCAL_IDENTITY_ISSUER`) —
  *"이 **신원**을 누가 발급했나"*. 행의 유일키 절반.

합치면 운영자가 ``LOCAL_JWT_ISSUER`` 를 바꾸는 순간 **신원 조회가 통째로 빗나간다**
(로그인은 되는데 그 사용자의 권한·멤버십이 사라진다). 그래서 principal 의 issuer 는
설정값이 아니라 상수에서 온다 — ``principal_resolver`` 참조.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional


__all__ = [
    'DEFAULT_LOCAL_JWT_ACCESS_TTL_SECONDS',
    'DEFAULT_LOCAL_JWT_REFRESH_TTL_SECONDS',
    'LOCAL_JWT_ALGORITHM',
    'LOCAL_JWT_MIN_SECRET_BYTES',
    'TOKEN_TYPE_ACCESS',
    'TOKEN_TYPE_REFRESH',
    'LocalJwtConfig',
    'LocalTokenError',
    'issue_token',
    'new_token_id',
    'verify_token',
]


#: ⚠️ **한 알고리즘만.** ``jwt.decode`` 에 ``algorithms`` 를 넘기지 않거나 목록을
#: 넓히면 공격자가 헤더의 ``alg`` 를 골라 검증을 우회할 수 있다 — ``alg: none`` 이
#: 그 계열의 교과서적 예시이고, ``HS256`` 검증기에 ``RS256`` 공개키를 비밀키로
#: 먹이는 혼동 공격도 같은 뿌리다. 이 값은 발행과 검증 **양쪽**이 쓴다.
LOCAL_JWT_ALGORITHM = 'HS256'

#: HMAC-SHA256 키의 최소 길이(바이트). RFC 7518 §3.2: *"A key of the same size as the
#: hash output (for instance, 256 bits for "HS256") or larger MUST be used."*
#:
#: ⚠️ 이것이 **부팅 시** 거부되는 이유: 짧은 비밀키는 아무 증상도 만들지 않는다.
#: 로그인은 정상 동작하고 토큰도 정상 발급되며, 달라지는 것은 오프라인 무차별 대입의
#: 비용뿐이다. 즉 관측 가능한 실패가 영원히 없으므로 **시작할 때 거부하지 않으면
#: 아무도 알아채지 못한다**.
LOCAL_JWT_MIN_SECRET_BYTES = 32

#: 액세스 토큰 수명. EMS ``ACCESS_TOKEN_TTL_SECONDS`` 와 같은 15분.
#: 짧은 이유: 토큰은 발급 후 취소할 수 없다. 권한 변경·계정 비활성화가 반영되는 데
#: 걸리는 최대 시간이 곧 이 값이다.
DEFAULT_LOCAL_JWT_ACCESS_TTL_SECONDS = 900

#: 리프레시 토큰 수명. EMS ``REFRESH_TOKEN_TTL_SECONDS`` 와 같은 7일.
DEFAULT_LOCAL_JWT_REFRESH_TTL_SECONDS = 604800

#: ⚠️ 토큰 **종류**는 클레임이어야 한다. 없으면 리프레시 토큰이 액세스 토큰으로
#: 그대로 통한다 — 서명도 issuer 도 audience 도 전부 유효하기 때문이다. 그러면 7일짜리
#: 자격증명이 15분짜리 자리에 앉아 짧은 수명의 의미가 사라진다. EMS 가 같은 이유로
#: ``payload.type !== 'refresh'`` 를 검사한다.
TOKEN_TYPE_ACCESS = 'access'
TOKEN_TYPE_REFRESH = 'refresh'

#: 클레임 이름. 표준이 있는 것은 표준을 쓰고(``iss``/``aud``/``sub``/``exp``/``iat``/
#: ``jti``), 없는 것만 접두를 붙인다.
CLAIM_TOKEN_TYPE = 'typ'
CLAIM_SESSION_VERSION = 'sv'
CLAIM_FORCE_PASSWORD_CHANGE = 'fpc'
CLAIM_PERMISSIONS = 'permissions'
CLAIM_NAME = 'name'
CLAIM_EMAIL = 'email'

#: 검증에서 **존재를 강제**하는 클레임. 없는 클레임은 검증되지 않고, 검증되지 않는
#: 클레임은 없는 것과 같다 — ``exp`` 가 빠진 토큰은 영원히 유효하다.
_REQUIRED_CLAIMS = ('exp', 'iat', 'iss', 'aud', 'sub', 'jti', CLAIM_TOKEN_TYPE)


class LocalTokenError(PermissionError):
    """토큰이 유효하지 않다.

    ``PermissionError`` 를 상속하는 것이 배선이다 — platform 라우트 경계의
    ``_PLATFORM_ERROR_CODE_TABLE`` 이 이미 ``PermissionError`` 를 ``FORBIDDEN`` 으로
    매핑하므로, 새 예외가 **매핑 표와 ``except`` 튜플 양쪽에 등재되지 않아 500 으로
    새는** 이 저장소의 알려진 실패 모드에 걸리지 않는다.

    ⚠️ 메시지는 **무엇이 틀렸는지 말하지 않는다**. *"서명이 틀렸다"* 와 *"만료됐다"* 와
    *"이 audience 가 아니다"* 를 구분해 주면 공격자에게 위조 진행도를 알려주는 오라클이
    된다.
    """


@dataclass(frozen=True)
class LocalJwtConfig:
    """로컬 토큰의 발행/검증 파라미터.

    ⚠️ ``secret`` 은 절대 ``as_options()`` 류의 진단 투영에 실리지 않는다
    (``auth_config.HttpAuthConfig.as_options`` 참조 — 그 dict 는 로그로 나간다).
    """

    secret: str
    issuer: str
    audience: str
    access_ttl_seconds: int = DEFAULT_LOCAL_JWT_ACCESS_TTL_SECONDS
    refresh_ttl_seconds: int = DEFAULT_LOCAL_JWT_REFRESH_TTL_SECONDS

    def validate(self) -> None:
        """부팅 시 한 번 — 조용한 약화보다 시끄러운 거부.

        모든 실패가 ``ValueError`` 인 것은 형제 ``oidc_jwt`` 분기와 같은 형태다
        (``create_principal_resolver`` 가 설정 누락에 ``ValueError`` 를 던진다).
        """
        if not self.issuer:
            raise ValueError('local_jwt auth requires local_jwt_issuer')
        if not self.audience:
            raise ValueError('local_jwt auth requires local_jwt_audience')
        secret_bytes = len((self.secret or '').encode('utf-8'))
        if secret_bytes < LOCAL_JWT_MIN_SECRET_BYTES:
            raise ValueError(
                'local_jwt auth requires local_jwt_secret of at least '
                f'{LOCAL_JWT_MIN_SECRET_BYTES} bytes (RFC 7518 section 3.2 — an '
                f'HS256 key must be at least as large as the hash output); got '
                f'{secret_bytes}. A short secret produces no symptom at all: '
                'login works, tokens verify, and only the offline brute-force '
                'cost changes — so it must be refused at boot or never.'
            )
        for name, ttl in (
            ('local_jwt_ttl_seconds', self.access_ttl_seconds),
            ('local_jwt_refresh_ttl_seconds', self.refresh_ttl_seconds),
        ):
            if not isinstance(ttl, int) or ttl <= 0:
                raise ValueError(f'{name} must be a positive integer, got {ttl!r}')


def new_token_id() -> str:
    """토큰의 ``jti``. 폐기 목록이 개별 토큰을 지목할 수 있는 유일한 손잡이다."""
    return str(uuid.uuid4())


def issue_token(
    config: LocalJwtConfig,
    *,
    subject: str,
    token_type: str,
    issued_at: int,
    token_id: Optional[str] = None,
    session_version: int = 0,
    permissions: Iterable[str] = (),
    display_name: str = '',
    email: str = '',
    force_password_change: bool = False,
) -> str:
    """서명된 토큰 하나.

    ``issued_at`` 은 **주입**이다 — 시계를 인자로 받으면 만료 경계를 실행으로 시험할
    수 있고, 모듈이 ``time.time()`` 을 부르면 그 테스트는 sleep 을 요구한다.
    """
    if token_type not in (TOKEN_TYPE_ACCESS, TOKEN_TYPE_REFRESH):
        raise ValueError(f'unknown local token type: {token_type!r}')
    ttl = (
        config.access_ttl_seconds if token_type == TOKEN_TYPE_ACCESS
        else config.refresh_ttl_seconds
    )
    payload: dict[str, Any] = {
        'iss': config.issuer,
        'aud': config.audience,
        'sub': subject,
        'iat': issued_at,
        'exp': issued_at + ttl,
        'jti': token_id or new_token_id(),
        CLAIM_TOKEN_TYPE: token_type,
        CLAIM_SESSION_VERSION: int(session_version or 0),
        CLAIM_FORCE_PASSWORD_CHANGE: bool(force_password_change),
    }
    # ⚠️ 리프레시 토큰은 권한·프로필을 **싣지 않는다**. 7일 동안 굳어 있을 값이고,
    # 리프레시는 어차피 DB 를 다시 읽어 새 액세스 토큰을 만든다. 실으면 그것은
    # 갱신되지 않는 권한 사본이 된다.
    if token_type == TOKEN_TYPE_ACCESS:
        payload[CLAIM_PERMISSIONS] = sorted({
            str(item).strip() for item in permissions if str(item).strip()
        })
        payload[CLAIM_NAME] = display_name or ''
        payload[CLAIM_EMAIL] = email or ''
    return _jwt().encode(payload, config.secret, algorithm=LOCAL_JWT_ALGORITHM)


def verify_token(
    config: LocalJwtConfig,
    token: object,
    *,
    expected_type: str,
    now: Optional[int] = None,
) -> Mapping[str, Any]:
    """검증된 클레임. 실패는 전부 :class:`LocalTokenError`.

    ⚠️ **``expected_type`` 은 선택 인자가 아니다.** 기본값을 주면 호출자가 빠뜨렸을
    때 조용히 아무 종류나 받아들이고, 그 순간 리프레시 토큰이 액세스 토큰으로 통한다.
    """
    if expected_type not in (TOKEN_TYPE_ACCESS, TOKEN_TYPE_REFRESH):
        raise ValueError(f'unknown local token type: {expected_type!r}')
    if not isinstance(token, str) or not token.strip():
        raise LocalTokenError('local token validation failed')
    jwt = _jwt()
    decode_kwargs: dict[str, Any] = {
        'key': config.secret,
        # ⚠️ 목록이 하나인 것이 요지다 — 위 LOCAL_JWT_ALGORITHM 주석 참조.
        'algorithms': [LOCAL_JWT_ALGORITHM],
        'audience': config.audience,
        'issuer': config.issuer,
        'options': {'require': list(_REQUIRED_CLAIMS)},
    }
    try:
        claims = jwt.decode(token, **decode_kwargs)
    except Exception as exc:  # noqa: BLE001 — 아래 docstring: 사유를 누설하지 않는다
        raise LocalTokenError('local token validation failed') from exc

    actual_type = str(claims.get(CLAIM_TOKEN_TYPE) or '')
    if actual_type != expected_type:
        raise LocalTokenError('local token validation failed')

    if now is not None:
        # 주입된 시계로 다시 한 번 — 테스트가 sleep 없이 만료 경계를 시험할 수 있고,
        # 프로덕션에서는 PyJWT 의 판정과 같은 답을 낸다(둘 다 exp 를 본다).
        expires_at = claims.get('exp')
        if not isinstance(expires_at, (int, float)) or now >= expires_at:
            raise LocalTokenError('local token validation failed')

    subject = str(claims.get('sub') or '').strip()
    if not subject:
        raise LocalTokenError('local token validation failed')
    return claims


def _jwt():
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - declared in requirements
        raise RuntimeError(
            'PyJWT[crypto] is required for local_jwt auth'
        ) from exc
    return jwt
