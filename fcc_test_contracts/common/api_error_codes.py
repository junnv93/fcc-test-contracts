"""Machine-readable API error contract (RFC 9457 Problem Details) — B1.

Single source of truth for:

1. ``ErrorCode`` — machine-readable error identifiers a client narrows on
   (frontend i18n routing / ``describeApiError(code)`` in Increment 4).
2. ``ERROR_CODE_STATUS`` — the **only** code → HTTP status mapping. The two
   surface ``api_error_status`` sources (headless / platform) delegate here, so
   HTTP status is byte-identical to the pre-B1 ``isinstance`` chains while every
   error now also carries a stable ``code``.
3. ``ProblemDetails`` — RFC 9457 ``application/problem+json`` body
   (``type``/``title``/``status``/``detail`` standard members + ``code``/``params``
   extensions).

Design constraints:

- **Dependency-free** (``application.common`` purity invariant) — stdlib only.
  Surface-specific exception classes are NOT imported here; each boundary owns a
  declarative ``(exception_type, ErrorCode)`` table and delegates status +
  Problem assembly to this module. That keeps the layering clean (common never
  imports headless/platform services) while the status SSOT stays singular.
- **PII never leaks** — ``params`` accepts only allow-listed, non-PII field
  names (``PROBLEM_PARAM_ALLOWLIST``). The route boundary never populates
  ``params`` from request body/headers/query; the allow-list is a forward guard
  for code that deliberately attaches safe structured context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Tuple, Type


__all__ = [
    'ErrorCode',
    'ERROR_CODE_STATUS',
    'ERROR_CODE_TITLES',
    'ApiSurface',
    'ERROR_CODE_SURFACE_SCOPE',
    'SHARED_ERROR_CODES',
    'surface_error_codes',
    'ProblemDetails',
    'PROBLEM_JSON_MEDIA_TYPE',
    'PROBLEM_TYPE_DEFAULT',
    'PROBLEM_PARAM_ALLOWLIST',
    'PROBLEM_PARAM_DECLARATION_ATTR',
    'problem_params_for',
    'ExceptionCodeTable',
    'UNCLASSIFIED_ERROR_CODE',
    'resolve_error_code',
    'status_for_code',
    'build_problem_details',
]


# RFC 9457 §3 media type for the problem body.
PROBLEM_JSON_MEDIA_TYPE = 'application/problem+json'

# RFC 9457 §4.2.1 — when a problem has no dedicated dereferenceable type URI the
# canonical default is ``about:blank`` and the machine semantic is carried by the
# ``code`` extension member. We do not invent a non-resolving docs URL.
PROBLEM_TYPE_DEFAULT = 'about:blank'


class ErrorCode(str, Enum):
    """Machine-readable error identifier (RFC 9457 ``code`` extension member).

    ``str`` mixin so the enum serializes to its value verbatim in JSON and the
    OpenAPI ``enum`` list. Values are stable wire identifiers — renaming one is a
    breaking API change.
    """

    # 400 — request shape/semantics rejected before reaching a resource.
    VALIDATION_ERROR = 'VALIDATION_ERROR'
    # 400 — the target project has no device model, so an operation that needs the
    # model as its **attribution axis** (sample-inventory import) cannot proceed.
    # Distinct from the generic VALIDATION_ERROR because nothing is wrong with the
    # request: the fix is server-side state ("give this project its model"), and a
    # client that can tell the two apart can say so instead of blaming the upload.
    # Platform-scoped (see ``ERROR_CODE_SURFACE_SCOPE``) — the headless surface has
    # no central project registry and can never emit it.
    PROJECT_MODEL_UNRESOLVED = 'PROJECT_MODEL_UNRESOLVED'
    # 403 — authenticated/anonymous principal lacks the required permission.
    FORBIDDEN = 'FORBIDDEN'
    # 404 — generic resource-not-found (headless ValueError fallback semantics:
    # "measurement job/session/report not found").
    NOT_FOUND = 'NOT_FOUND'
    # 404 — test-plan draft missing or hidden by the project boundary.
    DRAFT_NOT_FOUND = 'DRAFT_NOT_FOUND'
    # 404 — central RBAC membership target (user/role) unknown.
    MEMBERSHIP_NOT_FOUND = 'MEMBERSHIP_NOT_FOUND'
    # 404 — provider UI descriptor id unknown to the platform registry.
    PROVIDER_NOT_FOUND = 'PROVIDER_NOT_FOUND'
    # 404 — the provider picker offers this provider but the central
    # ``providers`` table has no row registering it, so every reference read and
    # write against it resolves nothing. Platform-scoped (see
    # ``ERROR_CODE_SURFACE_SCOPE``) — only the platform surface owns the central
    # provider registry.
    #
    # Distinct from the generic ``NOT_FOUND`` its exception's PARENT still maps
    # to, because the remedy has a different owner: a plain unknown provider
    # means the caller named an id nobody knows and should correct it, while
    # this one means the deployment offered the id and an **operator** must
    # register the provider row. The caller cannot act on it at all, and a
    # client that can tell the two apart says so instead of showing a tester an
    # error they will try and fail to fix.
    REFERENCE_PROVIDER_NOT_REGISTERED = 'REFERENCE_PROVIDER_NOT_REGISTERED'
    # 409 — generic state conflict.
    CONFLICT = 'CONFLICT'
    # 409 — draft row duplicate / DB integrity conflict.
    DRAFT_ROW_CONFLICT = 'DRAFT_ROW_CONFLICT'
    # 409 — publish blocked (not-DRAFT / duplicate condition / CAS race).
    PUBLISH_CONFLICT = 'PUBLISH_CONFLICT'
    # 409 — measurement claim contended (acquire held / release no-open-claim).
    CLAIM_CONFLICT = 'CLAIM_CONFLICT'
    # 409 — project identifier (관리번호 / 모델명) already taken by another
    # project row. Distinct from the generic ``CONFLICT`` because it is the only
    # 409 on the platform surface that is *client-fixable by editing one named
    # input*: the accompanying ``params.field`` says which one. Platform-scoped
    # (see ``ERROR_CODE_SURFACE_SCOPE``) — the headless surface has no project
    # directory write path and can never emit it.
    PROJECT_IDENTIFIER_CONFLICT = 'PROJECT_IDENTIFIER_CONFLICT'
    # 409 — granted download bytes changed on disk (sha256 mismatch).
    DOWNLOAD_INTEGRITY_CONFLICT = 'DOWNLOAD_INTEGRITY_CONFLICT'
    # 404 — the node holds no uploaded workbook under that handle. Session-scoped.
    # Deliberately distinct from the generic ``NOT_FOUND``: the remedy is specific
    # ("upload the workbook again"), and a node that was never composed with an
    # upload store answers this SAME code on purpose, so that an unauthenticated
    # prober cannot tell which nodes accept uploads.
    WORKBOOK_HANDLE_NOT_FOUND = 'WORKBOOK_HANDLE_NOT_FOUND'
    # 409 — a measurement is already running on this node. Session-scoped, and
    # distinct from the generic ``CONFLICT`` because the remedy is one specific
    # action the operator can take from the same screen: stop, then start.
    SESSION_ALREADY_RUNNING = 'SESSION_ALREADY_RUNNING'
    # 410 — download grant/token access window elapsed.
    DOWNLOAD_EXPIRED = 'DOWNLOAD_EXPIRED'
    # 422 — draft scope semantically unprocessable (shape ok, meaning invalid).
    DRAFT_UNPROCESSABLE = 'DRAFT_UNPROCESSABLE'
    # 422 — a selected sample has no deterministic Conduction/Radiation category
    # for the requested operational workbook template.
    SAMPLE_EXPORT_CATEGORY_UNRESOLVED = 'SAMPLE_EXPORT_CATEGORY_UNRESOLVED'
    # 422 — publishable shape but the draft has no rows.
    DRAFT_EMPTY = 'DRAFT_EMPTY'
    # 422 — the session exists but has produced no measurement rows, so there is
    # nothing to render into a result workbook. Deliberately NOT ``DRAFT_EMPTY``:
    # a draft is an authoring artefact and a session is a measurement run, and the
    # two say different things to the person holding the screen ("your plan has no
    # rows" vs "this run has not measured anything yet"). Headless-scoped — the
    # platform surface owns no measurement session export.
    SESSION_RESULTS_EMPTY = 'SESSION_RESULTS_EMPTY'
    # 422 — the publication request is syntactically JSON but attempts to supply
    # server-owned provenance or otherwise violates the closed request shape.
    # Platform-scoped: only the central result-reference publication route emits
    # this code.
    REFERENCE_REQUEST_UNPROCESSABLE = 'REFERENCE_REQUEST_UNPROCESSABLE'
    # 413 — uploaded workbook exceeds this node's configured ceiling. Session-
    # scoped. 413 exists in the taxonomy only because of this operation; the
    # accompanying ``params.max`` carries the ceiling so the screen can state it
    # rather than asking the tester to guess.
    WORKBOOK_UPLOAD_TOO_LARGE = 'WORKBOOK_UPLOAD_TOO_LARGE'
    # 415 — uploaded bytes are not an .xlsx workbook. Session-scoped. Separate
    # from 413 because the remedy is a different file, not a smaller one.
    WORKBOOK_UPLOAD_UNSUPPORTED_TYPE = 'WORKBOOK_UPLOAD_UNSUPPORTED_TYPE'
    # 429 — inbound rate limit exceeded (domain/services/rate_limit_policy).
    # Emitted by the rate-limit middleware, not by a route handler, so it is the
    # one code a client can receive from ANY operation on any surface.
    RATE_LIMITED = 'RATE_LIMITED'
    # 503 — central backend unavailable (read/write/RBAC infra failure).
    UPSTREAM_UNAVAILABLE = 'UPSTREAM_UNAVAILABLE'
    # 503 — this node was not composed with a workbook upload store, so it cannot
    # accept the upload at all. Session-scoped.
    SESSION_UPLOAD_UNSUPPORTED = 'SESSION_UPLOAD_UNSUPPORTED'
    # 503 — this node has neither a workbook nor runtime reference rows, so it
    # cannot source the values a measurement needs. Session-scoped.
    #
    # ⚠️ NOT folded into ``SESSION_UPLOAD_UNSUPPORTED`` even though both are 503
    # "this node is not ready". The operator does DIFFERENT things: that one needs
    # the node composed with an upload store, this one needs the reference
    # revisions published for the named families. Folding them would leave the
    # client no way back except parsing a sentence written for a human.
    SESSION_NODE_NOT_PROVISIONED = 'SESSION_NODE_NOT_PROVISIONED'
    # 503 — a reference lookup family this operation needs has no rows, so the
    # capability matrix cannot be built at all. Headless-scoped.
    #
    # ⚠️ NOT folded into ``SESSION_NODE_NOT_PROVISIONED`` even though both are 503
    # "the reference data is missing". Two reasons, both concrete: that code's
    # title says *node* and *measure with*, and this one is raised while AUTHORING
    # a test plan — a screen where no node is involved; and the operator's remedy
    # differs (that one wants reference revisions published for the named
    # families, this one wants the frequency table seeded).
    #
    # ⚠️ NOT ``UPSTREAM_UNAVAILABLE`` either: that promises "a dependency is down,
    # retrying may work". Retrying this never works until somebody seeds.
    REFERENCE_DATA_NOT_PROVISIONED = 'REFERENCE_DATA_NOT_PROVISIONED'
    # 401 — the supplied credentials did not authenticate. Local-login only,
    # platform-scoped.
    #
    # ⚠️ **401, and it is the only 401 in this repository.** Everything else here
    # answers 403 for both "anonymous" and "under-permissioned", and that is right
    # for AUTHORIZATION on a protected resource — the client already knows who it
    # is. A login endpoint asks a different question: credentials were supplied
    # and did not verify, which is exactly RFC 9110's 401. A frontend needs the
    # two apart, because 403 means "stop" and 401 means "show the login form".
    #
    # ⚠️ **This one code covers FOUR distinct situations** — no such user, wrong
    # password, disabled account, locked account. That is deliberate and is the
    # user-enumeration defence: any refusal that can tell them apart hands an
    # attacker the internal staff directory without a single correct password.
    # See ``application/platform/local_auth_service`` for the timing axis too.
    AUTH_INVALID_CREDENTIALS = 'AUTH_INVALID_CREDENTIALS'
    # 403 — authenticated, but a pending password change blocks everything else.
    # Platform-scoped.
    #
    # ⚠️ NOT folded into ``FORBIDDEN``. They demand opposite things of the client:
    # FORBIDDEN means "you will never be allowed this, stop asking", while this
    # means "do one specific thing and you may proceed". Folded together, a
    # bootstrap administrator hits a dead end on their first login with no way to
    # discover that changing the password is the way out.
    AUTH_PASSWORD_CHANGE_REQUIRED = 'AUTH_PASSWORD_CHANGE_REQUIRED'
    # 500 — unmapped/internal error.
    INTERNAL_ERROR = 'INTERNAL_ERROR'


# ── Status SSOT ───────────────────────────────────────────────────────────────
# The ONLY code → HTTP status mapping. ``api_error_status`` on both surfaces is a
# thin delegation onto this table, so the historical status values are preserved
# byte-identical (sealed by ``test_api_error_contract_status_parity``).
ERROR_CODE_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.PROJECT_MODEL_UNRESOLVED: 400,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.DRAFT_NOT_FOUND: 404,
    ErrorCode.MEMBERSHIP_NOT_FOUND: 404,
    ErrorCode.PROVIDER_NOT_FOUND: 404,
    ErrorCode.REFERENCE_PROVIDER_NOT_REGISTERED: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.DRAFT_ROW_CONFLICT: 409,
    ErrorCode.PUBLISH_CONFLICT: 409,
    ErrorCode.CLAIM_CONFLICT: 409,
    ErrorCode.PROJECT_IDENTIFIER_CONFLICT: 409,
    ErrorCode.DOWNLOAD_INTEGRITY_CONFLICT: 409,
    ErrorCode.WORKBOOK_HANDLE_NOT_FOUND: 404,
    ErrorCode.SESSION_ALREADY_RUNNING: 409,
    ErrorCode.WORKBOOK_UPLOAD_TOO_LARGE: 413,
    ErrorCode.WORKBOOK_UPLOAD_UNSUPPORTED_TYPE: 415,
    ErrorCode.DOWNLOAD_EXPIRED: 410,
    ErrorCode.DRAFT_UNPROCESSABLE: 422,
    ErrorCode.SAMPLE_EXPORT_CATEGORY_UNRESOLVED: 422,
    ErrorCode.DRAFT_EMPTY: 422,
    ErrorCode.SESSION_RESULTS_EMPTY: 422,
    ErrorCode.REFERENCE_REQUEST_UNPROCESSABLE: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.UPSTREAM_UNAVAILABLE: 503,
    ErrorCode.SESSION_UPLOAD_UNSUPPORTED: 503,
    ErrorCode.SESSION_NODE_NOT_PROVISIONED: 503,
    ErrorCode.REFERENCE_DATA_NOT_PROVISIONED: 503,
    ErrorCode.AUTH_INVALID_CREDENTIALS: 401,
    ErrorCode.AUTH_PASSWORD_CHANGE_REQUIRED: 403,
    ErrorCode.INTERNAL_ERROR: 500,
}


# RFC 9457 ``title`` — short, human-readable summary that does NOT change between
# occurrences of the same problem type (the per-occurrence text is ``detail``).
ERROR_CODE_TITLES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: 'Request validation failed',
    ErrorCode.PROJECT_MODEL_UNRESOLVED: 'Project has no device model',
    ErrorCode.FORBIDDEN: 'Forbidden',
    ErrorCode.NOT_FOUND: 'Resource not found',
    ErrorCode.DRAFT_NOT_FOUND: 'Test-plan draft not found',
    ErrorCode.MEMBERSHIP_NOT_FOUND: 'Project membership not found',
    ErrorCode.PROVIDER_NOT_FOUND: 'Provider not found',
    ErrorCode.REFERENCE_PROVIDER_NOT_REGISTERED: 'Provider not registered centrally',
    ErrorCode.CONFLICT: 'Conflict',
    ErrorCode.DRAFT_ROW_CONFLICT: 'Draft row conflict',
    ErrorCode.PUBLISH_CONFLICT: 'Publish conflict',
    ErrorCode.CLAIM_CONFLICT: 'Claim conflict',
    ErrorCode.PROJECT_IDENTIFIER_CONFLICT: 'Project identifier conflict',
    ErrorCode.DOWNLOAD_INTEGRITY_CONFLICT: 'Download integrity conflict',
    ErrorCode.WORKBOOK_HANDLE_NOT_FOUND: 'Uploaded workbook not found',
    ErrorCode.SESSION_ALREADY_RUNNING: 'A measurement is already running',
    ErrorCode.WORKBOOK_UPLOAD_TOO_LARGE: 'Workbook upload too large',
    ErrorCode.WORKBOOK_UPLOAD_UNSUPPORTED_TYPE: 'Uploaded file is not a workbook',
    ErrorCode.DOWNLOAD_EXPIRED: 'Download grant expired',
    ErrorCode.DRAFT_UNPROCESSABLE: 'Draft unprocessable',
    ErrorCode.SAMPLE_EXPORT_CATEGORY_UNRESOLVED: 'Sample export category unresolved',
    ErrorCode.DRAFT_EMPTY: 'Draft is empty',
    ErrorCode.SESSION_RESULTS_EMPTY: 'Session has no measurement results',
    ErrorCode.REFERENCE_REQUEST_UNPROCESSABLE: 'Reference publication request is unprocessable',
    ErrorCode.RATE_LIMITED: 'Too many requests',
    ErrorCode.UPSTREAM_UNAVAILABLE: 'Upstream service unavailable',
    ErrorCode.SESSION_UPLOAD_UNSUPPORTED: 'This node does not accept workbook uploads',
    ErrorCode.SESSION_NODE_NOT_PROVISIONED: 'This node has no reference data to measure with',
    ErrorCode.REFERENCE_DATA_NOT_PROVISIONED: 'Reference data is not provisioned',
    ErrorCode.AUTH_INVALID_CREDENTIALS: 'Invalid email or password',
    ErrorCode.AUTH_PASSWORD_CHANGE_REQUIRED: 'Password change required',
    ErrorCode.INTERNAL_ERROR: 'Internal server error',
}


# ── Surface scope ─────────────────────────────────────────────────────────────
# Which web surface's OpenAPI ``ErrorCode`` enum publishes a given code.
#
# Before this table every surface published the WHOLE ``ErrorCode`` union, so
# adding one member rewrote every ``docs/api/*-api.openapi.json`` artifact even
# when only one surface could emit it. A code declared here is published ONLY on
# the listed surfaces.
#
# **Why the pre-existing codes are not scoped down** — the shared union is a
# ratchet, not an endorsement. Two facts make shrinking it a separate, larger
# change than adding a scoped code:
#   1. a published enum member is part of the wire contract; removing one is a
#      breaking change for generated clients, and
#   2. ``apps/web/src/shared/api-error.ts`` builds its web-wide ``ErrorCode``
#      as the *union* of every surface artifact that publishes one (it aliased
#      the platform enum alone until 2026-08-13, which is exactly how a
#      headless-scoped code became unnameable there), so removing a member on
#      any surface breaks TypeScript compilation in a package this contract
#      does not own.
# Scoping the pre-existing members down (and re-pointing the web alias) is
# tracked debt; new codes are scoped correctly from birth so the union can only
# ratchet DOWN, never grow further.
class ApiSurface(str, Enum):
    """A web surface that publishes an OpenAPI document with an error contract."""

    HEADLESS = 'headless'
    PLATFORM = 'platform'
    # 2026-08-23 — the measurement-node surface. It published legacy
    # ``{"detail": str}`` bodies until this member existed, which is why the
    # repository carried TWO error contracts across three surfaces.
    #
    # ⚠️ Adding a surface WIDENS what the unscoped union publishes: a code with
    # no ``ERROR_CODE_SURFACE_SCOPE`` entry is published on every surface, so the
    # session artifact now enumerates shared codes it can never emit. That is the
    # same documented state headless and platform are already in, and paying it
    # down means scoping every pre-existing member to the surfaces that can emit
    # it — a separate axis. Stated rather than quietly inherited.
    SESSION = 'session'


# Codes with a restricted scope. A code ABSENT from this mapping is published on
# every surface (the frozen shared union described above).
ERROR_CODE_SURFACE_SCOPE: dict[ErrorCode, frozenset[ApiSurface]] = {
    # Only the platform surface owns the project directory write path.
    ErrorCode.PROJECT_IDENTIFIER_CONFLICT: frozenset({ApiSurface.PLATFORM}),
    # Only the platform surface has a central project registry to resolve a model
    # from (W3 백엔드 — sample-inventory attribution axis).
    ErrorCode.PROJECT_MODEL_UNRESOLVED: frozenset({ApiSurface.PLATFORM}),
    ErrorCode.SAMPLE_EXPORT_CATEGORY_UNRESOLVED: frozenset({ApiSurface.PLATFORM}),
    # Only the headless surface exports a measurement session's results.
    ErrorCode.SESSION_RESULTS_EMPTY: frozenset({ApiSurface.HEADLESS}),
    # The six session refusals below exist only on the measurement-node surface:
    # no other surface owns an upload store, a run gate, or a node's reference
    # provisioning. Scoped from birth so the shared union can only ratchet DOWN.
    ErrorCode.WORKBOOK_HANDLE_NOT_FOUND: frozenset({ApiSurface.SESSION}),
    ErrorCode.SESSION_ALREADY_RUNNING: frozenset({ApiSurface.SESSION}),
    ErrorCode.WORKBOOK_UPLOAD_TOO_LARGE: frozenset({ApiSurface.SESSION}),
    ErrorCode.WORKBOOK_UPLOAD_UNSUPPORTED_TYPE: frozenset({ApiSurface.SESSION}),
    ErrorCode.SESSION_UPLOAD_UNSUPPORTED: frozenset({ApiSurface.SESSION}),
    ErrorCode.SESSION_NODE_NOT_PROVISIONED: frozenset({ApiSurface.SESSION}),
    ErrorCode.REFERENCE_PROVIDER_NOT_REGISTERED: frozenset({ApiSurface.PLATFORM}),
    ErrorCode.REFERENCE_REQUEST_UNPROCESSABLE: frozenset({ApiSurface.PLATFORM}),
    # Only the headless surface builds a capability matrix from provider-local
    # reference tables. Scoped from birth so the shared union ratchets DOWN.
    ErrorCode.REFERENCE_DATA_NOT_PROVISIONED: frozenset({ApiSurface.HEADLESS}),
    # Only the platform surface issues and verifies local password credentials.
    # Scoped from birth so the shared union can only ratchet DOWN.
    ErrorCode.AUTH_INVALID_CREDENTIALS: frozenset({ApiSurface.PLATFORM}),
    ErrorCode.AUTH_PASSWORD_CHANGE_REQUIRED: frozenset({ApiSurface.PLATFORM}),
}


# The unscoped union — what a surface publishes when it does not declare its own
# scope. Derived, never hand-listed, so it cannot drift from ``ErrorCode``.
SHARED_ERROR_CODES: tuple[ErrorCode, ...] = tuple(
    code for code in ErrorCode if code not in ERROR_CODE_SURFACE_SCOPE
)


def surface_error_codes(surface: ApiSurface) -> tuple[ErrorCode, ...]:
    """Return the codes ``surface`` publishes, in ``ErrorCode`` declaration order.

    A code is published on ``surface`` when it is unscoped (shared union) or when
    ``surface`` appears in its ``ERROR_CODE_SURFACE_SCOPE`` entry.
    """
    return tuple(
        code for code in ErrorCode
        if surface in ERROR_CODE_SURFACE_SCOPE.get(code, frozenset(ApiSurface))
    )


# ── PII allow-list ────────────────────────────────────────────────────────────
# ``params`` may carry ONLY these structured, non-PII field names. Anything else
# (request body fields, header/query values, free-form identifiers a client
# supplied) is rejected so the problem body cannot become a PII exfiltration
# channel. The route boundary attaches no params; this guards future call sites.
PROBLEM_PARAM_ALLOWLIST: frozenset[str] = frozenset({
    'field',       # which contract field failed validation
    'limit',       # page-size bound that was violated
    'max',         # an upper bound that was exceeded
    'min',         # a lower bound
    'expected',    # an expected enum/format token
    'allowed',     # the allowed token set
    'resource',    # the resource KIND (not its user-supplied id)
    'expected_version',  # optimistic-concurrency version (structured integer)
    'retry_after', # seconds hint for 503/429-style responses
})


# ── How an exception says what belongs in ``params`` ──────────────────────────
# The class attribute an exception declares to opt into the ``params`` extension.
# Its value is a tuple of ATTRIBUTE NAMES on the exception; each name must also be
# a ``PROBLEM_PARAM_ALLOWLIST`` member.
#
#     class GenerationRequestRejected(ValueError):
#         PROBLEM_PARAM_FIELDS = ('field',)
#
# ⚠️ **Declaration, not attribute scraping.** The obvious shortcut — pull every
# allow-listed NAME off any exception that happens to have it — looks equivalent
# today and is not. ``limit``/``max``/``min``/``resource`` are ordinary words; the
# first exception that carries one of them meaning something else would put a
# value on the wire that nobody chose to publish. Opt-in makes that unreachable.
#
# ⚠️ **This replaced a per-surface isinstance table.** Until 2026-08-31 exactly one
# boundary populated ``params`` (platform, via a private ``_problem_params(exc)``
# isinstance chain) and the other two sent none at all — so a headless 400 could
# not say WHICH field a tester had got wrong even though the server knew. Copying
# that helper to the second and third surface would have made three tables that
# drift; the exception knowing its own structured context makes the boundaries
# need no table at all.
PROBLEM_PARAM_DECLARATION_ATTR = 'PROBLEM_PARAM_FIELDS'


def problem_params_for(exc: BaseException) -> dict[str, Any]:
    """Structured, allow-listed ``params`` an exception declares about itself.

    Returns ``{}`` for an exception that declares nothing — which is every
    exception in the repository except the handful that deliberately opt in.

    **Total: never raises.** This is boundary *diagnostics*. An exception raised
    while collecting it would turn the response we are in the middle of building
    into a 500, i.e. a misdeclared diagnostic would destroy the very refusal it
    was meant to explain. So a declaration that is malformed, names a
    non-allow-listed key, or hangs on a property that itself raises degrades to
    "no params" instead — and a ``None`` value is dropped rather than published,
    because "this refusal has no field" and "its field is null" are not the same
    statement.

    The strictness lives in the gate, not here: ``tests/test_problem_params_axis``
    walks every declaring class and fails when a declared name is outside
    :data:`PROBLEM_PARAM_ALLOWLIST`. That asymmetry — runtime degrades, gate
    refuses — is the same one the work-claim status vocabulary settled on, and for
    the same reason: the strict half must run where a human will see it.
    """
    declared = getattr(exc, PROBLEM_PARAM_DECLARATION_ATTR, None)
    if not isinstance(declared, (tuple, list)):
        return {}
    params: dict[str, Any] = {}
    for name in declared:
        if not isinstance(name, str) or name not in PROBLEM_PARAM_ALLOWLIST:
            continue
        try:
            value = getattr(exc, name, None)
        except Exception:  # noqa: BLE001 — a property that raises is not fatal here
            continue
        if value is not None:
            params[name] = value
    return params


# A declarative, ordered exception→code mapping. Ordered most-specific-first so a
# subclass resolves before its superclass (mirrors the old isinstance chains).
ExceptionCodeTable = Sequence[Tuple[Type[BaseException], ErrorCode]]


# ── The unmatched sentinel ────────────────────────────────────────────────────
# What a web surface answers when NOTHING in its table classified the exception.
#
# There is exactly one value because a surface has no legitimate reason to differ:
# an unclassified exception is a statement about **our** failure to classify, and
# that is the same failure everywhere. ``INTERNAL_ERROR`` (500) says it honestly.
#
# ⚠️ This is deliberately a single constant and NOT a ``{ApiSurface: ErrorCode}``
# mapping. A per-surface map whose values are all equal preserves the very seam
# this constant exists to close — it documents the divergence instead of removing
# it, and the next surface added gets its own row to disagree in.
#
# **This used to be three literals and they DID diverge.** Until 2026-08-27 the
# headless boundary defaulted to ``NOT_FOUND`` while session and platform used
# ``INTERNAL_ERROR``, so headless answered "404 not found" for request-validation
# failures, server misconfiguration, and absent reference data alike. The wire
# ``code`` was a lie, and it cost a full session of diagnosis on a live e2e lane:
# the operator read the 404, believed the surface names itself (problem+json), and
# looked for a missing project that was never missing. The three literals agreed
# on nothing more than luck; one definition removes the seam.
UNCLASSIFIED_ERROR_CODE: ErrorCode = ErrorCode.INTERNAL_ERROR


def resolve_error_code(
    exc: BaseException,
    table: ExceptionCodeTable,
    *,
    default: ErrorCode,
) -> ErrorCode:
    """Return the ``ErrorCode`` for ``exc`` from ``table`` (first isinstance hit).

    ``table`` MUST be ordered most-specific-first. Falls back to ``default``,
    which every web surface sources from :data:`UNCLASSIFIED_ERROR_CODE` — an
    exception no table classified is an internal failure, not a missing resource.
    """
    for exc_type, code in table:
        if isinstance(exc, exc_type):
            return code
    return default


def status_for_code(code: ErrorCode) -> int:
    """HTTP status for ``code`` from the single ``ERROR_CODE_STATUS`` SSOT."""
    return ERROR_CODE_STATUS[code]


@dataclass(frozen=True)
class ProblemDetails:
    """RFC 9457 Problem Details value object.

    ``as_dict()`` emits the standard members (``type``/``title``/``status``/
    ``detail``) plus the ``code`` extension always, and the optional
    ``instance``/``params`` extensions when present. ``params`` keys are
    validated against ``PROBLEM_PARAM_ALLOWLIST`` at construction (PII guard).
    """

    status: int
    title: str
    code: ErrorCode
    detail: str = ''
    type: str = PROBLEM_TYPE_DEFAULT
    instance: Optional[str] = None
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        illegal = set(self.params) - PROBLEM_PARAM_ALLOWLIST
        if illegal:
            raise ValueError(
                'ProblemDetails.params contains non-allow-listed key(s) '
                f'{sorted(illegal)} — only {sorted(PROBLEM_PARAM_ALLOWLIST)} are '
                'permitted (PII guard; never capture request body/header/query).'
            )

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            'type': self.type,
            'title': self.title,
            'status': self.status,
            'detail': self.detail,
            'code': self.code.value,
        }
        if self.instance:
            body['instance'] = self.instance
        if self.params:
            body['params'] = dict(self.params)
        return body


def build_problem_details(
    exc: BaseException,
    table: ExceptionCodeTable,
    *,
    default: ErrorCode,
    instance: Optional[str] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> ProblemDetails:
    """Assemble a ``ProblemDetails`` for ``exc`` using ``table`` + status SSOT.

    ``detail`` is the human-readable ``str(exc)`` (RFC 9457 §3.1 — the
    per-occurrence explanation), preserving the pre-B1 ``{detail: str(exc)}``
    body content while adding the machine ``code`` + standard members.

    ``params`` **defaults to what the exception declares about itself**
    (:func:`problem_params_for`) rather than to empty. That is deliberate and it
    is what makes the structured context impossible for a surface to forget: the
    alternative — every boundary calling the helper — is three call sites that
    can drift, and the drift is silent because a missing ``params`` looks exactly
    like an exception that had none to give. Passing an explicit mapping still
    wins verbatim (including ``{}`` for "publish nothing"), so a caller that
    knows better is not overridden by the default.
    """
    code = resolve_error_code(exc, table, default=default)
    return ProblemDetails(
        status=ERROR_CODE_STATUS[code],
        title=ERROR_CODE_TITLES[code],
        code=code,
        detail=str(exc),
        instance=instance,
        params=problem_params_for(exc) if params is None else params,
    )
