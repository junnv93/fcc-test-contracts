"""`scripts/check_extraction_import_boundaries.py` 의 **알맹이** (2026-09-05).

⚠️ `scripts/` 는 패키지가 아니라 **휠이 나르지 못한다.** 이 레인을 pip 로 받는
소비자에게 그 파일은 오지 않는다 — 그리고 그것이 소비 레인
(`fcc-test-platform`)의 `scripts/platform_extraction_runner.py` 가 배송된 상자에서
**import 조차 되지 않던** 원인이다(실측 2026-09-04, 공급 폐포 게이트 계급 B).

모노레포의 매니페스트가 그 자리를 이미 이름 붙여 놨다:

    *"세 개의 platform 박스 시험 모듈이 `check_extraction_import_boundaries` 를 맨
    최상위 이름으로 import 한다 — 그것이 배송된 트리가 자기 `scripts/` 에 닿는
    방식이다. … **platform conftest 는 자기 `scripts/` 만 얹을 수 있고 형제의 것은
    못 얹는다.**"*

그 문장이 적은 것은 **스테이징 시점의 우회**(형제의 `scripts/` 를 PYTHONPATH 에
얹는다)이지 설치본에서 성립하는 형태가 아니다. 배송 상자에는 형제 디렉터리가 없다.

⭐ 그래서 형제 도구가 이미 간 길을 따른다 — `prepare_headless_extraction_package.py`
가 2026-08-31 에 같은 사유로 알맹이를 `fcc_test_contracts.extraction_package` 로
옮겼고, 그 진입점이 자기 주석에 규칙을 적어 뒀다: *"이 파일이 **짧은 것이 요점**이다.
… 알맹이가 바뀌면 휠이 나른다."* 로직은 여기 살고 `scripts/` 에는 진입점만 남는다.

⚠️ 「`scripts/` 는 배포하지 않는다」 결정은 **뒤집히지 않았다.** `scripts/` 는 여전히
휠에 실리지 않는다 — 실리는 것은 알맹이이고, 스크립트는 진입점으로 남는다.

──────────────────────────────────────────────────────────────────────────────
아래는 원본 스크립트의 머리말이고, 이 모듈의 계약은 그대로다.

Check staged extraction trees for cross-repository import leakage.

Lane rules are **derived** from the extraction manifest
(``docs/api/headless_contract_extraction_manifest.v1.json``) through
``fcc_test_contracts.common.extraction_lane_policy``. This module deliberately
keeps no lane→prefix table of its own: when it did, the two sides drifted — the
``fcc-unlicensed-headless`` lane carried an empty forbidden *and* an empty
allowed tuple, so its gate could not report a single import violation, while
the platform lane banned ``application.common`` that the manifest had already
handed to the contracts lane.

The output contract (``schema_version`` 1 payload, ``--root/--lane/--output/
--require-clean`` CLI) is unchanged; only the source of the rules moved.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path

from fcc_test_contracts.common.extraction_lane_policy import ExtractionLanePolicy
from fcc_test_contracts.common.tree_artifacts import (
    operating_repository_root as _repository_root,
    resolve_repo_artifact,
)

# ⚠️ **모듈 위치에서 파생하면 안 된다.** 이 모듈은 「자기가 어느 저장소에 있나」가
# 아니라 **「지금 어느 저장소를 다루나」**를 알아야 한다 — `load_policy` 가 여기에
# 정책을 묶고, 그 묶음이 *"누가 `scripts.foo` 를 소유하나"* 에 답하게 하기 때문이다.
# 사유는 `operating_repository_root` 의 docstring 에 있다(설치본에서 `parents[1]` 은
# `site-packages` 이고, 그 상태는 「경로가 맞다」와 같은 모양이다).
PROJECT_ROOT = _repository_root()
SRC_ROOT = PROJECT_ROOT / 'src'

# Addressed by its repository-relative name and resolved through the packager's
# own layout record: this lane delivers docs/api/ to artifacts/ at the box root,
# so a nearest-ancestor walk finds the box's docs/ directory and then looks for a
# file that is no longer under it. The record answers where it actually went.
DEFAULT_MANIFEST = resolve_repo_artifact(
    __file__, 'docs/api/headless_contract_extraction_manifest.v1.json',
)


def load_policy(manifest_path: Path | None = None) -> ExtractionLanePolicy:
    """Load and bind the policy to this monorepo's tree.

    Binding is what lets both gates below see ``scripts/`` imports at all —
    ``namespaces()``/``lane_for_module`` answer ``unclassified`` for every
    ``scripts.*`` target on an unbound policy. Bound to ``PROJECT_ROOT``
    rather than whatever staged tree a caller later checks: "who owns
    ``scripts.foo``" is a monorepo ownership question, not a question about
    the tree being validated.
    """
    return ExtractionLanePolicy.from_path(manifest_path or DEFAULT_MANIFEST).bound_to(PROJECT_ROOT)


def lane_choices(policy: ExtractionLanePolicy | None = None) -> list[str]:
    return sorted((policy or load_policy()).lanes)


def check_import_boundaries(
    root: Path,
    *,
    lane: str,
    policy: ExtractionLanePolicy | None = None,
) -> dict:
    policy = policy or load_policy()
    resolved_root = root.resolve(strict=False)
    if lane not in policy.lanes:
        return _payload(lane, root, 0, [
            _violation('', 0, 'unknown_lane', lane, f'unknown lane: {lane}'),
        ])
    if not resolved_root.exists():
        return _payload(lane, root, 0, [
            _violation('', 0, 'missing_root', str(root), f'root does not exist: {root}'),
        ])

    allowed = policy.allowed_prefixes(lane)
    forbidden = policy.forbidden_prefixes(lane)

    violations: list[dict] = []
    files = _python_files(resolved_root, policy)
    for path in files:
        rel_path = _relative(path, resolved_root)
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError as exc:
            violations.append(_violation(rel_path, exc.lineno or 0, 'parse_error', '', exc.msg))
            continue
        except UnicodeDecodeError as exc:
            violations.append(_violation(rel_path, 0, 'decode_error', '', str(exc)))
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _append_if_forbidden(
                        violations,
                        lane=lane,
                        allowed=allowed,
                        forbidden=forbidden,
                        rel_path=rel_path,
                        line=node.lineno,
                        kind='import',
                        module=alias.name,
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                _append_if_forbidden(
                    violations,
                    lane=lane,
                    allowed=allowed,
                    forbidden=forbidden,
                    rel_path=rel_path,
                    line=node.lineno,
                    kind='from',
                    module=node.module,
                )

    return _payload(lane, root, len(files), violations)


def check_dependency_resolution(
    root: Path,
    *,
    lane: str,
    policy: ExtractionLanePolicy | None = None,
    sibling_roots: dict[str, Path] | None = None,
) -> dict:
    """Imports the staged tree is *allowed* to make but cannot resolve.

    A different question from :func:`check_import_boundaries`, and the reason
    they must stay apart is that the boundary gate answered ``valid`` over a
    platform package in which 40 of 78 shipped test files could not even be
    collected. The gate asks *may this tree import that name*; permitted
    dependencies pass, correctly, because ``depends_on`` grants them. Nobody was
    asking the second question — *will that import resolve in the box we are
    handing over* — and a declared dependency that is not delivered and not
    declared as an installable requirement resolves nowhere.

    Reported, never inferred away: the fix for a name in this list is a
    packaging decision (publish the dependency, or vendor it), and this function
    deliberately does not guess which. Silence here would let a package that
    unpacks cleanly and runs nothing look finished.

    ``sibling_roots`` credits a dependency that is delivered *beside* this lane
    rather than inside it — the shape ``fcc-test-contracts`` has, being its own
    package that the platform names but never received. Only **directories that
    exist** count. Crediting a declared requirement would make this the one
    thing it must never be: a gate satisfiable by declaration, which is how the
    boundary gate came to report a package clean while 40 of its test files
    could not be collected. The shared kernel cannot be credited this way at
    all — it has no package name and is not an extraction target — so the two
    mechanisms stay structurally apart and neither can hide the other's number.
    """
    policy = policy or load_policy()
    resolved_root = root.resolve(strict=False)
    if lane not in policy.lanes or not resolved_root.exists():
        return {
            'schema_version': 1, 'lane': lane, 'root': str(root),
            'python_files': 0, 'unresolved': [], 'satisfied_by_sibling': [],
        }

    allowed = policy.allowed_prefixes(lane)
    files = _python_files(resolved_root, policy)
    delivered_by: dict[str, tuple[str, str]] = {}
    for sibling, sibling_root in (sibling_roots or {}).items():
        sibling_path = Path(sibling_root).resolve(strict=False)
        if not sibling_path.is_dir():
            continue
        for name in _top_level_names(sibling_path, policy):
            delivered_by.setdefault(name, (sibling, str(sibling_path)))
    stdlib = set(sys.stdlib_module_names) | set(sys.builtin_module_names)

    unresolved: dict[str, int] = {}
    satisfied: dict[str, tuple[str, str]] = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for module in _module_names(tree):
            head = module.split('.')[0]
            if head in stdlib:
                continue
            if _module_resolves_locally(resolved_root, module):
                continue
            if _resolves_via_entry_point_root(resolved_root, module, policy):
                continue
            if not any(_matches_prefix(module, prefix) for prefix in allowed):
                # Not permitted at all — that is the boundary gate's finding,
                # and counting it twice would make one defect look like two.
                continue
            if head in delivered_by:
                satisfied[head] = delivered_by[head]
                continue
            unresolved[module] = unresolved.get(module, 0) + 1

    return {
        'schema_version': 1,
        'lane': lane,
        'root': str(root),
        'python_files': len(files),
        'unresolved': [
            {'module': module, 'occurrences': count}
            for module, count in sorted(unresolved.items())
        ],
        # Kept apart from the count on purpose: "resolved because it is in the
        # box" and "resolved because a sibling package carries it" are different
        # facts about what a receiving team must install, and one number cannot
        # say which moved.
        'satisfied_by_sibling': [
            {'module_head': head, 'lane': lane_name, 'root': sibling_root}
            for head, (lane_name, sibling_root) in sorted(satisfied.items())
        ],
    }


def _top_level_names(root: Path, policy: ExtractionLanePolicy) -> set[str]:
    """Importable top-level names the staged tree itself provides.

    Includes bare names of files directly inside each of the *monorepo's*
    entry-point roots (:meth:`ExtractionLanePolicy.entry_point_roots` —
    ``scripts/`` in this manifest), not just the top-level names ``root``
    itself carries: every CLI under an entry-point root adds its own
    directory to ``sys.path`` (``contract_cli.ensure_importable`` is the
    shared reason why, and ``tests/conftest.py`` does the same in the
    monorepo), so a sibling file inside ``scripts/`` is reachable by its bare
    name from *inside* that directory — exactly how
    ``check_headless_provider_registry.py`` reaches ``contract_cli``. Before
    this, a sibling tree's own ``scripts/contract_cli.py`` was invisible to
    credit because only the *sibling's root* was scanned, one level short of
    where the file actually sits.

    Entry-point-ness is asked of the *monorepo* tree (``PROJECT_ROOT``), not
    of ``root`` itself — the same tree :func:`load_policy` binds against.
    A sibling's staged copy of ``scripts/`` does not necessarily ship its own
    ``__init__.py``, so asking ``root`` the same question :meth:`entry_point_roots`
    asks of the source tree would silently stop crediting it the moment that
    file is not copied; whether a root is *conceptually* an entry point is a
    fact about the source, evidence for which the staged copy is not
    required to carry.
    """
    names: set[str] = set()
    for child in root.iterdir():
        if child.is_dir():
            names.add(child.name)
        elif child.suffix == '.py':
            names.add(child.stem)
    for entry_root in policy.entry_point_roots(PROJECT_ROOT):
        entry_dir = root / entry_root.rstrip('/')
        if not entry_dir.is_dir():
            continue
        for child in entry_dir.iterdir():
            if child.is_file() and child.suffix == '.py':
                names.add(child.stem)
    return names


def _module_resolves_locally(root: Path, module: str) -> bool:
    """Whether ``module`` resolves to a real file or package under ``root``.

    Checking only the top-level segment (``module.split('.')[0]``) is where
    the previous version of this check was wrong: once a tree ships a
    ``scripts/`` package at all, *every* ``scripts.*`` import looked
    resolved, even one whose specific submodule was never copied into the
    box — a false resolution that would have hidden exactly the gap this
    axis exists to catch. This walks the whole dotted path instead, accepting
    either a package (a directory, so a package-level import like
    ``import domain.services`` still resolves) or a module (the final segment
    as a ``.py`` file). A directory is accepted without requiring
    ``__init__.py`` — the staged trees this checks ship implicit namespace
    packages (``fcc_test_platform/`` itself has none), and Python has resolved
    those since 3.3; requiring one would fail every import of the package the
    lane is named after.
    """
    parts = module.split('.')
    candidate = root
    for index, part in enumerate(parts):
        candidate = candidate / part
        is_last = index == len(parts) - 1
        if is_last:
            return candidate.with_suffix('.py').is_file() or candidate.is_dir()
        if not candidate.is_dir():
            return False
    return True


def _resolves_via_entry_point_root(
    root: Path, module: str, policy: ExtractionLanePolicy,
) -> bool:
    """Whether ``module`` resolves from *inside* one of ``root``'s entry-point roots.

    The same fact :func:`_top_level_names` already reads for a *sibling* tree,
    asked of the lane's own box: a CLI under an entry-point root runs with that
    directory on ``sys.path``, so ``scripts/check_headless_provider_registry.py``
    reaches its neighbour as bare ``contract_cli``. Crediting that for siblings
    and not for self is the asymmetry this closes — it made eleven modules that
    are physically in their own box report as delivered nowhere, and the
    extraction evidence answer ``valid: false`` with nothing actually missing.

    This cannot reintroduce the false resolution :func:`_module_resolves_locally`
    documents. The whole dotted path is walked *beneath* the entry directory, so
    ``scripts.foo`` is asked for ``scripts/scripts/foo.py`` here and is credited
    only by the root walk, on the real file — a never-copied submodule still
    resolves nowhere in either place.

    Entry-point-ness is asked of the monorepo (``PROJECT_ROOT``), not of ``root``,
    for the reason :func:`_top_level_names` gives: whether a root is conceptually
    an entry point is a fact about the source tree, and the staged copy is not
    required to carry the ``__init__.py`` that evidences it.
    """
    for entry_root in policy.entry_point_roots(PROJECT_ROOT):
        entry_dir = root / entry_root.rstrip('/')
        if entry_dir.is_dir() and _module_resolves_locally(entry_dir, module):
            return True
    return False


def _module_names(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def _python_files(root: Path, policy: ExtractionLanePolicy) -> list[Path]:
    """Collect ``*.py`` under ``root``, pruning trees governance excludes."""
    collected: list[Path] = []
    for current, dirnames, filenames in os.walk(root):
        rel_dir = Path(current).relative_to(root).as_posix()
        rel_dir = '' if rel_dir == '.' else rel_dir
        dirnames[:] = sorted(
            name for name in dirnames
            if not policy.should_prune_dir(f'{rel_dir}/{name}' if rel_dir else name)
        )
        collected.extend(
            Path(current) / name for name in filenames if name.endswith('.py')
        )
    return sorted(collected)


def _payload(lane: str, root: Path, python_files: int, violations: list[dict]) -> dict:
    return {
        'schema_version': 1,
        'lane': lane,
        'root': str(root),
        'valid': not violations,
        'python_files': python_files,
        'violations': violations,
    }


def _append_if_forbidden(
    violations: list[dict],
    *,
    lane: str,
    allowed: tuple[str, ...],
    forbidden: tuple[str, ...],
    rel_path: str,
    line: int,
    kind: str,
    module: str,
) -> None:
    # Longest match wins, the same rule path ownership uses. A blanket allow on
    # `application.headless` must not shadow the ban on
    # `application.headless.central_db_config`, which a different lane owns —
    # checking "allowed first, any match" silently let every carve-out through.
    best_allowed = max(
        (prefix for prefix in allowed if _matches_prefix(module, prefix)),
        key=len,
        default='',
    )
    matched = max(
        (prefix for prefix in forbidden if _matches_prefix(module, prefix)),
        key=len,
        default='',
    )
    if len(best_allowed) >= len(matched):
        return
    if matched:
        violations.append(_violation(
            rel_path,
            line,
            kind,
            module,
            f'import crosses {lane} boundary via {matched}',
        ))


def _matches_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + '.')


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _violation(path: str, line: int, kind: str, module: str, message: str) -> dict:
    return {
        'path': path,
        'line': int(line or 0),
        'kind': kind,
        'module': module,
        'message': message,
    }


def main(argv: list[str] | None = None) -> int:
    policy = load_policy()
    parser = argparse.ArgumentParser(description='Check staged extraction import boundaries.')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--lane', choices=lane_choices(policy), required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--require-clean', action='store_true')
    args = parser.parse_args(argv)

    payload = check_import_boundaries(args.root, lane=args.lane, policy=policy)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)

    if args.require_clean and not payload['valid']:
        return 1
    return 0

