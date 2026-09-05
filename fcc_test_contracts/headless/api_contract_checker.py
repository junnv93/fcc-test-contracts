"""Compatibility checks for shared headless API contract documents."""
from __future__ import annotations

from dataclasses import dataclass, field

from fcc_test_contracts.headless.api_contracts import ApiContractSnapshot
from fcc_test_contracts.headless.dependency_closure import closure_issues
from fcc_test_contracts.headless.contract_identity import (
    FeatureScopeError,
    contract_comparison_document,
    feature_scoped_document,
)


__all__ = [
    'ApiContractCompatibilityResult',
    'ApiContractIssue',
    'check_api_contract_compatibility',
]

# Module-level type alias for the ``mode`` argument. Intentionally NOT part of
# the curated public surface (``__all__``): the alias resolves to a bare ``str``
# and its legal values (``_FULL_MODE`` / ``_LIVE_SUBSET_MODE``) are kept private,
# so exporting it would expose an opaque symbol without its valid values. It
# remains importable as a module attribute for type hints. Public surface SSOT:
# tests/test_api_contract_public_surface_phase29.py.
ApiContractCheckMode = str
_FULL_MODE = 'full'
_LIVE_SUBSET_MODE = 'live-subset'
#: Judge the provider against the surface it SAYS it serves (§6.7, 2026-09-05).
#:
#: ⚠️ Deliberately not a reuse of ``live-subset``. That mode was rejected as a
#: conformance basis for one reason — *nobody defined which subset is legal* —
#: and reusing its name would carry the rejection along with it. Here the legal
#: subset is the provider's own declaration, reduced by the SAME function on
#: both sides, and it is checked rather than assumed: every operation of every
#: declared feature must be present, required features are in scope whether
#: declared or not, and the dependency closure must hold.
_DECLARED_FEATURES_MODE = 'declared-features'


@dataclass(frozen=True)
class ApiContractIssue:
    code: str
    path: str
    message: str

    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'path': self.path,
            'message': self.message,
        }


@dataclass(frozen=True)
class ApiContractCompatibilityResult:
    compatible: bool
    issues: list[ApiContractIssue] = field(default_factory=list)
    warnings: list[ApiContractIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'compatible': self.compatible,
            'issues': [issue.to_dict() for issue in self.issues],
            'warnings': [warning.to_dict() for warning in self.warnings],
        }


def check_api_contract_compatibility(
    provider_contract: dict,
    expected_contract: dict | None = None,
    *,
    mode: ApiContractCheckMode = _FULL_MODE,
    declared_features=None,
) -> ApiContractCompatibilityResult:
    """Compare a provider contract document with the local SSOT contract."""
    if mode not in {_FULL_MODE, _LIVE_SUBSET_MODE, _DECLARED_FEATURES_MODE}:
        raise ValueError(f"unsupported api contract check mode: {mode!r}")
    if (mode == _DECLARED_FEATURES_MODE) != (declared_features is not None):
        raise ValueError(
            "declared_features is required by mode 'declared-features' and "
            "meaningless in any other mode"
        )

    expected = expected_contract or ApiContractSnapshot().to_dict()
    ssot = expected
    if mode == _DECLARED_FEATURES_MODE:
        # ⚠️ Reduce the EXPECTATION, not the judgement. Everything below still
        # demands the whole of what is in scope — the subset is chosen by the
        # provider's declaration, then verified in full. A mode that instead
        # softened the comparison would be `live-subset` again.
        try:
            expected = feature_scoped_document(expected, declared_features)
        except FeatureScopeError as error:
            return ApiContractCompatibilityResult(
                compatible=False,
                issues=[ApiContractIssue(
                    code='unknown_declared_feature',
                    path='features',
                    message=str(error),
                )],
            )
    # ⚠️ Both sides are reduced by the SAME function the identity digest uses.
    # This used to be the dict comprehension below, spelled twice — and a third
    # spelling would have appeared in `contract_identity` the day evidence
    # documents needed to say *which contract was checked*. Three spellings of
    # "the same contract" is three things that can drift apart without any of
    # them saying so; one function is one answer.
    provider_contract = contract_comparison_document(provider_contract)
    expected = contract_comparison_document(expected)
    issues: list[ApiContractIssue] = []
    warnings: list[ApiContractIssue] = []

    _check_version(expected, provider_contract, warnings)
    _check_compatibility_major(expected, provider_contract, issues)
    require_all = mode in {_FULL_MODE, _DECLARED_FEATURES_MODE}
    _check_routes(expected, provider_contract, issues, warnings, require_all=require_all)
    _check_operations(expected, provider_contract, issues, warnings, require_all=require_all)
    _check_schemas(expected, provider_contract, issues, warnings, require_all=require_all)
    if mode == _DECLARED_FEATURES_MODE:
        _check_dependency_closure(ssot, provider_contract, issues)

    return ApiContractCompatibilityResult(
        compatible=not issues,
        issues=issues,
        warnings=warnings,
    )


def _check_version(expected: dict, provider: dict, warnings: list[ApiContractIssue]) -> None:
    if provider.get('version') != expected.get('version'):
        warnings.append(ApiContractIssue(
            code='version_difference',
            path='version',
            message=(
                f"expected {expected.get('version')!r}, "
                f"got {provider.get('version')!r}"
            ),
        ))


def _check_compatibility_major(
    expected: dict,
    provider: dict,
    issues: list[ApiContractIssue],
) -> None:
    if provider.get('compatibility_major') != expected.get('compatibility_major'):
        issues.append(ApiContractIssue(
            code='compatibility_major_mismatch',
            path='compatibility_major',
            message=(
                f"expected {expected.get('compatibility_major')!r}, "
                f"got {provider.get('compatibility_major')!r}"
            ),
        ))


def _missing_issue(
    *,
    code: str,
    path: str,
    message: str,
    issues: list[ApiContractIssue],
    warnings: list[ApiContractIssue],
    require_all: bool,
) -> None:
    target = issues if require_all else warnings
    target.append(ApiContractIssue(code=code, path=path, message=message))


def _check_routes(
    expected: dict,
    provider: dict,
    issues: list[ApiContractIssue],
    warnings: list[ApiContractIssue],
    *,
    require_all: bool,
) -> None:
    expected_routes = expected.get('routes') or {}
    provider_routes = provider.get('routes') or {}
    for name, expected_route in expected_routes.items():
        path = f"routes.{name}"
        actual_route = provider_routes.get(name)
        if actual_route is None:
            _missing_issue(
                code='missing_route',
                path=path,
                message=f"missing route {name}",
                issues=issues,
                warnings=warnings,
                require_all=require_all,
            )
            continue
        if actual_route.get('method') != expected_route.get('method'):
            issues.append(ApiContractIssue(
                code='route_method_mismatch',
                path=f"{path}.method",
                message=(
                    f"expected {expected_route.get('method')!r}, "
                    f"got {actual_route.get('method')!r}"
                ),
            ))
        if actual_route.get('path') != expected_route.get('path'):
            issues.append(ApiContractIssue(
                code='route_path_mismatch',
                path=f"{path}.path",
                message=(
                    f"expected {expected_route.get('path')!r}, "
                    f"got {actual_route.get('path')!r}"
                ),
            ))


def _check_operations(
    expected: dict,
    provider: dict,
    issues: list[ApiContractIssue],
    warnings: list[ApiContractIssue],
    *,
    require_all: bool,
) -> None:
    expected_operations = expected.get('operations') or {}
    provider_operations = provider.get('operations') or {}
    for name, expected_operation in expected_operations.items():
        path = f"operations.{name}"
        actual_operation = provider_operations.get(name)
        if actual_operation is None:
            _missing_issue(
                code='missing_operation',
                path=path,
                message=f"missing operation {name}",
                issues=issues,
                warnings=warnings,
                require_all=require_all,
            )
            continue
        for key in ('request', 'response', 'permission'):
            if actual_operation.get(key) != expected_operation.get(key):
                issues.append(ApiContractIssue(
                    code=f'operation_{key}_mismatch',
                    path=f"{path}.{key}",
                    message=(
                        f"expected {expected_operation.get(key)!r}, "
                        f"got {actual_operation.get(key)!r}"
                    ),
                ))


def _check_schemas(
    expected: dict,
    provider: dict,
    issues: list[ApiContractIssue],
    warnings: list[ApiContractIssue],
    *,
    require_all: bool,
) -> None:
    expected_schemas = expected.get('schemas') or {}
    provider_schemas = provider.get('schemas') or {}
    for name, expected_schema in expected_schemas.items():
        path = f"schemas.{name}"
        actual_schema = provider_schemas.get(name)
        if actual_schema is None:
            _missing_issue(
                code='missing_schema',
                path=path,
                message=f"missing schema {name}",
                issues=issues,
                warnings=warnings,
                require_all=require_all,
            )
            continue
        if actual_schema != expected_schema:
            issues.append(ApiContractIssue(
                code='schema_mismatch',
                path=path,
                message=f"schema differs for {name}",
            ))


def _check_dependency_closure(
    ssot: dict,
    provider: dict,
    issues: list[ApiContractIssue],
) -> None:
    """The arm that is not a provider comparing itself with itself.

    The other two arms of the §6.7.1 rule — core is present, declaration matches
    surface — both read only the provider's own two statements, so a provider
    that declares nothing and serves nothing satisfies them. This one asks
    whether the surface it does serve can actually be USED: an operation whose
    path needs an id nothing in the served set can mint is a door with no key.

    ⚠️ Producers are derived from the SSOT, not from the provider's document.
    Deriving them from the provider's own artifact would let a provider satisfy
    the closure by declaring a producer it invented, and a check whose two sides
    come from one source is an identity.
    """
    served = set(provider.get('operations') or {})
    for issue in closure_issues(
        served,
        ssot.get('operations') or {},
        {
            name: (route.get('method'), route.get('path'))
            for name, route in (ssot.get('routes') or {}).items()
        },
        ssot.get('schemas') or {},
    ):
        issues.append(ApiContractIssue(
            code='dependency_closure_violation',
            path=f"operations.{issue['operation']}",
            message=(
                f"serves {issue['operation']}, which needs "
                f"{issue['identifier']}, but serves none of its producers "
                f"{list(issue['producers'])}"
            ),
        ))
