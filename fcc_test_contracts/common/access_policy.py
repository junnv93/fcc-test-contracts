"""Dependency-free access policy for shared web API operations.

Fix #4 (2026-05-24): moved from ``application/headless/`` to ``application/common/``
because both Session API and Headless API web entrypoints share the same
``ApiPrincipal`` / ``AccessDecision`` / ``ApiAccessPolicy`` classes.

Deep #3 (2026-05-24):
- Class renamed from ``ApiAccessPolicy`` to ``ApiAccessPolicy`` (의미-중립).
  Session API + Headless API + 미래 추가 API 모두 동일 정책 객체 사용.
- ``operations`` 인자 required positional — silent fallback (default
  ``HEADLESS_API_OPERATIONS``) 영구 제거. Session API 가 누락 시 잘못된 operations
  catalog 사용 위험 차단.
- ``application.headless.api_contracts.HEADLESS_API_OPERATIONS`` 직접 의존 영구 제거 —
  module-level import 0 (호출자가 명시적으로 주입).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fcc_test_contracts.common.identity import LEGACY_IDENTITY_ISSUER, canonical_issuer


__all__ = [
    'ALLOWED_DURING_PASSWORD_CHANGE',
    'REASON_PASSWORD_CHANGE_REQUIRED',
    'API_PERMISSION_ADMIN',
    'API_PERMISSION_AUTHENTICATED',
    'API_PERMISSION_PUBLIC',
    'API_PERMISSION_WILDCARD',
    'AccessDecision',
    'ApiAccessPolicy',
    'ApiPrincipal',
]


API_PERMISSION_ADMIN = 'admin'
API_PERMISSION_PUBLIC = 'public'
API_PERMISSION_WILDCARD = '*'
#: Authorization CLASS (not a grantable token) — "any resolved, non-anonymous
#: principal passes; anonymous is denied". Mirrors the PUBLIC sentinel's role as
#: a non-grantable authorization mode (ADR-0017 D3): project creation is a
#: GLOBAL operation that a brand-new project cannot gate by project-scoped
#: membership (no membership exists yet), yet must still require login. Like
#: 'public', this token is NEVER listed in rbac_role_grants and NEVER mirrored
#: into apps/web permissions.ts — it is excluded from the RBAC parity universe
#: (tests/test_rbac_parity.py) exactly as 'public' is.
API_PERMISSION_AUTHENTICATED = 'authenticated'
#: Operation-contract key: "this operation stays reachable while the caller still
#: has a pending password change". Absent/false everywhere else — fail closed.
ALLOWED_DURING_PASSWORD_CHANGE = 'allowed_during_password_change'

#: ``AccessDecision.reason`` a boundary maps to
#: ``ErrorCode.AUTH_PASSWORD_CHANGE_REQUIRED``. A distinct reason (not just
#: ``missing_permission``) because the two demand opposite things of the client:
#: one means "stop", this one means "do one specific thing and proceed".
REASON_PASSWORD_CHANGE_REQUIRED = 'password_change_required'

#: The subject value a principal carries when no identity was resolved.
_ANONYMOUS_SUBJECT = 'anonymous'


@dataclass(frozen=True)
class ApiPrincipal:
    subject: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    #: Optional resource binding (멀티챔버, 2026-06-20). A chamber machine token may
    #: carry a ``chamber_id`` claim binding it to ONE chamber — the heartbeat
    #: endpoint rejects a token that tries to report a *different* chamber. Empty
    #: for human/generic tokens (no per-chamber binding). Kept on the shared
    #: principal so the binding is a first-class authZ input, not an ad-hoc claim
    #: re-parse at the endpoint.
    chamber_id: str = ''
    #: Validated identity issuer. OIDC principals carry the configured issuer
    #: after JWT issuer validation; local/trusted-header principals use a stable
    #: legacy issuer so central identity is keyed by (issuer, subject).
    issuer: str = LEGACY_IDENTITY_ISSUER
    #: Verified identity metadata carried only from the trusted auth boundary.
    #: These fields are provisioning metadata, not authorization inputs.
    display_name: str = ''
    email: str = ''
    #: 신원 축 EMS 정합 (2026-08-21) — 이 principal 은 비밀번호를 바꾸기 전까지
    #: **아무것도 할 수 없다**. 로컬 토큰의 ``fpc`` 클레임에서 온다.
    #:
    #: ⚠️ 이것은 provisioning 메타데이터가 **아니라 authorization 입력**이다 (위 두
    #: 필드와 다르다). 부트스트랩 관리자가 초기 비밀번호로 로그인한 상태에서 시험
    #: 데이터를 만지기 시작하면, 그 초기 비밀번호는 환경변수에 적혀 있고 배포 로그에
    #: 남아 있으며 아무도 바꾸지 않는다.
    force_password_change: bool = False

    @classmethod
    def anonymous(cls) -> 'ApiPrincipal':
        return cls(subject='anonymous')

    @classmethod
    def from_permissions(
        cls,
        subject: str,
        permissions: list[str] | tuple[str, ...] | set[str] | frozenset[str],
        *,
        chamber_id: str = '',
        issuer: str = LEGACY_IDENTITY_ISSUER,
        display_name: str = '',
        email: str = '',
        force_password_change: bool = False,
    ) -> 'ApiPrincipal':
        return cls(
            subject=str(subject or '').strip() or 'anonymous',
            permissions=frozenset(_text(permission) for permission in permissions),
            chamber_id=str(chamber_id or '').strip(),
            issuer=canonical_issuer(issuer),
            display_name=str(display_name or '').strip(),
            email=str(email or '').strip(),
            force_password_change=bool(force_password_change),
        )


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    operation: str
    required_permission: str
    subject: str
    reason: str = ''

    def to_dict(self) -> dict:
        return {
            'allowed': self.allowed,
            'operation': self.operation,
            'required_permission': self.required_permission,
            'subject': self.subject,
            'reason': self.reason,
        }


class ApiAccessPolicy:
    """Authorize API operations against the operation permission contract.

    Deep #3 (2026-05-24): ``operations`` is required (no default fallback to
    ``HEADLESS_API_OPERATIONS``). Session API 가 SESSION_API_OPERATIONS 주입을
    빠뜨려도 silent 로 headless catalog 를 쓰던 위험 영구 제거.
    """

    def __init__(self, operations: dict[str, dict]) -> None:
        if operations is None:
            raise TypeError(
                'ApiAccessPolicy: operations dict 은 필수입니다 — '
                'Session/Headless API 가 자기 operations catalog 명시 주입 필요.'
            )
        self._operations = operations

    def authorize(
        self,
        operation: str,
        principal: ApiPrincipal | None,
    ) -> AccessDecision:
        operation_contract = self._operations.get(operation)
        subject = principal.subject if principal is not None else 'anonymous'
        if operation_contract is None:
            return AccessDecision(
                allowed=False,
                operation=operation,
                required_permission='',
                subject=subject,
                reason='unknown_operation',
            )

        required = _text(operation_contract.get('permission'))
        if not required:
            return AccessDecision(
                allowed=False,
                operation=operation,
                required_permission='',
                subject=subject,
                reason='missing_permission_contract',
            )
        if required == API_PERMISSION_PUBLIC:
            return AccessDecision(
                allowed=True,
                operation=operation,
                required_permission=required,
                subject=subject,
            )

        # 신원 축 EMS 정합 (2026-08-21) — a principal with a pending password
        # change may reach ONLY the operations that let it resolve that state.
        #
        # ⚠️ The allow-list is DECLARED BY THE OPERATION CONTRACT, not listed
        # here. Two reasons. (1) This module is surface-agnostic; naming platform
        # operation ids in it would put one surface's vocabulary into the shared
        # policy. (2) It is **fail-closed**: an operation added later says nothing
        # about this flag and is therefore blocked, which is the safe default. A
        # list living here would silently fail OPEN for every operation somebody
        # forgot to add to it.
        #
        # This runs AFTER the public short-circuit on purpose — login and refresh
        # are public, and a bootstrap admin must be able to obtain a token in
        # order to have anything to change the password with.
        if (
            principal is not None
            and getattr(principal, 'force_password_change', False)
            and not operation_contract.get(ALLOWED_DURING_PASSWORD_CHANGE)
        ):
            return AccessDecision(
                allowed=False,
                operation=operation,
                required_permission=required,
                subject=subject,
                reason=REASON_PASSWORD_CHANGE_REQUIRED,
            )

        if required == API_PERMISSION_AUTHENTICATED:
            # ADR-0017 D3 — a GLOBAL (non-project-scoped) operation that requires
            # only a resolved login, not a grantable permission. Allowed iff a
            # non-anonymous principal was resolved; anonymous is denied. No
            # membership / token lookup (a new project has no membership yet).
            authenticated = principal is not None and subject != _ANONYMOUS_SUBJECT
            return AccessDecision(
                allowed=authenticated,
                operation=operation,
                required_permission=required,
                subject=subject,
                reason='' if authenticated else 'unauthenticated',
            )

        permissions = principal.permissions if principal is not None else frozenset()
        if (
            required in permissions
            or API_PERMISSION_WILDCARD in permissions
            or API_PERMISSION_ADMIN in permissions
        ):
            return AccessDecision(
                allowed=True,
                operation=operation,
                required_permission=required,
                subject=subject,
            )

        return AccessDecision(
            allowed=False,
            operation=operation,
            required_permission=required,
            subject=subject,
            reason='missing_permission',
        )


def _text(value: object) -> str:
    if value is None:
        return ''
    return str(value).strip()
