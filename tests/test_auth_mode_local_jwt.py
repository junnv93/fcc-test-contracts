"""다섯 번째 auth mode (``local_jwt``) — 위조 토큰 거부 봉인 (계약 M-3, T-3).

⚠️ **판정은 실행이다.** 계약 M-3 이 명시한다: *"소스에 ``algorithms=['HS256']`` 이 적혀
있다는 확인은 증거가 아니다(철자를 묻는 봉인)."* 그래서 이 파일은 축마다 **실제 토큰을
만들어 먹인다**.

인증은 보안 표면이고, 여기서 통과해서는 안 되는 것이 통과하면 그것은 *"남의 신원을
얻는 경로"* 다. 그러므로 아래 각 테스트는 "거부되는가"가 아니라 **"이 위조로 남이 될 수
있는가"** 를 묻는 형태로 읽어야 한다.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_REPO_ROOT / 'src'), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fcc_test_contracts.common.auth_config import (  # noqa: E402
    AUTH_MODE_DISABLED,
    AUTH_MODE_LOCAL_JWT,
    AUTH_MODE_NONE,
    AUTH_MODE_OIDC_JWT,
    AUTH_MODE_TRUSTED_HEADERS,
    AUTH_FIELD_NAMES,
    SECRET_AUTH_FIELD_NAMES,
    HttpAuthConfig,
)
from fcc_test_contracts.common.local_identity import (  # noqa: E402
    CLAIM_FORCE_PASSWORD_CHANGE,
    CLAIM_PERMISSIONS,
    CLAIM_SESSION_VERSION,
    CLAIM_TOKEN_TYPE,
    LOCAL_JWT_ALGORITHM,
    LOCAL_JWT_MIN_SECRET_BYTES,
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_REFRESH,
    LocalJwtConfig,
    LocalTokenError,
    issue_token,
    verify_token,
)
from fcc_test_contracts.common.principal_resolver import (  # noqa: E402
    LocalJwtPrincipalResolver,
    build_local_jwt_config,
    create_principal_resolver,
)
from fcc_test_contracts.common.identity import LOCAL_IDENTITY_ISSUER  # noqa: E402

import jwt as pyjwt  # noqa: E402


_SECRET = 's' * LOCAL_JWT_MIN_SECRET_BYTES
_OTHER_SECRET = 'x' * LOCAL_JWT_MIN_SECRET_BYTES
_ISSUER = 'https://fcc-platform.internal/auth'
_AUDIENCE = 'fcc-platform-web'
#: ⚠️ **실제 시계에 앵커한다.** 고정 상수(예: 1_700_000_000)를 쓰면 그 시각이 과거가
#: 되는 순간 모든 happy-path 픽스처가 PyJWT 의 ``exp`` 검사에 걸려 죽는다 — 그리고 그때
#: 거부 테스트들은 **여전히 통과**하므로(다른 이유로 거부되니까) 봉인이 조용히 공허해진다.
#: 발행 시각만 실제 시계에서 오고, 만료 경계 시험은 ``verify_token(now=...)`` 주입이 한다.
_NOW = int(time.time())


def _config(**overrides) -> LocalJwtConfig:
    base = dict(
        secret=_SECRET, issuer=_ISSUER, audience=_AUDIENCE,
        access_ttl_seconds=900, refresh_ttl_seconds=604800,
    )
    base.update(overrides)
    return LocalJwtConfig(**base)


def _access(config: LocalJwtConfig | None = None, **overrides) -> str:
    kwargs = dict(
        subject='tester@x.com', token_type=TOKEN_TYPE_ACCESS, issued_at=_NOW,
        permissions=['platform:read'], display_name='Tester',
        email='tester@x.com', session_version=1,
    )
    kwargs.update(overrides)
    return issue_token(config or _config(), **kwargs)


class _Request:
    def __init__(self, token: str | None = None, header: str | None = None) -> None:
        if header is not None:
            self.headers = {'authorization': header}
        elif token is not None:
            self.headers = {'authorization': f'Bearer {token}'}
        else:
            self.headers = {}


class TestTheHappyPathActuallyWorks(unittest.TestCase):
    """⚠️ 거부 테스트만 있으면 *전부 거부하는* 구현이 만점을 받는다."""

    def test_a_freshly_issued_token_resolves_to_its_subject(self):
        resolver = LocalJwtPrincipalResolver(_config())
        principal = resolver.resolve(_Request(_access()))
        self.assertEqual(principal.subject, 'tester@x.com')
        self.assertIn('platform:read', principal.permissions)
        self.assertEqual(principal.display_name, 'Tester')
        self.assertEqual(principal.email, 'tester@x.com')

    def test_the_principal_carries_the_identity_issuer_not_the_token_issuer(self):
        """⚠️ 두 축의 혼동이 이 모드의 가장 조용한 결함이다.

        ``config.issuer`` 를 principal 에 실으면 운영자가 ``LOCAL_JWT_ISSUER`` 를 바꾸는
        순간 모든 principal 이 자기 ``users`` 행에서 분리된다 — 로그인은 계속 되고
        권한과 멤버십만 조용히 사라진다.
        """
        principal = LocalJwtPrincipalResolver(_config()).resolve(_Request(_access()))
        self.assertEqual(principal.issuer, LOCAL_IDENTITY_ISSUER)
        self.assertNotEqual(principal.issuer, _ISSUER)

    def test_no_token_is_anonymous_not_an_error(self):
        """``public`` operation(로그인 자체)이 토큰 없이 도달할 수 있어야 한다."""
        principal = LocalJwtPrincipalResolver(_config()).resolve(_Request())
        self.assertEqual(principal.subject, 'anonymous')
        self.assertEqual(principal.permissions, frozenset())

    def test_a_non_bearer_authorization_header_is_anonymous(self):
        principal = LocalJwtPrincipalResolver(_config()).resolve(
            _Request(header='Basic dXNlcjpwYXNz'),
        )
        self.assertEqual(principal.subject, 'anonymous')


class TestForgedTokensAreRefused(unittest.TestCase):
    """계약 M-3 의 일곱 축 — 각각 **실제 토큰을 만들어** 먹인다."""

    def setUp(self) -> None:
        self.resolver = LocalJwtPrincipalResolver(_config())

    def _refused(self, token: str, axis: str) -> None:
        with self.assertRaises(
            PermissionError,
            msg=f'{axis}: this forgery was ACCEPTED — it grants someone else\'s identity',
        ):
            self.resolver.resolve(_Request(token))

    def test_unsigned_token_is_refused(self):
        payload = pyjwt.decode(
            _access(), _SECRET, algorithms=[LOCAL_JWT_ALGORITHM],
            audience=_AUDIENCE, issuer=_ISSUER,
        )
        unsigned = pyjwt.encode(payload, key='', algorithm='none')
        self._refused(unsigned, 'alg:none / unsigned')

    def test_token_signed_with_another_key_is_refused(self):
        self._refused(
            _access(_config(secret=_OTHER_SECRET)), 'signed with a different key',
        )

    def test_expired_token_is_refused(self):
        stale = _access(issued_at=_NOW - 100_000)
        # 발급 시점 기준으로는 유효했다 — 지금 기준으로만 만료다.
        self.assertIsNotNone(stale)
        self._refused(stale, 'expired')

    def test_audience_mismatch_is_refused(self):
        other = _access(_config(audience='some-other-app'))
        self._refused(other, 'audience mismatch')

    def test_issuer_mismatch_is_refused(self):
        other = _access(_config(issuer='https://evil.example/auth'))
        self._refused(other, 'issuer mismatch')

    def test_tampered_payload_is_refused(self):
        """서명 대상 바이트가 바뀌면 서명이 맞지 않는다 — 권한 상승 시도의 기본형."""
        token = _access()
        header, payload, signature = token.split('.')
        forged_payload = pyjwt.api_jws.base64url_encode(
            b'{"iss":"' + _ISSUER.encode() + b'","aud":"' + _AUDIENCE.encode()
            + b'","sub":"admin@x.com","permissions":["platform:admin"],'
            b'"typ":"access","iat":1700000000,"exp":9999999999,"jti":"x","sv":1}'
        ).decode()
        self._refused(f'{header}.{forged_payload}.{signature}', 'tampered payload')

    def test_a_refresh_token_cannot_authorise_a_request(self):
        """⚠️ 서명·issuer·audience 가 **전부 유효**하다. ``typ`` 만이 이것을 막는다.

        막지 못하면 7일짜리 자격증명이 15분짜리 자리에 앉아, 짧은 액세스 수명이라는
        설계 전체가 무의미해진다.
        """
        refresh = issue_token(
            _config(), subject='tester@x.com', token_type=TOKEN_TYPE_REFRESH,
            issued_at=_NOW,
        )
        # 같은 토큰이 리프레시 자리에서는 유효하다 — 즉 거부의 원인이 서명이 아니다.
        self.assertEqual(
            verify_token(_config(), refresh, expected_type=TOKEN_TYPE_REFRESH)['sub'],
            'tester@x.com',
        )
        self._refused(refresh, 'refresh token used as access token')

    def test_garbage_and_empty_inputs_are_refused(self):
        for value in ('', '   ', 'not-a-jwt', 'a.b.c', None, 123, []):
            with self.subTest(value=repr(value)):
                with self.assertRaises(LocalTokenError):
                    verify_token(_config(), value, expected_type=TOKEN_TYPE_ACCESS)


class TestRequiredClaimsAreEnforced(unittest.TestCase):
    """검증되지 않는 클레임은 없는 것과 같다 — ``exp`` 없는 토큰은 영원히 유효하다."""

    def _hand_rolled(self, payload: dict) -> str:
        return pyjwt.encode(payload, _SECRET, algorithm=LOCAL_JWT_ALGORITHM)

    def _full_payload(self) -> dict:
        return {
            'iss': _ISSUER, 'aud': _AUDIENCE, 'sub': 'tester@x.com',
            'iat': _NOW, 'exp': _NOW + 900, 'jti': 'token-1',
            CLAIM_TOKEN_TYPE: TOKEN_TYPE_ACCESS, CLAIM_SESSION_VERSION: 1,
            CLAIM_FORCE_PASSWORD_CHANGE: False, CLAIM_PERMISSIONS: [],
        }

    def test_the_hand_rolled_baseline_is_accepted(self):
        """⚠️ 이것이 없으면 아래 결측 테스트들이 **다른 이유로** 통과할 수 있다."""
        claims = verify_token(
            _config(), self._hand_rolled(self._full_payload()),
            expected_type=TOKEN_TYPE_ACCESS,
        )
        self.assertEqual(claims['sub'], 'tester@x.com')

    def test_each_required_claim_is_individually_required(self):
        for claim in ('exp', 'iat', 'iss', 'aud', 'sub', 'jti', CLAIM_TOKEN_TYPE):
            with self.subTest(missing=claim):
                payload = self._full_payload()
                payload.pop(claim)
                with self.assertRaises(
                    LocalTokenError,
                    msg=f'a token with no {claim!r} claim was accepted',
                ):
                    verify_token(
                        _config(), self._hand_rolled(payload),
                        expected_type=TOKEN_TYPE_ACCESS,
                    )

    def test_an_empty_subject_is_refused(self):
        payload = self._full_payload()
        payload['sub'] = '   '
        with self.assertRaises(LocalTokenError):
            verify_token(
                _config(), self._hand_rolled(payload), expected_type=TOKEN_TYPE_ACCESS,
            )


class TestExpiryBoundaryIsInjectable(unittest.TestCase):
    """만료 경계를 sleep 없이 결정론적으로 시험한다."""

    def test_one_second_before_expiry_is_valid(self):
        token = _access()
        claims = verify_token(
            _config(), token, expected_type=TOKEN_TYPE_ACCESS, now=_NOW + 899,
        )
        self.assertEqual(claims['sub'], 'tester@x.com')

    def test_at_expiry_is_refused(self):
        token = _access()
        with self.assertRaises(LocalTokenError):
            verify_token(
                _config(), token, expected_type=TOKEN_TYPE_ACCESS, now=_NOW + 900,
            )

    def test_refresh_lives_longer_than_access(self):
        config = _config()
        self.assertGreater(config.refresh_ttl_seconds, config.access_ttl_seconds)


class TestConfigIsRefusedAtBootNotSilently(unittest.TestCase):
    """설정 결함은 **증상이 없다** — 부팅에서 거부하지 않으면 아무도 알아채지 못한다."""

    def _auth(self, **overrides) -> HttpAuthConfig:
        base = dict(
            auth_mode=AUTH_MODE_LOCAL_JWT, local_jwt_secret=_SECRET,
            local_jwt_issuer=_ISSUER, local_jwt_audience=_AUDIENCE,
        )
        base.update(overrides)
        return HttpAuthConfig(**base)

    def test_a_valid_config_builds(self):
        resolver = create_principal_resolver(self._auth())
        self.assertIsInstance(resolver, LocalJwtPrincipalResolver)

    def test_a_short_secret_is_refused(self):
        """RFC 7518 §3.2 — HS256 키는 해시 출력 길이(256비트) 이상이어야 한다."""
        short = 's' * (LOCAL_JWT_MIN_SECRET_BYTES - 1)
        with self.assertRaises(ValueError) as caught:
            create_principal_resolver(self._auth(local_jwt_secret=short))
        self.assertIn('local_jwt_secret', str(caught.exception))

    def test_a_multibyte_secret_is_measured_in_bytes_not_characters(self):
        """⚠️ 31자 한글은 93바이트라 **충분하다**. 문자로 세면 거부된다."""
        hangul = '가' * 31
        self.assertGreaterEqual(
            len(hangul.encode('utf-8')), LOCAL_JWT_MIN_SECRET_BYTES,
        )
        self.assertIsInstance(
            create_principal_resolver(self._auth(local_jwt_secret=hangul)),
            LocalJwtPrincipalResolver,
        )

    def test_missing_issuer_or_audience_is_refused(self):
        for field in ('local_jwt_issuer', 'local_jwt_audience'):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    create_principal_resolver(self._auth(**{field: ''}))

    def test_an_unparseable_ttl_is_refused_rather_than_defaulted(self):
        """⚠️ ``15m`` 을 기본값 900 으로 접으면 우연히 맞고 그 다음엔 틀린다."""
        with self.assertRaises(ValueError):
            create_principal_resolver(self._auth(local_jwt_ttl_seconds='15m'))

    def test_a_non_positive_ttl_is_refused(self):
        for value in ('0', '-1'):
            with self.subTest(ttl=value):
                with self.assertRaises(ValueError):
                    create_principal_resolver(self._auth(local_jwt_ttl_seconds=value))

    def test_an_empty_ttl_takes_the_default(self):
        config = build_local_jwt_config(self._auth(local_jwt_ttl_seconds=''))
        self.assertEqual(config.access_ttl_seconds, 900)


class TestTheOtherFourModesAreUnchanged(unittest.TestCase):
    """계약 M-2 — 이 모드는 **더해지는** 것이지 기존 모드를 바꾸지 않는다."""

    def test_the_mode_token_is_new_and_distinct(self):
        existing = {
            AUTH_MODE_DISABLED, AUTH_MODE_NONE, AUTH_MODE_TRUSTED_HEADERS,
            AUTH_MODE_OIDC_JWT,
        }
        self.assertNotIn(AUTH_MODE_LOCAL_JWT, existing)
        self.assertEqual(len(existing | {AUTH_MODE_LOCAL_JWT}), 5)

    def test_disabled_and_none_still_return_no_resolver(self):
        for mode in ('', AUTH_MODE_DISABLED, AUTH_MODE_NONE):
            with self.subTest(mode=mode):
                self.assertIsNone(
                    create_principal_resolver(HttpAuthConfig(auth_mode=mode)),
                )

    def test_trusted_headers_still_resolves_from_headers(self):
        resolver = create_principal_resolver(
            HttpAuthConfig(auth_mode=AUTH_MODE_TRUSTED_HEADERS),
        )
        principal = resolver.resolve(
            type('R', (), {'headers': {
                'X-FCC-Subject': 'ops', 'X-FCC-Permissions': 'platform:read',
            }})(),
        )
        self.assertEqual(principal.subject, 'ops')
        self.assertIn('platform:read', principal.permissions)

    def test_oidc_still_refuses_incomplete_config(self):
        with self.assertRaises(ValueError):
            create_principal_resolver(HttpAuthConfig(auth_mode=AUTH_MODE_OIDC_JWT))

    def test_an_unknown_mode_is_still_refused(self):
        with self.assertRaises(ValueError):
            create_principal_resolver(HttpAuthConfig(auth_mode='sso_magic'))

    def test_local_jwt_fields_load_from_the_environment(self):
        """``AUTH_FIELD_NAMES`` 가 ``_FIELD_TO_SUFFIX`` 에서 파생되므로 자동 반영된다."""
        env = {
            'FCC_PLATFORM_AUTH_MODE': AUTH_MODE_LOCAL_JWT,
            'FCC_PLATFORM_LOCAL_JWT_SECRET': _SECRET,
            'FCC_PLATFORM_LOCAL_JWT_ISSUER': _ISSUER,
            'FCC_PLATFORM_LOCAL_JWT_AUDIENCE': _AUDIENCE,
            'FCC_PLATFORM_LOCAL_JWT_TTL_SECONDS': '600',
        }
        loaded = HttpAuthConfig.from_env(env, prefix='FCC_PLATFORM_')
        self.assertEqual(loaded.auth_mode, AUTH_MODE_LOCAL_JWT)
        self.assertEqual(loaded.local_jwt_secret, _SECRET)
        self.assertEqual(build_local_jwt_config(loaded).access_ttl_seconds, 600)

    def test_every_declared_field_has_an_env_key(self):
        keys = HttpAuthConfig.env_keys('FCC_PLATFORM_')
        self.assertEqual(set(keys), set(AUTH_FIELD_NAMES))


class TestTheSecretNeverEntersADiagnosticProjection(unittest.TestCase):
    """``as_options()`` 는 로그로 나간다."""

    def test_the_secret_is_absent_from_as_options(self):
        options = HttpAuthConfig(
            auth_mode=AUTH_MODE_LOCAL_JWT, local_jwt_secret=_SECRET,
            local_jwt_issuer=_ISSUER, local_jwt_audience=_AUDIENCE,
        ).as_options()
        self.assertNotIn('local_jwt_secret', options)
        self.assertNotIn(
            _SECRET, repr(options),
            'the signing secret appears in a projection that reaches logs',
        )

    def test_the_legacy_projection_shape_is_unchanged(self):
        """⚠️ 음성 단언만 있으면 **투영을 통째로 비운** 구현이 만점을 받는다.

        그리고 이것이 계약 M-2 이기도 하다 — 이 축은 기존 투영을 넓히지도 좁히지도
        않는다(넓히면 두 pin 테스트가 깨지고, 그 대가로 얻는 것이 없다).
        """
        options = HttpAuthConfig(
            auth_mode=AUTH_MODE_LOCAL_JWT, local_jwt_secret=_SECRET,
            local_jwt_issuer=_ISSUER, local_jwt_audience=_AUDIENCE,
        ).as_options()
        self.assertEqual(
            set(options),
            {
                'mode', 'subject_header', 'permissions_header',
                'oidc_issuer', 'oidc_audience', 'oidc_jwks_uri',
            },
        )

    def test_as_options_drops_a_field_declared_secret(self):
        """필터가 **``as_options`` 안에서** 살아 있는지 실행으로 확인한다.

        ⚠️ 이전 판은 테스트 본문에서 컴프리헨션을 **재구현**하고 자기 dict 를 단언했다 —
        ``as_options`` 를 통째로 지워도 통과하는 테스트였다(적대 평가 R2). 판정은
        프로덕션 함수를 통과해야 한다.

        오늘의 투영에 비밀 필드가 없으므로, 기존 키 하나를 일시적으로 비밀로 선언해
        **그 필터가 실제로 그 키를 떨어뜨리는지** 본다. 필터를 지우면 red 다.
        """
        import fcc_test_contracts.common.auth_config as auth_config

        config = HttpAuthConfig(
            auth_mode=AUTH_MODE_LOCAL_JWT, local_jwt_secret=_SECRET,
            oidc_issuer='https://idp.example/realms/x',
        )
        self.assertEqual(config.as_options()['oidc_issuer'], config.oidc_issuer)

        original = auth_config.SECRET_AUTH_FIELD_NAMES
        auth_config.SECRET_AUTH_FIELD_NAMES = frozenset({'oidc_issuer'})
        try:
            filtered = config.as_options()
        finally:
            auth_config.SECRET_AUTH_FIELD_NAMES = original
        self.assertNotIn(
            'oidc_issuer', filtered,
            'as_options() does not consult SECRET_AUTH_FIELD_NAMES — the filter '
            'is dead code and a future widening of this projection can leak a '
            'declared secret',
        )

    def test_the_verifier_pins_exactly_one_algorithm(self):
        """⚠️ ``alg`` 허용 목록이 **하나**인지 직접 묻는다.

        적대 평가 R2: ``algorithms=['HS256', 'none']`` 으로 넓혀도 위조 테스트가 전부
        통과했다 — PyJWT 가 키를 받은 경우 ``alg=none`` 을 자체적으로 거부하기 때문이다.
        즉 그 축을 지키고 있던 것은 **우리 코드가 아니라 라이브러리**였고, 목록을 넓히는
        변경은 아무 게이트도 건드리지 않았다. ``HS512`` 를 더하는 변이도 마찬가지로
        살아남는다 — 그쪽은 라이브러리가 막아 주지도 않는다.
        """
        import fcc_test_contracts.common.local_identity as local_identity

        source = Path(local_identity.__file__).read_text(encoding='utf-8')
        self.assertIn("'algorithms': [LOCAL_JWT_ALGORITHM]", source)
        self.assertEqual(LOCAL_JWT_ALGORITHM, 'HS256')
        # 그리고 그 상수가 실제로 발행·검증 **양쪽**에 쓰인다 — 목록을 손으로
        # 넓히려면 두 사이트를 모두 지나야 한다.
        self.assertIn("algorithm=LOCAL_JWT_ALGORITHM", source)     # issue_token
        self.assertIn("[LOCAL_JWT_ALGORITHM]", source)             # verify_token
        # ⚠️ 리터럴 알고리즘 이름이 상수 선언 밖에 나타나면 안 된다 — 그것이 목록을
        # 넓히는 가장 쉬운 방법이다.
        body = source.split("LOCAL_JWT_ALGORITHM = ", 1)[1].split("\n", 1)[1]
        for forbidden in ("'none'", "'HS512'", "'RS256'", "'HS384'"):
            with self.subTest(algorithm=forbidden):
                self.assertNotIn(forbidden, body)

    def test_the_filter_is_derived_not_remembered(self):
        """비밀 목록에 필드를 더하면 투영에서 **자동으로** 빠진다."""
        self.assertIn('local_jwt_secret', SECRET_AUTH_FIELD_NAMES)
        for name in SECRET_AUTH_FIELD_NAMES:
            with self.subTest(field=name):
                self.assertIn(
                    name, AUTH_FIELD_NAMES,
                    f'{name} is declared secret but is not an auth field at all',
                )


if __name__ == '__main__':
    unittest.main()
