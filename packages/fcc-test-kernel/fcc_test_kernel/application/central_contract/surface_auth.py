"""중앙 플랫폼 계약 — 로컬 계정 인증 (login · refresh · me · change-password · logout · unlock).

``api_contracts`` facade 가 이 모듈의 표를 병합해 ``PLATFORM_API_*`` 로 재노출한다.
모듈 경계는 **표 종류가 아니라 operation 표면**이다 — git 이력 실측에서 계약 변경
커밋의 92%(52 중 48)가 정확히 한 표면만 만졌고, 표 종류로 자르면 엔드포인트 하나
추가가 항상 다섯 표를 동시에 만진다(네 표가 같은 operationId 키로 병렬 배열돼 있다).
"""
from __future__ import annotations

from fcc_test_kernel.application.central_contract.api_operation_factory import _operation

#: 이 모듈이 소유하는 route path prefix. 분할은 **선언이 아니라 판정 대상**이다 —
#: ``tests/test_central_contract_decomposition_axis.py`` 가 prefix 집합이 쌍마다
#: 서로소이고 ``PLATFORM_API_ROUTES`` 의 모든 경로를 덮는지, 그리고 각 operation 이
#: 자기 경로의 **최장 일치** prefix 를 소유한 모듈에 물리적으로 선언돼 있는지 파생
#: 판정한다. 새 엔드포인트가 어느 모듈로 가야 하는지 사람이 기억하지 않는다.
SURFACE_PREFIXES: tuple[str, ...] = (
    '/platform/auth',
)


# 이 표면의 operation 만 참조하는 에러 응답 조각. 둘 이상의 표면이 참조하게 되면
# ``api_operation_factory`` 로 올라가야 하고, 그 판정도 파생 검사가 한다.
# 멀티챔버 P5 — chamber measurement proxy error responses (SSOT).
_EXPIRED_OR_INVALID_TOKEN_401 = (
    'The presented access token is expired, malformed, revoked, or of the wrong '
    'type. 401 rather than 403 on purpose: 403 means "stop", 401 means '
    '"re-authenticate", and only the second tells a browser to attempt a silent '
    'refresh instead of showing an error page. Declaring it matters — this is the '
    'status a client is most likely to act on, and an undeclared status is one a '
    'generated client has no branch for.'
)

_INVALID_CREDENTIALS_401 = (
    'Authentication failed. Deliberately indistinguishable across four cases '
    '(no such user / wrong password / disabled account / locked account) — any '
    'refusal that could tell them apart would let an attacker enumerate the '
    'internal staff directory without a single correct password.'
)

_LOCAL_ACCOUNT_NOT_FOUND_404 = (
    'No local account for that email. ⚠️ Unlike the login surface — which folds '
    '"no such account" into "wrong password" so it cannot be used to enumerate '
    'users — this operation says so plainly. It is platform:admin gated, and an '
    'administrator who cannot tell a typo from a successful unlock will believe '
    'they helped while the tester is still locked out.'
)

_USER_ADMIN_SELF_TARGET_400 = (
    'An administrator may not disable their own account or revoke their own last '
    'system_admin role. Refused at the boundary rather than "allowed but '
    'discouraged": the failure mode is that NOBODY can administer the system, and '
    'it is not recoverable through the API — it needs a DB edit. The check is on '
    'the AUTHENTICATED subject, never on a body field, so it cannot be spoofed.'
)

_LAST_SYSTEM_ADMIN_409 = (
    'Refused: this would leave the platform with zero system_admin holders. A '
    'system with no administrator cannot issue accounts, reset passwords, or grant '
    'roles — the only exit is a DB edit. 409 rather than 400 because the request is '
    'well-formed; it is the CURRENT STATE that forbids it, and it will succeed once '
    'another holder exists.'
)

_USER_ALREADY_EXISTS_409 = (
    'A local account already exists for that email. Said plainly (unlike the login '
    'surface, which folds every failure together to prevent enumeration) because '
    'this operation is platform:admin gated and an administrator who cannot tell a '
    'duplicate from a failure will create a second account for the same person.'
)

_UNLOCK_MISSING_EMAIL_400 = (
    "The 'email' field is missing or blank. ⚠️ Declared separately from the 404 "
    'on purpose: the request field is named "email" while the response envelope '
    'calls the same value "subject", so an administrator who copies the shape of '
    'the reply sends the wrong key — and folding that into "no local account for '
    'that identifier" tells them the account does not exist when it does. That is '
    'the exact confusion the 404 description exists to prevent, arriving through '
    'the other door.'
)

_REFRESH_ROTATION_LIMITED_429 = (
    'Too many refresh rotations for this account in the current window. Sized from '
    'the measured envelope (concurrent sessions per tester x one retry each), which '
    'is ~29x the steady-state rate a normal client produces, so a client that hits '
    'it is looping rather than working. Carries Retry-After. The budget is per '
    'VERIFIED subject: a forged token naming someone else cannot spend their '
    'allowance, because the charge happens after signature, token-type and '
    'session_version have all been checked.'
)


ROUTES: dict[str, tuple[str, str]] = {
    'local_auth_login': ('POST', '/platform/auth/login'),
    'local_auth_refresh': ('POST', '/platform/auth/refresh'),
    'local_auth_me': ('GET', '/platform/auth/me'),
    'local_auth_change_password': ('POST', '/platform/auth/change-password'),
    'local_auth_logout': ('POST', '/platform/auth/logout'),
    # 식별자가 경로에 없는 이유는 ``UnlockLocalAccountRequest`` 가 소유한다(로그 PII).
    'unlock_local_account': ('POST', '/platform/auth/accounts/unlock'),
    # ── 사용자 관리 (2026-09-07, intent/global-roles-and-user-admin) ────────
    # 이 시스템이 계정을 «소유»한다: 중앙은 평문 HTTP 라 브라우저가 local_jwt 이고
    # (실측 2026-09-07), Keycloak 이 계정을 소유하는 배포가 아니다. 그래서 발급·
    # 비활성화·초기화가 이 표면 안에 있다.
    #
    # ⚠️ 식별자를 경로에 두지 않는 규약은 위 unlock 과 같다 — subject 는 IdP 마다
    # 모양이 다르고(이메일·oid·uuid) URL 인코딩 규칙을 계약에 밀어 넣게 된다.
    'list_users': ('GET', '/platform/auth/users'),
    'create_local_user': ('POST', '/platform/auth/users'),
    'disable_user': ('POST', '/platform/auth/users/disable'),
    'enable_user': ('POST', '/platform/auth/users/enable'),
    'reset_user_password': ('POST', '/platform/auth/users/reset-password'),
    'assign_global_role': ('POST', '/platform/auth/users/roles/assign'),
    'revoke_global_role': ('POST', '/platform/auth/users/roles/revoke'),
}


PERMISSIONS: dict[str, str] = {

    # ── 로컬 신원 (2026-08-21) ──────────────────────────────────────────────
    # ⚠️ 로그인/리프레시가 이 저장소에서 'public' 인 **유일한** operation 이다.
    # 그럴 수밖에 없다 — 자격증명을 제시하러 오는 요청은 아직 principal 이 없다.
    # 새 토큰을 만들지 않고 이미 있는 API_PERMISSION_PUBLIC 센티넬을 쓴다(계획서 D-4).
    #
    # ⚠️ 리프레시가 public 인 것은 리프레시 **토큰 자체가 자격증명**이기 때문이다.
    # 액세스 토큰을 요구하면 액세스 토큰이 만료된 뒤 갱신할 방법이 없어져, 리프레시가
    # 존재할 이유가 사라진다.
    'local_auth_login': 'public',
    'local_auth_refresh': 'public',
    # 나머지 셋은 "로그인한 사람이 자기 자신에 대해" 하는 일이라 grantable 토큰이
    # 아니라 authenticated 클래스다 — 어떤 역할도 이것을 부여하거나 회수하지 않는다.
    'local_auth_me': 'authenticated',
    'local_auth_change_password': 'authenticated',
    'local_auth_logout': 'authenticated',
    # 관리자 계정 잠금 해제 (2026-08-23) — 위 셋과 달리 **남의 계정**에 대한 행위라
    # authenticated 가 아니라 최상위 관리자 티어다. ⚠️ ``platform:chamber-config-write``
    # 재사용은 기각 — 그 토큰은 시험원이 갖고, 시험원이 자기 계정을 스스로 풀 수 있으면
    # 잠금이 막으려던 것을 잠금 해제가 되돌린다. 챔버 모드 축이 *행위자가 다르다* 라는
    # 같은 논거로 같은 기각을 이미 했다. **신규 grantable 토큰 0** — ``platform:admin``
    # 은 이미 존재하고 3-way 미러(스키마·API·프론트)를 건드리지 않는다.
    'unlock_local_account': 'platform:admin',
    # ── 사용자 관리 (2026-09-07) ───────────────────────────────────────────
    # 일곱 전부 platform:admin 이다. **신규 grantable 토큰 0.**
    #
    # 2026-09-07 에 platform:admin 은 「시험을 진행하는 사람의 일」을 잃고
    # (그쪽은 platform:project-operate 로 갔다) **사람·권한 관리 전용**이 됐다.
    # 이 일곱이 그 토큰의 새 내용물이고, 그래서 재사용이 옳다 — 같은 직무다.
    #
    # ⚠️ 읽기(`list_users`)도 platform:admin 이다. platform:read 로 낮추지 않는 이유:
    # 그것은 **내부 직원 명부**이고 모든 로그인 사용자가 갖는 토큰이다. 로그인 표면이
    # 네 실패를 구별 불가로 접어 열거를 막는데(위 _INVALID_CREDENTIALS_401), 명부를
    # 열어 두면 그 방어가 우회된다.
    'list_users': 'platform:admin',
    'create_local_user': 'platform:admin',
    'disable_user': 'platform:admin',
    'enable_user': 'platform:admin',
    'reset_user_password': 'platform:admin',
    'assign_global_role': 'platform:admin',
    'revoke_global_role': 'platform:admin',
}


SCHEMAS: dict[str, dict] = {
    # 챔버 모드 축 (2026-08-16) — 승인 절반의 쓰기.
    #
    # 형제 저장-위치 PATCH 와 같은 규약이되 **3-상태**다: 생략 = 불변, null = 판정 철회
    # (*"아무도 결정하지 않음"*), true/false = 명시적 판정. null 과 false 가 다른 값이라는
    # 것이 이 축의 요지이고, 그래서 nullable boolean 이지 bool 이 아니다.
    # ── 로컬 신원 (2026-08-21) ──────────────────────────────────────────────
    'LocalLoginRequest': {
        'type': 'object',
        'required': ['email', 'password'],
        'properties': {
            'email': {
                'type': 'string',
                'description': (
                    'Work email. Compared case-insensitively after trimming; the '
                    'normalised form is the identity key.'
                ),
            },
            'password': {
                'type': 'string',
                'description': (
                    'The password as typed. Never logged, never echoed back, and '
                    'never carried in a URL.'
                ),
            },
        },
        'additionalProperties': False,
    },
    'LocalRefreshRequest': {
        'type': 'object',
        'required': ['refresh_token'],
        'properties': {
            'refresh_token': {
                'type': 'string',
                'description': (
                    'The refresh token from a previous login. It is itself a '
                    'credential, which is why this operation is public.'
                ),
            },
        },
        'additionalProperties': False,
    },
    'LocalChangePasswordRequest': {
        'type': 'object',
        'required': ['current_password', 'new_password'],
        'properties': {
            'current_password': {
                'type': 'string',
                'description': (
                    'Re-verified even though the caller is already authenticated: '
                    'without it a stolen access token becomes account takeover.'
                ),
            },
            'new_password': {
                'type': 'string',
                'description': (
                    'At least 8 characters and at most 72 UTF-8 BYTES (the bcrypt '
                    'ceiling — 24 Hangul characters). No composition rules are '
                    'imposed (NIST SP 800-63B).'
                ),
            },
        },
        'additionalProperties': False,
    },
    'LocalAuthUserEnvelope': {
        'type': 'object',
        'required': ['subject', 'email', 'display_name', 'enabled'],
        'properties': {
            'subject': {'type': 'string'},
            'email': {'type': 'string'},
            'display_name': {'type': 'string'},
            'enabled': {'type': 'boolean'},
            'force_password_change': {
                'type': 'boolean',
                'description': (
                    'When true the caller may reach only the auth operations until '
                    'the password is changed.'
                ),
            },
        },
        'additionalProperties': False,
    },
    'LocalAuthTokenEnvelope': {
        'type': 'object',
        'required': ['access_token', 'refresh_token', 'token_type', 'expires_in'],
        'properties': {
            'access_token': {'type': 'string'},
            'refresh_token': {'type': 'string'},
            'token_type': {'type': 'string'},
            'expires_in': {
                'type': 'integer',
                'description': 'Access-token lifetime in seconds.',
            },
            'force_password_change': {'type': 'boolean'},
            'user': {'allOf': [{'$ref': '#/components/schemas/LocalAuthUserEnvelope'}]},
        },
        'additionalProperties': False,
    },
    # 관리자 계정 잠금 해제 (2026-08-23).
    #
    # ⚠️ **식별자가 경로가 아니라 body 에 있다.** 형제 리소스 operation 들은
    # ``/{chamber_id}`` 처럼 경로에 식별자를 두지만, 여기서 식별자는 **업무 이메일**
    # 이고 경로는 게이트웨이 access log 에 그대로 남는다. 이 저장소는 이미 실 클라이언트
    # 주소가 로그에 들어가는 것을 PII 항목으로 장부에 올려 두었고, 같은 이유로 형제
    # ``local_auth_login`` 도 이메일을 body 로 받는다. RESTful 함보다 **로그에 남지
    # 않는 것**이 우선이다.
    'UnlockLocalAccountRequest': {
        'type': 'object',
        'required': ['email'],
        'properties': {
            'email': {
                'type': 'string',
                'description': (
                    'Work email of the locked account. Normalised exactly as the '
                    'login path normalises it, so an administrator can copy what '
                    'the tester types. Carried in the body rather than the URL so '
                    'it does not land in gateway access logs.'
                ),
            },
        },
        'additionalProperties': False,
    },
    'LocalAccountUnlockEnvelope': {
        'type': 'object',
        'required': ['subject', 'was_locked', 'sessions_invalidated'],
        'properties': {
            'subject': {
                'type': 'string',
                'description': 'The normalised identity key this call addressed.',
            },
            'was_locked': {
                'type': 'boolean',
                'description': (
                    'Whether a lock was actually lifted. FALSE means the account '
                    'exists but held no lock, and then NOTHING happened: no '
                    'session was ended, no counter moved, and no audit row was '
                    'written. That case is a 200 rather than a 404 because "you '
                    'mistyped the address" and "it was already unlocked" need '
                    'different actions from the administrator.'
                ),
            },
            'session_version': {
                'type': ['integer', 'null'],
                'description': (
                    'The account session counter AFTER the unlock, or null when '
                    'was_locked is false (nothing was incremented).'
                ),
            },
            'sessions_invalidated': {
                'type': 'boolean',
                'description': (
                    'True exactly when a lock was lifted, and stated rather than '
                    'implied: lifting a lock ends the account\'s existing '
                    'sessions on every device. That is deliberate — the lock is '
                    'reachable by a holder of a stolen access token, and '
                    'unlocking without it hands the account straight back. '
                    '⚠️ It is not total: that stolen ACCESS token keeps working '
                    'for its remaining lifetime, which is the access-token TTL '
                    'this deployment configures (default 900s / 15 min, settable '
                    'via the local-JWT TTL setting). So re-locking is bounded by '
                    'that TTL, not prevented.'
                ),
            },
        },
        'additionalProperties': False,
    },
    'LocalLogoutRequest': {
        'type': 'object',
        'properties': {
            'refresh_token': {
                'type': 'string',
                'description': (
                    'The refresh token to retire alongside the presented access '
                    'token. Optional only so an older client still logs out '
                    'partially; omitting it leaves a captured refresh token able '
                    'to mint new sessions for its full lifetime.'
                ),
            },
        },
        'additionalProperties': False,
    },
    'LocalLogoutEnvelope': {
        'type': 'object',
        'required': ['logged_out'],
        'properties': {
            'logged_out': {
                'type': 'boolean',
                'description': (
                    'Always true — logout must not be failable, because a caller '
                    'that believes it signed out while it did not is the worst '
                    'outcome this operation has.'
                ),
            },
            'access_token_revoked': {
                'type': 'boolean',
                'description': 'Whether the presented access token was retired.',
            },
            'refresh_token_revoked': {
                'type': 'boolean',
                'description': (
                    'Whether a refresh token was retired. FALSE means the session '
                    'is still refreshable: the caller sent no refresh_token, or an '
                    'unreadable one. The operation still succeeds, but a client '
                    'that ignores this field is signing out only in appearance.'
                ),
            },
        },
        'additionalProperties': False,
    },
    # ── 사용자 관리 (2026-09-07) ───────────────────────────────────────────
    # ⚠️ 사용자 «표현»은 새로 만들지 않는다 — `LocalAuthUserEnvelope` 가 이미
    # subject/email/display_name/enabled 를 담고 있고, 관리자가 보는 사용자와
    # 본인이 보는 사용자는 **같은 사실**이다. 두 벌이 되면 갈라진다.
    'UserAdminList': {
        'type': 'array',
        'items': {'$ref': '#/schemas/UserAdminEnvelope'},
    },
    # 본인 조회 봉투에 «관리자만 아는» 것 둘을 더한다: 전역 역할과 강제변경 상태.
    'UserAdminEnvelope': {
        'type': 'object',
        'required': ['subject', 'email', 'display_name', 'enabled', 'role_keys'],
        'properties': {
            'subject': {'type': 'string'},
            'issuer': {'type': 'string'},
            'email': {'type': 'string'},
            'display_name': {'type': 'string'},
            'enabled': {'type': 'boolean'},
            'role_keys': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': (
                    'Global role keys this user holds. A user may hold more than '
                    'one — engineer + system_admin is the expected shape for a '
                    'tester who also administers the platform.'
                ),
            },
            'force_password_change': {
                'type': 'boolean',
                'description': (
                    'True while the account still carries its issued password. An '
                    'access token minted in this state carries NO permissions, so '
                    'the account can do exactly one thing: change its password.'
                ),
            },
            'locked_until': {'type': 'string', 'nullable': True},
        },
        'additionalProperties': False,
    },
    'CreateLocalUserRequest': {
        'type': 'object',
        'required': ['email', 'display_name'],
        'properties': {
            'email': {'type': 'string', 'minLength': 1},
            'display_name': {'type': 'string', 'minLength': 1},
            'role_keys': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': (
                    'Global roles to grant at creation. Omitted or empty means the '
                    'account is created with NO role — it can log in, change its '
                    'password, and nothing else. That is a deliberate default: an '
                    'account created by mistake grants nothing.'
                ),
            },
        },
        'additionalProperties': False,
        'description': (
            'No password field. The issued password is a fixed constant the '
            'operator already knows, and the account is born with '
            'force_password_change set — so a password in this request would be a '
            'secret travelling through a request body, a log, and an audit row to '
            'buy nothing.'
        ),
    },
    # 셋(disable / enable / reset-password)이 같은 모양이라 하나를 공유한다.
    'UserSubjectRequest': {
        'type': 'object',
        'required': ['subject'],
        'properties': {
            'subject': {'type': 'string', 'minLength': 1},
            'issuer': {'type': 'string'},
        },
        'additionalProperties': False,
    },
    'GlobalRoleRequest': {
        'type': 'object',
        'required': ['subject', 'role_key'],
        'properties': {
            'subject': {'type': 'string', 'minLength': 1},
            'issuer': {'type': 'string'},
            'role_key': {'type': 'string', 'minLength': 1},
        },
        'additionalProperties': False,
    },
}



OPERATIONS: dict[str, dict] = {
    # ── 로컬 신원 (2026-08-21) ──────────────────────────────────────────────
    'local_auth_login': _operation(
        request='LocalLoginRequest',
        response='LocalAuthTokenEnvelope',
        permission=PERMISSIONS['local_auth_login'],
        error_responses={'401': _INVALID_CREDENTIALS_401},
    ),
    'local_auth_refresh': _operation(
        request='LocalRefreshRequest',
        response='LocalAuthTokenEnvelope',
        permission=PERMISSIONS['local_auth_refresh'],
        error_responses={
            '401': _INVALID_CREDENTIALS_401,
            '429': _REFRESH_ROTATION_LIMITED_429,
        },
    ),
    # ⚠️ 아래 셋만 allowed_during_password_change=True 다. 그 플래그가 없으면 부트스트랩
    # 관리자가 첫 로그인 후 **자기 비밀번호를 바꾸는 화면에도 도달하지 못한다**.
    'local_auth_me': _operation(
        request=None,
        response='LocalAuthUserEnvelope',
        permission=PERMISSIONS['local_auth_me'],
        error_responses={'401': _EXPIRED_OR_INVALID_TOKEN_401},
        allowed_during_password_change=True,
    ),
    'local_auth_change_password': _operation(
        request='LocalChangePasswordRequest',
        response='LocalAuthTokenEnvelope',
        permission=PERMISSIONS['local_auth_change_password'],
        error_responses={'401': _INVALID_CREDENTIALS_401},
        allowed_during_password_change=True,
    ),
    'local_auth_logout': _operation(
        request='LocalLogoutRequest',
        response='LocalLogoutEnvelope',
        permission=PERMISSIONS['local_auth_logout'],
        error_responses={'401': _EXPIRED_OR_INVALID_TOKEN_401},
        allowed_during_password_change=True,
    ),
    'unlock_local_account': _operation(
        request='UnlockLocalAccountRequest',
        response='LocalAccountUnlockEnvelope',
        permission=PERMISSIONS['unlock_local_account'],
        error_responses={
            '400': _UNLOCK_MISSING_EMAIL_400,
            '404': _LOCAL_ACCOUNT_NOT_FOUND_404,
        },
    ),
    # ── 사용자 관리 (2026-09-07) ───────────────────────────────────────────
    'list_users': _operation(
        request=None,
        response='UserAdminList',
        permission=PERMISSIONS['list_users'],
    ),
    'create_local_user': _operation(
        request='CreateLocalUserRequest',
        response='UserAdminEnvelope',
        permission=PERMISSIONS['create_local_user'],
        error_responses={'409': _USER_ALREADY_EXISTS_409},
    ),
    'disable_user': _operation(
        request='UserSubjectRequest',
        response='UserAdminEnvelope',
        permission=PERMISSIONS['disable_user'],
        error_responses={
            '400': _USER_ADMIN_SELF_TARGET_400,
            '404': _LOCAL_ACCOUNT_NOT_FOUND_404,
        },
    ),
    'enable_user': _operation(
        request='UserSubjectRequest',
        response='UserAdminEnvelope',
        permission=PERMISSIONS['enable_user'],
        error_responses={'404': _LOCAL_ACCOUNT_NOT_FOUND_404},
    ),
    'reset_user_password': _operation(
        request='UserSubjectRequest',
        response='UserAdminEnvelope',
        permission=PERMISSIONS['reset_user_password'],
        error_responses={'404': _LOCAL_ACCOUNT_NOT_FOUND_404},
    ),
    'assign_global_role': _operation(
        request='GlobalRoleRequest',
        response='UserAdminEnvelope',
        permission=PERMISSIONS['assign_global_role'],
        error_responses={'404': _LOCAL_ACCOUNT_NOT_FOUND_404},
    ),
    'revoke_global_role': _operation(
        request='GlobalRoleRequest',
        response='UserAdminEnvelope',
        permission=PERMISSIONS['revoke_global_role'],
        error_responses={
            '400': _USER_ADMIN_SELF_TARGET_400,
            '404': _LOCAL_ACCOUNT_NOT_FOUND_404,
            '409': _LAST_SYSTEM_ADMIN_409,
        },
    ),
}
