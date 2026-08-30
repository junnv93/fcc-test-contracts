"""Shared HTTP authentication config for Session API + Headless API (F-2-D4).

Both web entrypoints carry the same auth fields with identical defaults — only
the environment-variable prefix differs (``FCC_SESSION_`` vs ``FCC_HEADLESS_``).
This module is the SSOT for the dataclass shape, env-var loader, and option
projection used by the composition roots and the principal-resolver factory.

dependency-free: no FastAPI / PySide6 / openpyxl / pandas / sqlalchemy imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from fcc_test_contracts.common.env_loaders import read_text


__all__ = [
    'AUTH_FIELD_NAMES',
    'AUTH_MODE_DISABLED',
    'AUTH_MODE_LOCAL_JWT',
    'AUTH_MODE_NONE',
    'AUTH_MODE_OIDC_JWT',
    'AUTH_MODE_TRUSTED_HEADERS',
    'SECRET_AUTH_FIELD_NAMES',
    'WEB_AUTH_STRATEGIES',
    'WEB_AUTH_STRATEGY_LOCAL',
    'LOCAL_DEV_HOSTNAMES',
    'WEB_AUTH_STRATEGY_NOT_APPLICABLE',
    'WEB_AUTH_STRATEGY_OIDC',
    'HttpAuthConfig',
    'auth_mode_pairing_defect',
    'deployment_auth_defects',
    'web_auth_strategy_for',
]


AUTH_MODE_DISABLED = 'disabled'
AUTH_MODE_NONE = 'none'
AUTH_MODE_TRUSTED_HEADERS = 'trusted_headers'
AUTH_MODE_OIDC_JWT = 'oidc_jwt'

#: 다섯 번째 모드 (신원 축 EMS 정합, 2026-08-21). platform-api 가 자기 키로 서명한
#: 토큰을 발행하고 같은 키로 검증한다 — 브라우저가 암호 연산을 하지 않으므로 평문
#: HTTP 에서도 로그인이 성립한다(``crypto.subtle`` 은 보안 컨텍스트 전용).
#:
#: ⚠️ ``oidc_jwt`` 를 **대체하지 않는다.** 나란히 두고, Azure 승인이 나면 그쪽으로 간다.
AUTH_MODE_LOCAL_JWT = 'local_jwt'


# ── SPA 로그인 전략과의 짝 (2026-08-22) ──────────────────────────────────────
#
# ⚠️ **백엔드 모드와 SPA 전략은 반드시 함께 바뀐다.** 백엔드만 바꾸면 화면이 여전히 IdP 로
# 튕기고, 프론트만 바꾸면 로그인 요청이 401 로 돌아온다. 그 규칙은 2026-08-22 까지 세 곳에
# **주석으로만** 있었고(compose · runtime-config 템플릿 · 런북) 강제하는 것은 없었다 —
# 이 저장소가 반복해서 이름 붙인 형태다: *아무것도 강제하지 않는 규칙은 건너뛸 수 있는
# 규칙이다.*
#
# ⚠️ 같은 파일(`docker-compose.central.yml`)이 같은 계열의 사고를 이미 기록하고 있다:
# `ALLOW_INSECURE_TRANSPORT` 를 compose 가 컨테이너로 넘기지 않아 운영자가 `central.env` 에
# 적은 값이 **아무 효과도 없었고**, 그 진단이 *"live deployment 에서 실제 시간을 잃었다"*.

#: SPA 가 아는 로그인 전략 토큰. 프론트 어휘이므로 백엔드 모드 이름과 **다르다** —
#: `apps/web/src/config/runtime.ts` 의 `z.enum([...])` 과 집합이 같아야 하고, 그 등가성은
#: cross-language 봉인이 확인한다(이 저장소는 그 패턴을 이미 OIDC 축에서 쓴다).
WEB_AUTH_STRATEGY_OIDC = 'oidc'
WEB_AUTH_STRATEGY_LOCAL = 'local'

#: SPA 로그인 화면이 **없는** 서버측 모드. 짝이 ``oidc`` 인 것이 아니라 *"이 배포는
#: SPA 로그인을 쓰지 않는다"* 이다.
#:
#: ⚠️ 첫 판은 이 셋을 ``oidc`` 로 적었고 그것은 **거짓이었다**(적대 평가 실측):
#: ``disabled``/``none`` 은 resolver 를 아예 만들지 않아 API 가 토큰을 **기대하지 않고**,
#: ``trusted_headers`` 는 ``X-FCC-Subject`` 로 키잉하는데 이 스택의 nginx 는 그 헤더를
#: 설정하지 않는다. 그런데 결함 메시지는 *"API 가 IdP 토큰을 기대하므로 401"* 이라고
#: 말하고 있었다. 기본값으로 접는 `if` 를 거부해 놓고 **표 안에 같은 기본값을 적은** 셈이다.
WEB_AUTH_STRATEGY_NOT_APPLICABLE = 'n/a'

#: SPA 가 아는 로그인 전략의 **전부**. ``runtime.ts`` 의 ``z.enum`` 과 집합 상등이어야 한다.
WEB_AUTH_STRATEGIES: frozenset = frozenset({
    WEB_AUTH_STRATEGY_OIDC, WEB_AUTH_STRATEGY_LOCAL,
})

#: 백엔드 모드 → SPA 전략. **전사(total)이고 명시적**이다.
#:
#: ⚠️ 기본값을 ``oidc`` 로 두고 ``local_jwt`` 만 특별 취급하는 ``if`` 한 줄이 아니라 표인
#: 이유: 여섯 번째 모드가 생기는 날 그 ``if`` 는 조용히 ``oidc`` 를 답하고 **아무것도 red 가
#: 되지 않는다**. 표는 키가 없으면 조회가 실패하므로, 새 모드는 여기에 답을 적어야 한다.
_WEB_AUTH_STRATEGY_BY_MODE: dict = {
    AUTH_MODE_LOCAL_JWT: WEB_AUTH_STRATEGY_LOCAL,
    AUTH_MODE_OIDC_JWT: WEB_AUTH_STRATEGY_OIDC,
    AUTH_MODE_TRUSTED_HEADERS: WEB_AUTH_STRATEGY_NOT_APPLICABLE,
    AUTH_MODE_DISABLED: WEB_AUTH_STRATEGY_NOT_APPLICABLE,
    AUTH_MODE_NONE: WEB_AUTH_STRATEGY_NOT_APPLICABLE,
}


def web_auth_strategy_for(auth_mode: object) -> 'str | None':
    """이 백엔드 모드와 짝인 SPA 전략, 또는 모드를 모르면 ``None``.

    총함수 — 어떤 입력에도 raise 하지 않는다. ``None`` 은 *"이 모드에는 선언된 짝이
    없다"* 이고, 호출자(봉인·사전점검)는 그것을 **결함**으로 읽어야 한다. 조용히
    ``oidc`` 로 접으면 이 함수가 존재할 이유가 사라진다.

    :data:`WEB_AUTH_STRATEGY_NOT_APPLICABLE` 은 *"이 배포에는 SPA 로그인 화면이 없다"* 이지
    ``oidc`` 의 동의어가 아니다.
    """
    return _WEB_AUTH_STRATEGY_BY_MODE.get(str(auth_mode or '').strip().lower())


def auth_mode_pairing_defect(auth_mode: object, web_auth_mode: object) -> 'str | None':
    """이 (백엔드 모드, SPA 전략) 쌍의 결함 설명, 또는 짝이 맞으면 ``None``.

    ⚠️ 증상을 **함께** 돌려준다. 이 쌍이 어긋났을 때 운영자가 보는 것은 설정 오류 메시지가
    아니라 *"로그인 화면이 자꾸 Keycloak 으로 튄다"* 또는 *"비밀번호가 맞는데 401"* 이고,
    그 증상에서 이 쌍으로 거슬러 올라가는 데 시간이 든다.
    """
    expected = web_auth_strategy_for(auth_mode)
    actual = str(web_auth_mode or '').strip().lower()
    if expected is None:
        return (
            f'auth_mode {auth_mode!r} has no declared SPA pairing — add it to '
            '_WEB_AUTH_STRATEGY_BY_MODE rather than letting it default'
        )
    if expected == WEB_AUTH_STRATEGY_NOT_APPLICABLE:
        # ⚠️ **결함이 아니다 — 제약이 없는 것이다.** 이 모드들은 토큰을 기대하지 않거나
        # (`disabled`/`none`) 이 스택이 설정하지 않는 헤더를 본다(`trusted_headers`).
        # 어느 `WEB_AUTH_MODE` 도 틀리지 않으므로 여기서 거절하면 **그 모드로는 게이트를
        # 통과할 방법이 아예 없어지고**, 통과할 수 없는 게이트는 꺼진다(이 저장소가
        # *"아무것도 강제하지 않는 규칙은 건너뛸 수 있는 규칙"* 으로 적은 것의 쌍둥이).
        #
        # ⚠️ 첫 판은 여기서 거절하면서 고치는 방법으로 `WEB_AUTH_MODE=n/a` 를 제시했다.
        # 그 값은 SPA 의 enum 에 없어서 런타임 설정 검증이 던지고 **화면이 통째로 안 뜬다** —
        # 진단하려던 것보다 나쁜 실패다(적대 평가 2라운드 H-4).
        return None
    if actual == expected:
        return None
    symptom = (
        'the SPA will redirect to the IdP while the API issues its own tokens'
        if expected == WEB_AUTH_STRATEGY_LOCAL
        else 'the SPA will show its own password form while the API expects an IdP token, '
             'so every login answers 401'
    )
    return (
        f'auth_mode {auth_mode!r} pairs with WEB_AUTH_MODE {expected!r}, '
        f'but {actual!r} is configured — {symptom}'
    )


# ── 배포 정합 (2026-08-22, 적대 평가가 짝 하나로는 부족함을 보였다) ──────────────
#
# ⚠️ **짝은 넷 중 하나였다.** 첫 판은 `(FCC_PLATFORM_AUTH_MODE, WEB_AUTH_MODE)` 만 보고
# 나머지 셋을 놓쳤고, 그 결과 런북 §S0-L 이 지시하는 **바로 그 설정**에 `exit 0` 을 냈다:
#
#   1. `FCC_HEADLESS_AUTH_MODE` — SPA 는 `/headless/*` 와 `/platform/*` 에 **같은 bearer**
#      를 붙인다. platform 만 local_jwt 로 바꾸면 headless 는 Keycloak 으로 검증하려
#      들고 모든 headless 화면이 401 이다.
#   2. `ALLOW_INSECURE_TRANSPORT` — SPA 의 런타임 스키마가 `oidc + insecure=true` 를
#      **거부**하고(그 조합은 crypto.subtle 부재로 로그인 자체가 불가), 평문 http
#      엔드포인트 + `insecure=false` 도 거부한다. 평문 배포는 `true` 여야 한다.
#   3. `local_jwt` 필수 값 — 모드만 바꾸고 시크릿·issuer·audience 가 컨테이너에 도달하지
#      않으면 부팅 거부다. 그 도달 여부는 compose 의 몫이라 이 함수가 볼 수 없고,
#      **봉인이 따로 본다**(`tests/test_auth_mode_pairing.py`).
#
# 이 함수는 1·2 와 짝을 함께 판정한다 — 셋을 따로 물으면 운영자가 하나만 고치고
# 다시 막힌다.

def deployment_auth_defects(
    *,
    platform_auth_mode: object,
    web_auth_mode: object,
    headless_auth_mode: object = None,
    local_jwt_secrets: object = None,
    insecure_transport_allowed: object = None,
    public_host: object = None,
) -> tuple:
    """이 배포 설정의 결함 **전부**. 정합이면 빈 튜플. 총함수.

    ``None`` 인 인자는 *"이 축은 묻지 않는다"* 이지 *"통과"* 가 아니다 — 호출자가 값을
    읽지 못했으면 판정 불가로 보고해야 하고, 그 구분은 호출자의 몫이다.
    """
    defects: list = []
    pairing = auth_mode_pairing_defect(platform_auth_mode, web_auth_mode)
    if pairing is not None:
        defects.append(pairing)

    if headless_auth_mode is not None:
        platform = str(platform_auth_mode or '').strip().lower()
        headless = str(headless_auth_mode or '').strip().lower()
        if headless != platform:
            defects.append(
                f'FCC_HEADLESS_AUTH_MODE {headless!r} differs from '
                f'FCC_PLATFORM_AUTH_MODE {platform!r} — the SPA attaches the SAME '
                'bearer to /headless and /platform, so one of the two surfaces will '
                'reject every request it receives'
            )

    if local_jwt_secrets is not None:
        platform_secret, headless_secret = local_jwt_secrets
        if str(platform_secret or '') != str(headless_secret or ''):
            defects.append(
                'FCC_HEADLESS_LOCAL_JWT_* differs from FCC_PLATFORM_LOCAL_JWT_* — the '
                'two surfaces must verify the SAME token, so a different secret, '
                'issuer or audience makes every /headless call fail token validation'
            )

    if insecure_transport_allowed is not None:
        insecure = _as_bool(insecure_transport_allowed)
        strategy = web_auth_strategy_for(platform_auth_mode)
        if strategy == WEB_AUTH_STRATEGY_OIDC and insecure:
            defects.append(
                'ALLOW_INSECURE_TRANSPORT=true with an OIDC login is refused by the '
                'SPA itself: OIDC needs crypto.subtle, which browsers expose only in '
                'a secure context, so login would be impossible rather than insecure'
            )
        if public_host is not None and not insecure and not _is_loopback(public_host):
            defects.append(
                f'PUBLIC_HOST {public_host!r} is not loopback and '
                'ALLOW_INSECURE_TRANSPORT is false, so the SPA will refuse to boot: '
                'its runtime schema requires https endpoints unless the flag is set'
            )
    return tuple(defects)


def _as_bool(value: object) -> bool:
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


#: 평문 http 를 허용하는 호스트 — **SPA 가 판정자다.**
#:
#: ⚠️ 첫 판은 이것을 WHATWG *potentially trustworthy* 로 적었고 그것은 **틀린 재판관**이다.
#: 실제 게이트는 ``apps/web/src/config/runtime.ts`` 의 ``isLocalDevHostname`` 이고, 그 집합은
#: WHATWG 와 양방향으로 다르다 — ``::1``·``127.0.0.5`` 는 WHATWG 가 신뢰하지만 SPA 는
#: 거부하고, ``hostmachine`` 은 그 반대다(적대 평가 2라운드 실측: 셋 다 예측이 뒤집혔다).
#: 규칙을 재표현하지 않고 **그쪽 집합을 그대로 적는다**; 등가성은 cross-language 봉인이 본다.
LOCAL_DEV_HOSTNAMES: frozenset = frozenset({'127.0.0.1', 'localhost', 'hostmachine'})


def _is_loopback(host: object) -> bool:
    """SPA 가 평문 엔드포인트를 허용하는 호스트인가."""
    return str(host or '').strip().lower() in LOCAL_DEV_HOSTNAMES


_LOWERCASE_FIELDS = frozenset({
    'auth_mode',
})

# Suffix in the env var (without prefix). Field order matches the dataclass.
_FIELD_TO_SUFFIX: tuple[tuple[str, str], ...] = (
    ('auth_mode', 'AUTH_MODE'),
    ('auth_subject_header', 'AUTH_SUBJECT_HEADER'),
    ('auth_permissions_header', 'AUTH_PERMISSIONS_HEADER'),
    ('oidc_issuer', 'OIDC_ISSUER'),
    ('oidc_audience', 'OIDC_AUDIENCE'),
    ('oidc_jwks_uri', 'OIDC_JWKS_URI'),
    ('oidc_subject_claim', 'OIDC_SUBJECT_CLAIM'),
    ('oidc_name_claim', 'OIDC_NAME_CLAIM'),
    ('oidc_email_claim', 'OIDC_EMAIL_CLAIM'),
    ('oidc_permissions_claim', 'OIDC_PERMISSIONS_CLAIM'),
    ('oidc_scope_claim', 'OIDC_SCOPE_CLAIM'),
    ('oidc_role_claim', 'OIDC_ROLE_CLAIM'),
    ('local_jwt_secret', 'LOCAL_JWT_SECRET'),
    ('local_jwt_issuer', 'LOCAL_JWT_ISSUER'),
    ('local_jwt_audience', 'LOCAL_JWT_AUDIENCE'),
    ('local_jwt_ttl_seconds', 'LOCAL_JWT_TTL_SECONDS'),
    ('local_jwt_refresh_ttl_seconds', 'LOCAL_JWT_REFRESH_TTL_SECONDS'),
)

AUTH_FIELD_NAMES: tuple[str, ...] = tuple(name for name, _ in _FIELD_TO_SUFFIX)

#: 진단·로그 투영에서 **반드시 제외**되는 필드.
#:
#: ⚠️ 손 목록이 아니라 :meth:`HttpAuthConfig.as_options` 가 소비하는 SSOT 다. 비밀을
#: 흘리지 않는 방법은 "적지 않기"가 아니라 "적을 수 없게 만들기"여야 한다 — 다음
#: 사람이 투영을 넓힐 때 이 집합이 그를 막는다. 봉인:
#: ``tests/test_auth_mode_local_jwt.py::TestTheSecretNeverEntersADiagnosticProjection``.
SECRET_AUTH_FIELD_NAMES: frozenset = frozenset({'local_jwt_secret'})


@dataclass(frozen=True)
class HttpAuthConfig:
    """Shared HTTP auth configuration embedded in Session/Headless runtime configs.

    Defaults are intentionally identical to the legacy flat fields they replaced
    so existing deployments keep working without env-var changes.
    """

    auth_mode: str = AUTH_MODE_DISABLED
    auth_subject_header: str = 'X-FCC-Subject'
    auth_permissions_header: str = 'X-FCC-Permissions'
    oidc_issuer: str = ''
    oidc_audience: str = ''
    oidc_jwks_uri: str = ''
    oidc_subject_claim: str = 'sub'
    oidc_name_claim: str = 'name'
    oidc_email_claim: str = 'email'
    oidc_permissions_claim: str = 'permissions'
    oidc_scope_claim: str = 'scope'
    oidc_role_claim: str = 'roles'
    # local_jwt (2026-08-21). Empty defaults so every existing deployment keeps
    # working without env changes — the fields are only READ in local_jwt mode,
    # and that mode refuses to start when they are unset (loud, at boot).
    #
    # ⚠️ TTLs are TEXT here because every field in this dataclass comes out of the
    # environment as text; ``local_identity.LocalJwtConfig`` is where they become
    # integers, and where a non-numeric value is refused. Parsing at the boundary
    # would put a second parser in the loader that the loader cannot report on.
    local_jwt_secret: str = ''
    local_jwt_issuer: str = ''
    local_jwt_audience: str = ''
    local_jwt_ttl_seconds: str = ''
    local_jwt_refresh_ttl_seconds: str = ''

    @classmethod
    def env_keys(cls, prefix: str) -> dict[str, str]:
        """Return ``{field_name: env_var_name}`` for the given namespace prefix.

        Example::

            HttpAuthConfig.env_keys('FCC_SESSION_')
            # → {'auth_mode': 'FCC_SESSION_AUTH_MODE', ...}
        """
        if not prefix:
            raise ValueError('env-var prefix must be non-empty (e.g. "FCC_SESSION_")')
        return {field: f'{prefix}{suffix}' for field, suffix in _FIELD_TO_SUFFIX}

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
        *,
        prefix: str,
    ) -> 'HttpAuthConfig':
        """Load all auth fields from environ using the given namespace prefix."""
        keys = cls.env_keys(prefix)
        defaults = cls.__dataclass_fields__
        kwargs: dict[str, str] = {}
        for field_name in AUTH_FIELD_NAMES:
            raw = read_text(environ, keys[field_name])
            if field_name in _LOWERCASE_FIELDS:
                raw = raw.lower()
            if not raw:
                raw = defaults[field_name].default
            kwargs[field_name] = raw
        return cls(**kwargs)

    def trusted_subject_header(self) -> str:
        """Header name a pre-auth component may key on, or ``''`` when none.

        ``auth_subject_header`` merely *names* the trusted-header carrier; it is
        only meaningful in ``trusted_headers`` mode, where a reverse proxy is
        responsible for setting it and stripping any client-supplied copy. In
        ``oidc_jwt`` / ``none`` / ``disabled`` mode the same header is plain
        attacker-controlled input, and :mod:`application.common.principal_resolver`
        ignores it accordingly.

        The inbound rate limiter runs before authentication and needs the same
        distinction; expressing it here keeps one owner of the rule instead of an
        ``auth_mode ==`` comparison copy-pasted into each composition root.
        """
        return (
            self.auth_subject_header
            if self.auth_mode == AUTH_MODE_TRUSTED_HEADERS
            else ''
        )

    def as_options(self) -> dict:
        """Stable projection used by the legacy ``auth_options()`` consumers.

        ⚠️ **This dict reaches logs and diagnostics.**

        The ``local_jwt_*`` fields are deliberately NOT projected here, and not
        only the secret one. This projection is pinned byte-for-byte by two
        existing tests and has zero production readers, so widening it would
        break the pins to add nothing — the local_jwt axis is diagnosed from the
        boot-time refusals in ``LocalJwtConfig.validate()``, which name the exact
        field that is wrong.

        The :data:`SECRET_AUTH_FIELD_NAMES` filter stays regardless. It is not
        guarding today's dict — today's dict has no secret in it — it is guarding
        the next person who widens this projection and does not stop to think
        about which of the fields they are adding is a credential.
        """
        projection = {
            'mode': self.auth_mode,
            'subject_header': self.auth_subject_header,
            'permissions_header': self.auth_permissions_header,
            'oidc_issuer': self.oidc_issuer,
            'oidc_audience': self.oidc_audience,
            'oidc_jwks_uri': self.oidc_jwks_uri,
        }
        return {
            key: value for key, value in projection.items()
            if key not in SECRET_AUTH_FIELD_NAMES
        }
