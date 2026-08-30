"""Validate and optionally stage files from the headless extraction manifest.

Two shapes of relocation exist, and the difference is deliberate:

* a **file entry** names one path and moves it;
* a **directory entry** — ``current_path`` ending in ``/`` — names a tree and is
  expanded into concrete file entries when the plan is built.

The second shape exists because the first cannot express ownership honestly at
scale. ``src/application/platform/`` and ``apps/web/`` hold 258 governed files
between them; enumerating them by hand recreates the defect SPLIT-1 just
repaid, where 18 of a lane's 34 files had no entry and were therefore neither
copied nor import-rewritten while the runner still reported ``valid: true``.
A hand-maintained list is the place the *next* file goes missing, and that
silence only surfaces on extraction day. A directory entry makes ownership and
relocation speak in the same unit, so totality is structural rather than
clerical. ``OwnershipRule`` already reads a trailing ``/`` as a directory
prefix, so this reuses an existing meaning rather than inventing one.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / 'src'
for _path in (PROJECT_ROOT, SRC_ROOT):
    _text = str(_path)
    if _text not in sys.path:
        sys.path.insert(0, _text)

from fcc_test_contracts.common.tree_artifacts import (  # noqa: E402
    LAYOUT_RECORD_NAME, resolve_repo_artifact,
)
# Only the manifest *vocabulary* is bound at module level — the constants below
# are re-exports and must resolve before any function runs. ``ExtractionLanePolicy``
# itself stays a function-local import, which is this file's existing shape.
from fcc_test_contracts.common.extraction_lane_policy import (  # noqa: E402
    CONSUMED_BASIS_DELIVERY,
    LANE_TEST_SUITE_KIND as _LANE_TEST_SUITE_KIND,
    SHARED_KERNEL_CLOSURE_KIND as _SHARED_KERNEL_CLOSURE_KIND,
)

# The record, not a directory walk: this lane delivers docs/api/ to artifacts/.
DEFAULT_MANIFEST = resolve_repo_artifact(
    __file__, 'docs/api/headless_contract_extraction_manifest.v1.json',
)

#: Entry kinds whose relocation also renames a Python import namespace.
PYTHON_RELOCATION_KINDS = ('python_module', 'python_package')

#: The third relocation shape: *this lane's test suite*.
#:
#: A directory entry cannot express it. ``current_path`` ending in ``/`` is a
#: **path prefix**, and a lane's tests are scattered through ``tests/`` by
#: subject rather than gathered under a directory — handing ``tests/`` to the
#: platform as a prefix would ship it 434 provider tests. The membership
#: question here is answered by content (what a test imports), not by location,
#: so it gets its own expansion rather than a special case inside the directory
#: one.
#
# The literal moved to the policy with the rest of the manifest vocabulary; the
# name is re-exported here because that is where every caller has always read
# it. One definition, one binding, no copy.
LANE_TEST_SUITE_KIND = _LANE_TEST_SUITE_KIND

#: The fourth relocation shape: *the shared kernel this lane actually reaches*.
#:
#: ``shared-kernel`` is not a repository lane, so nothing stages it, and both
#: lanes that declare it as a dependency received a package whose ``domain.*``
#: imports resolved nowhere. The obvious repair — promote the layer and ship it
#: whole — hands a joining team every measurement judgement in ``src/domain/``
#: (``power_judgment``, ``ant_gain_validation``, …), which is the outcome
#: ADR-0018 D-5 keeps closed.
#:
#: So ownership and delivery answer different questions here too, exactly as
#: they already do for tests: the kernel keeps owning the whole layer and the
#: box takes the consumption closure. Membership is content, not location, so
#: like ``lane_test_suite`` it cannot be a directory entry — a trailing slash is
#: a path prefix, and a prefix would ship all 229 files.
#
# Re-exported from the policy for the same reason as ``LANE_TEST_SUITE_KIND``:
# the filter that reads it is now the policy's, and a second literal here would
# be free to disagree with the derivation it feeds.
SHARED_KERNEL_CLOSURE_KIND = _SHARED_KERNEL_CLOSURE_KIND


def _lane_policy(manifest: dict):
    """Policy bound to ``manifest``, imported the way this file already does.

    A named seam rather than a seventh inline ``from … import`` so the reader
    can see that every question about lanes in this module is answered by the
    same object.
    """
    from fcc_test_contracts.common.extraction_lane_policy import ExtractionLanePolicy
    return ExtractionLanePolicy.from_manifest(manifest)


def build_extraction_plan(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    repository: str | None = None,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    repositories = manifest['repositories']
    selected_names = [repository] if repository else list(repositories)
    issues: list[dict] = []
    packages: dict[str, list[dict]] = {}

    from fcc_test_contracts.common.extraction_lane_policy import MANIFEST_VERSION

    if manifest.get('manifest_version') != MANIFEST_VERSION:
        # A typed issue, not a traceback. This CLI's contract is that it always
        # prints a plan document, and callers parse stdout even on a non-zero
        # exit; letting the policy's ValueError escape turned a named refusal
        # into "no output at all". The version only started mattering here when
        # package rewrite keys began needing the policy, so the failure mode was
        # new even though the check was not.
        return {
            'schema_version': 1,
            'manifest_path': _relative(manifest_path),
            'packages': {},
            'import_rewrites': {},
            'issues': [_issue(
                'unsupported_manifest_version', 'manifest_version',
                f'extraction manifest must be version {MANIFEST_VERSION}, '
                f'got {manifest.get("manifest_version")!r}',
            )],
            'compatible': False,
        }

    for repo_name in selected_names:
        repo = repositories.get(repo_name)
        if repo is None:
            issues.append(_issue('unknown_repository', repo_name, f'unknown repository lane: {repo_name}'))
            continue
        # Two passes, and the order is the point: the shared-kernel closure is
        # seeded by *what this lane's own files import*, so those files have to
        # be resolved first. Any entry kind can contribute a seed — the platform
        # body reaches the kernel from ``src/application/platform/`` and its test
        # suite reaches it again from ``tests/`` — so the split is "everything
        # else" then "the closure", not a list of kinds that may seed.
        declared = list(enumerate(repo.get('entries') or []))
        deferred = [
            (index, entry) for index, entry in declared
            if entry.get('kind') == SHARED_KERNEL_CLOSURE_KIND
        ]
        entries = []
        for index, entry in declared:
            if entry.get('kind') == SHARED_KERNEL_CLOSURE_KIND:
                continue
            issue_path = f'repositories.{repo_name}.entries[{index}]'
            expanded, entry_issues = _plan_entry(
                entry,
                repo_name=repo_name,
                manifest=manifest,
                issue_path=issue_path,
                already_planned=tuple(item['current_path'] for item in entries),
            )
            issues.extend(entry_issues)
            entries.extend(expanded)
        for index, entry in deferred:
            issue_path = f'repositories.{repo_name}.entries[{index}]'
            expanded, entry_issues = _plan_entry(
                entry,
                repo_name=repo_name,
                manifest=manifest,
                issue_path=issue_path,
                # The basis is named rather than assumed. This one is
                # ``delivery`` — what the box carries — and the filter that
                # drops the closure entry from its own seed lives in the
                # policy, so the parity invariant cannot re-derive it
                # differently.
                consumed=_lane_policy(manifest).consumed_for_lane(
                    PROJECT_ROOT, repo_name, CONSUMED_BASIS_DELIVERY, planned=entries,
                ),
                already_planned=tuple(item['current_path'] for item in entries),
            )
            issues.extend(entry_issues)
            entries.extend(expanded)
        packages[repo_name] = entries

    return {
        'schema_version': 1,
        'manifest_path': _relative(manifest_path),
        'packages': packages,
        # Derived from *every* lane, not just the packaged one. A platform module
        # importing a contracts-lane module that moved must be rewritten too, or
        # the staged tree reaches for a name that will not exist.
        'import_rewrites': _import_rewrite_map(manifest),
        'issues': issues,
        'compatible': not issues,
    }


def _plan_entry(
    entry: dict, *, repo_name: str, manifest: dict, issue_path: str,
    consumed: tuple[str, ...] = (),
    already_planned: tuple[str, ...] = (),
) -> tuple[list[dict], list[dict]]:
    """Resolve one manifest entry into the concrete files it relocates."""
    current_path = str(entry.get('current_path', '')).replace('\\', '/')
    destination = _safe_future_path(entry.get('future_path', ''))
    if destination is None:
        return [], [_issue(
            'unsafe_future_path', issue_path,
            'future_path must be relative and must not contain traversal',
        )]

    if entry.get('kind') == SHARED_KERNEL_CLOSURE_KIND:
        return _expand_shared_kernel_closure(
            entry,
            current_path=current_path,
            destination=destination,
            repo_name=repo_name,
            manifest=manifest,
            issue_path=issue_path,
            consumed=consumed,
        )

    if entry.get('kind') == LANE_TEST_SUITE_KIND:
        return _expand_lane_test_suite(
            entry,
            current_path=current_path,
            destination=destination,
            repo_name=repo_name,
            manifest=manifest,
            issue_path=issue_path,
            already_planned=already_planned,
        )

    if not current_path.endswith('/'):
        source = PROJECT_ROOT / current_path
        if not source.exists():
            return [], [_issue('missing_source', issue_path, f'missing source: {current_path}')]
        if _violates_forbidden(repo_name, current_path, manifest):
            return [], [_issue('forbidden_shared_path', issue_path, f'forbidden shared path: {current_path}')]
        return [_planned(entry, current_path, destination.as_posix(), source)], []

    return _expand_directory_entry(
        entry,
        current_path=current_path,
        destination=destination,
        repo_name=repo_name,
        manifest=manifest,
        issue_path=issue_path,
    )


def _expand_lane_test_suite(
    entry: dict,
    *,
    current_path: str,
    destination: Path,
    repo_name: str,
    manifest: dict,
    issue_path: str,
    already_planned: tuple[str, ...],
) -> tuple[list[dict], list[dict]]:
    """Expand *this lane's tests* into the files that must be in the box.

    Attribution and delivery are different questions, and until now only the
    first was asked. ``ExtractionLanePolicy.tests_for_lane`` answers the second:
    the lane's attributed tests, closed over the test-root modules they import,
    plus the ``conftest.py`` pytest loads whether or not anyone imports it.

    Shipping attribution alone would have delivered a platform repository with
    73 tests, no ``conftest.py`` to put its own package on ``sys.path``, and no
    ``support/central_pg_sqlite_shim`` for the tests that import it — a package
    that unpacks cleanly and cannot run a single test.
    """
    from fcc_test_contracts.common.extraction_lane_policy import ExtractionLanePolicy

    policy = ExtractionLanePolicy.from_manifest(manifest)
    if not policy.test_root or current_path != policy.test_root:
        # The declared root is the one the attribution rule uses. An entry
        # naming a different tree would silently ship a set nobody attributed.
        return [], [_issue(
            'lane_test_suite_root_mismatch', issue_path,
            f'lane_test_suite must name the declared test root '
            f'{policy.test_root!r}, got {current_path!r}',
        )]

    planned: list[dict] = []
    issues: list[dict] = []
    for rel in policy.tests_for_lane(PROJECT_ROOT, repo_name):
        source = PROJECT_ROOT / rel
        if not source.is_file():
            continue
        if _violates_forbidden(repo_name, rel, manifest):
            issues.append(_issue('forbidden_shared_path', issue_path, f'forbidden shared path: {rel}'))
            continue
        # ⚠️ A blind ``rel[len(test_root):]`` assumes every attributed path
        # lives under the test root, and ``tests_for_lane`` unions in
        # ``data_fixtures`` — which its own docstring describes as data "no
        # import statement can name", not as data that happens to sit under
        # ``tests/``. Declaring a fixture outside that root produced a silently
        # mangled destination rather than an error: measured 2026-09-09,
        # ``docs/platform/migrations/001_initial_central_db.sql`` was staged to
        # ``tests/latform/migrations/001_initial_central_db.sql`` (the slice ate
        # six characters of a path that never had the prefix). Nothing failed at
        # staging time; the box just could not find its data.
        #
        # A path under the test root keeps its old destination byte-for-byte; a
        # path outside it mirrors its repository-relative location, which is the
        # only layout a repository-relative reader can resolve.
        if rel.startswith(policy.test_root):
            target = (destination / rel[len(policy.test_root):]).as_posix()
        else:
            target = rel
        planned.append(_planned(entry, rel, target, source))

    # A test's import closure cannot see repository-local files it executes or
    # reads by path.  Let the policy derive those dependencies from the test
    # source, then mirror the repository-relative path so the delivered test
    # observes the same layout.  This is delivery closure, not ownership: a
    # support script may belong to another lane and is still valid in this
    # box when the attributed test needs it.
    planned_paths = set(already_planned)
    planned_paths.update(item['current_path'] for item in planned)
    for rel in policy.test_runtime_support_for_lane(
        PROJECT_ROOT,
        repo_name,
        already_planned=tuple(sorted(planned_paths)),
    ):
        source = PROJECT_ROOT / rel
        if not source.is_file() or rel in planned_paths:
            continue
        if _violates_forbidden(repo_name, rel, manifest):
            issues.append(_issue('forbidden_shared_path', issue_path, f'forbidden shared path: {rel}'))
            continue
        support_entry = dict(entry)
        support_entry['kind'] = 'runtime_support'
        planned.append(_planned(support_entry, rel, rel, source))
        planned_paths.add(rel)

    if not planned and not issues:
        issues.append(_issue(
            'empty_directory_relocation', issue_path,
            f'lane test suite staged no files: {current_path}',
        ))
    return planned, issues


def _expand_shared_kernel_closure(
    entry: dict,
    *,
    current_path: str,
    destination: Path,
    repo_name: str,
    manifest: dict,
    issue_path: str,
    consumed: tuple[str, ...],
) -> tuple[list[dict], list[dict]]:
    """Expand *the shared kernel this lane reaches* into files.

    ``ExtractionLanePolicy.shared_kernel_closure_for_lane`` owns the judgement,
    the same way ``tests_for_lane`` owns the test one. Nothing here re-derives
    it: the invariants compare the planned set against that method for **set
    equality**, and a second derivation would be free to disagree with the thing
    it is checked against.

    The delivered files keep the ``domain.*`` import name — they land under the
    package root unchanged, so no rewrite key exists for them and none should.
    A rename is owner-wide, and this owner ships only part of its layer.
    """
    from fcc_test_contracts.common.extraction_lane_policy import (
        SHARED_KERNEL_LANE, ExtractionLanePolicy,
    )

    policy = ExtractionLanePolicy.from_manifest(manifest)
    roots = tuple(
        rule.pattern for rule in policy.rules
        if rule.lane == SHARED_KERNEL_LANE and rule.pattern.endswith('/')
    )
    if current_path not in roots:
        # Naming a tree the manifest does not give to the shared kernel would
        # ship files under a claim their owner never made.
        return [], [_issue(
            'shared_kernel_root_mismatch', issue_path,
            f'shared_kernel_closure must name a declared shared-kernel root '
            f'{sorted(roots)!r}, got {current_path!r}',
        )]
    if not policy.may_depend_on(repo_name, SHARED_KERNEL_LANE):
        return [], [_issue(
            'shared_kernel_not_declared', issue_path,
            f'{repo_name} does not declare {SHARED_KERNEL_LANE} in depends_on',
        )]

    planned: list[dict] = []
    issues: list[dict] = []
    for rel in policy.shared_kernel_closure_for_lane(PROJECT_ROOT, repo_name, consumed):
        # ⚠️ The closure spans EVERY shared-kernel root, and this entry names
        # ONE of them. Without this filter the destination arithmetic below
        # (``rel[len(current_path):]``) is applied to paths that do not start
        # with ``current_path`` — it does not fail, it silently truncates by the
        # wrong number of characters and stages the file somewhere invented.
        # Invisible while the kernel had a single root; a defect the moment it
        # had two (2026-08-28, src/application/central_contract/).
        if not rel.startswith(current_path):
            continue
        source = PROJECT_ROOT / rel
        if not source.is_file():
            continue
        if _violates_forbidden(repo_name, rel, manifest):
            issues.append(_issue('forbidden_shared_path', issue_path, f'forbidden shared path: {rel}'))
            continue
        inner = rel[len(current_path):]
        planned.append(_planned(entry, rel, (destination / inner).as_posix(), source))

    if not planned and not issues:
        # A declared kernel that ships nothing is the false all-clear again: the
        # manifest says the lane receives its dependency and the package proves
        # otherwise, while every import of it still resolves nowhere.
        issues.append(_issue(
            'empty_directory_relocation', issue_path,
            f'shared kernel closure staged no files: {current_path}',
        ))
    return planned, issues


def _expand_directory_entry(
    entry: dict,
    *,
    current_path: str,
    destination: Path,
    repo_name: str,
    manifest: dict,
    issue_path: str,
) -> tuple[list[dict], list[dict]]:
    """Expand a tree relocation into one planned entry per file it carries.

    The filter is the manifest's own ``exclusions`` — read through
    ``ExtractionLanePolicy`` rather than restated here, because a second list of
    what-not-to-ship is exactly where the two would drift apart.

    ``out_of_scope_roots`` is deliberately *not* consulted. That list scopes
    **classification** ("the walk that asks who owns what starts here"), and it
    waives ``docs/`` as a whole while governance separately governs
    ``docs/platform/``. Reading it as a shipping filter emptied the migrations
    relocation to zero files — the ``empty_directory_relocation`` issue below is
    what caught it. A directory entry is an explicit statement that this tree
    leaves; only exclusions (build output, caches, installed dependencies) may
    subtract from it.
    """
    source_dir = PROJECT_ROOT / current_path.rstrip('/')
    if not source_dir.is_dir():
        return [], [_issue(
            'missing_source', issue_path, f'missing source directory: {current_path}',
        )]

    from fcc_test_contracts.common.extraction_lane_policy import ExtractionLanePolicy

    policy = ExtractionLanePolicy.from_manifest(manifest)
    planned: list[dict] = []
    issues: list[dict] = []
    for source in _walk_files(source_dir, policy):
        rel = source.relative_to(PROJECT_ROOT).as_posix()
        if policy.is_excluded(rel):
            continue
        # Forbidden first, and deliberately so. A provider-private path inside a
        # shared lane's tree is a *declaration* error, and the ownership skip
        # below would swallow it as "belongs to someone else" — leaving the
        # author with an empty-relocation notice instead of the sentence that
        # names what they did.
        if _violates_forbidden(repo_name, rel, manifest):
            issues.append(_issue('forbidden_shared_path', issue_path, f'forbidden shared path: {rel}'))
            continue
        owner = policy.lane_for_path(rel)
        if owner in policy.lanes and owner != repo_name:
            # A tree may contain a file the manifest gives to a different lane —
            # ``docs/api/`` is the contracts lane's, but the provider registry
            # inside it is the platform's. Carrying it here would ship one file
            # in two packages and let each believe it owns it. Skipping is not a
            # silent drop: the totality invariant proves every lane-owned file is
            # scheduled by *its* lane, so this file leaves with that one.
            continue
        inner = source.relative_to(source_dir).as_posix()
        planned.append(_planned(entry, rel, (destination / inner).as_posix(), source))

    if not planned and not issues:
        # A declared move that ships nothing is the false all-clear in miniature:
        # the manifest says the tree relocates and the package proves otherwise.
        issues.append(_issue(
            'empty_directory_relocation', issue_path,
            f'directory relocation staged no files: {current_path}',
        ))
    return planned, issues


def _walk_files(source_dir: Path, policy) -> list[Path]:
    """Files under ``source_dir`` in deterministic order, pruning excluded trees.

    Pruning is an optimisation, not the rule: ``is_excluded`` on the file is the
    authority (its globs already cross separators). Descending into an installed
    ``node_modules`` only to discard it costs tens of thousands of stats.
    """
    collected: list[Path] = []
    for current, dirnames, filenames in os.walk(source_dir):
        rel_dir = Path(current).relative_to(PROJECT_ROOT).as_posix()
        dirnames[:] = sorted(
            name for name in dirnames
            if not policy.is_excluded_dir(f'{rel_dir}/{name}')
        )
        collected.extend(Path(current) / name for name in sorted(filenames))
    return collected


def _planned(entry: dict, current_path: str, future_path: str, source: Path) -> dict:
    return {
        'current_path': current_path,
        'future_path': future_path,
        'kind': entry['kind'],
        'notes': entry['notes'],
        'byte_size': source.stat().st_size,
    }


def stage_extraction_package(plan: dict, target_root: Path) -> list[dict]:
    staged: list[dict] = []
    root = target_root.resolve(strict=False)
    import_rewrites = plan.get('import_rewrites') or {}
    for repo_name in plan['packages']:
        repo_root = root / repo_name
        _assert_under_root(repo_root, root)
        if repo_root.exists():
            shutil.rmtree(repo_root)
    layouts: dict[str, dict[str, str]] = {}
    for repo_name, entries in plan['packages'].items():
        for entry in entries:
            source = PROJECT_ROOT / entry['current_path']
            destination = root / repo_name / entry['future_path']
            _assert_under_root(destination, root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            rewrites = []
            if destination.suffix == '.py':
                rewrites = _rewrite_python_imports(destination, import_rewrites)
            layouts.setdefault(repo_name, {})[entry['current_path']] = (
                entry['future_path']
            )
            staged.append({
                'repository': repo_name,
                'source': entry['current_path'],
                'destination': str(destination),
                'import_rewrites': rewrites,
            })
    for repo_name, paths in layouts.items():
        _write_layout_record(root / repo_name, repo_name, paths)
    return staged


def _write_layout_record(
    repo_root: Path, repo_name: str, paths: dict[str, str],
) -> None:
    """Record what this staging run wrote where, inside the tree it wrote it to.

    The packager is the only party that *knows* the relocation — it just
    performed it — and until now it discarded that knowledge the moment the
    process exited. Everything downstream then had to model the move again:
    a delivered test looking for ``docs/platform/migrations`` has no way to
    learn that the box calls it ``migrations``, so it fails on a path that is
    present under another name. Measured 2026-08-15 on the delivered trees:
    363 reasons were exactly that — the largest class in which the file is
    *in the box*, and the only one no mechanism addressed. A larger raw
    class (433) was files genuinely absent, but that one splits into tests
    that should not have been in the box at all and artifacts a sibling
    lane owns: neither is repaired by knowing where something moved to.

    Written from ``plan['packages']`` entries as they are copied, so the record
    is total by construction rather than by anyone remembering to extend it —
    a file that shipped is a file that is in here. The consumer is
    :func:`application.common.tree_artifacts.resolve_repo_artifact`, and the
    absence of this file is what makes that function the identity in a
    monorepo checkout.
    """
    payload = {
        'schema': 1,
        'repository': repo_name,
        'paths': dict(sorted(paths.items())),
    }
    (repo_root / LAYOUT_RECORD_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=False) + '\n', encoding='utf-8',
    )


def _import_rewrite_map(manifest: dict, *, root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Module **and package** renames declared by every lane, longest key first.

    Scoping this to the packaged lane is what left a staged platform tree
    importing ``application.common.access_policy`` and
    ``application.headless.api_contracts`` — both of which SPLIT-1 moved into
    the contracts lane. Those imports are legitimate (platform depends on
    contracts); what was wrong was shipping them under a name that no longer
    exists. Longest key first so a file rename beats the package rename that
    contains it.

    Module keys stay a pure function of the manifest. **Package** keys cannot:
    ``from application.common import inbound_http`` names the *package*, so
    without a ``application.common`` key the delivered file keeps importing a
    name that does not exist. Deriving that key from the entries alone is
    **unsound** — a previous attempt read "every known module under the package
    moves", where *known* silently meant *has an entry*, and produced
    ``application -> fcc_test_platform``, which would rewrite every package's
    ``application.headless.*`` including the modules deliberately staying put.

    The sound condition needs the filesystem, and that is why this function
    takes a root: a package key is minted only when **every governed ``.py``
    file that actually exists under the directory has an entry** and those
    entries relocate it structure-preservingly under **one** destination.
    A directory with no governed file on disk mints nothing — vacuous truth is
    how a synthetic manifest would otherwise conjure a rename for a tree that
    does not exist.
    """
    rewrites: dict[str, str] = {}
    for repo in (manifest.get('repositories') or {}).values():
        for entry in repo.get('entries') or []:
            if entry.get('kind') not in PYTHON_RELOCATION_KINDS:
                continue
            current_module = _module_name_from_path(entry.get('current_path', ''))
            future_module = _module_name_from_path(entry.get('future_path', ''))
            if current_module and future_module and current_module != future_module:
                rewrites[current_module] = future_module
    rewrites.update(_package_rewrite_keys(manifest, root=root))
    return dict(sorted(rewrites.items(), key=lambda item: len(item[0]), reverse=True))


def _package_rewrite_keys(manifest: dict, *, root: Path) -> dict[str, str]:
    """Package-level renames whose totality the filesystem can vouch for.

    Two conditions, both necessary:

    * **totality** — every governed ``.py`` file present under the directory is
      named by an entry. One file staying put means the package still exists in
      the monorepo sense, so renaming the package would move imports that must
      not move.
    * **unanimity, structure-preserving** — every entry under the directory
      relocates ``<dir>/<rel>`` to ``<dest>/<rel>`` for a single ``<dest>``.
      Checking only that destinations "share a package" would accept a tree
      that shuffles modules between subpackages, and the rewritten import would
      point at the wrong one.
    """
    from fcc_test_contracts.common.extraction_lane_policy import ExtractionLanePolicy

    policy = ExtractionLanePolicy.from_manifest(manifest)
    by_dir: dict[str, dict[str, str]] = {}
    for repo in (manifest.get('repositories') or {}).values():
        for entry in repo.get('entries') or []:
            if entry.get('kind') not in PYTHON_RELOCATION_KINDS:
                continue
            current = str(entry.get('current_path', '')).replace('\\', '/')
            future = str(entry.get('future_path', '')).replace('\\', '/')
            if not current.endswith('.py') or not future.endswith('.py'):
                continue
            parent = current.rsplit('/', 1)[0] + '/'
            by_dir.setdefault(parent, {})[current] = future

    keys: dict[str, str] = {}
    for directory, entries in by_dir.items():
        present = _governed_python_files(root, directory, policy)
        if not present or not present <= set(entries):
            # No file on disk (nothing to vouch for) or a file staying put.
            continue
        destinations = set()
        for current, future in entries.items():
            if current not in present:
                continue
            inner = current[len(directory):]
            if not future.endswith('/' + inner):
                destinations.add(None)
                break
            destinations.add(future[: -len('/' + inner)])
        if len(destinations) != 1 or None in destinations:
            continue
        source_module = _module_name_from_path(directory)
        target_module = _module_name_from_path(destinations.pop() + '/')
        if source_module and target_module and source_module != target_module:
            keys[source_module] = target_module
    return keys


def _governed_python_files(root: Path, directory: str, policy) -> set[str]:
    """Governed ``.py`` paths directly under ``directory`` and below it.

    Recursive because the key being minted covers ``<pkg>.*``: a subpackage
    module that stays put would be rewritten by it just the same.
    """
    base = Path(root) / directory.rstrip('/')
    if not base.is_dir():
        return set()
    found: set[str] = set()
    for current, dirnames, filenames in os.walk(base):
        rel_dir = Path(current).relative_to(root).as_posix()
        dirnames[:] = sorted(
            name for name in dirnames
            if not policy.is_excluded_dir(f'{rel_dir}/{name}')
        )
        for name in filenames:
            if not name.endswith('.py'):
                continue
            rel = f'{rel_dir}/{name}'
            if policy.is_governed(rel) and not policy.is_excluded(rel):
                found.add(rel)
    return found


def _module_name_from_path(value: str) -> str:
    """Import name for a relocation path — a module for a file, a package prefix
    for a directory. Returns ``''`` when the path names no import at all."""
    text = str(value or '').strip().replace('\\', '/')
    path = _safe_future_path(text)
    if path is None:
        return ''
    if text.endswith('/'):
        parts = list(path.parts)
    elif path.suffix == '.py':
        parts = list(path.with_suffix('').parts)
    else:
        return ''
    if parts and parts[0] == 'src':
        parts = parts[1:]
    if not parts or any(not _is_python_identifier(part) for part in parts):
        return ''
    return '.'.join(parts)


def _is_python_identifier(value: str) -> bool:
    return value.isidentifier() and value not in {'', '.', '..'}


def _rewrite_python_imports(path: Path, import_rewrites: dict[str, str]) -> list[dict]:
    if not import_rewrites:
        return []
    text = path.read_text(encoding='utf-8')
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    lines = text.splitlines(keepends=True)
    applied: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            replacement = _rewrite_module_name(node.module, import_rewrites)
            if replacement != node.module:
                _replace_on_line(lines, node.lineno, node.module, replacement)
                applied.append({
                    'line': node.lineno,
                    'from': node.module,
                    'to': replacement,
                })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                replacement = _rewrite_module_name(alias.name, import_rewrites)
                if replacement != alias.name:
                    _replace_on_line(lines, node.lineno, alias.name, replacement)
                    applied.append({
                        'line': node.lineno,
                        'from': alias.name,
                        'to': replacement,
                    })

    if applied:
        path.write_text(''.join(lines), encoding='utf-8')
    return applied


def _rewrite_module_name(module: str, import_rewrites: dict[str, str]) -> str:
    for current, future in import_rewrites.items():
        if module == current:
            return future
        if module.startswith(current + '.'):
            return future + module[len(current):]
    return module


def _replace_on_line(lines: list[str], lineno: int, old: str, new: str) -> None:
    index = lineno - 1
    if 0 <= index < len(lines):
        lines[index] = lines[index].replace(old, new, 1)


def _safe_future_path(value: str) -> Path | None:
    text = str(value or '').strip().replace('\\', '/')
    if not text:
        return None
    path = Path(text)
    if path.is_absolute() or '..' in path.parts:
        return None
    return Path(*[part for part in path.parts if part not in {'', '.'}])


def _violates_forbidden(repo_name: str, current_path: str, manifest: dict) -> bool:
    """Whether a shared lane is trying to carry a provider-private path.

    The fragments are **repository-relative path prefixes** (``src/ui/``,
    ``src/reporting/``, ``src/sidebar.py``), so they are matched as prefixes.
    A plain substring test reads them as "these characters anywhere", which
    rejected ``apps/web/src/ui/Button.tsx`` — the platform's own React
    primitives — because the React app also happens to keep its UI under
    ``src/ui``. Nothing caught it before because nothing had ever staged
    ``apps/web``: the over-broad match only becomes reachable once a lane
    actually carries a second tree with a ``src/`` inside it.
    """
    if repo_name == 'fcc-unlicensed-headless':
        return False
    path = current_path.replace('\\', '/')
    return any(
        path.startswith(fragment)
        for fragment in (manifest.get('forbidden_shared_path_fragments') or ())
    )


def _assert_under_root(path: Path, root: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError(f'destination escapes target root: {path}') from exc


def _relative(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _issue(code: str, path: str, message: str) -> dict:
    return {'code': code, 'path': path, 'message': message}


def _lane_choices(manifest_path: Path = DEFAULT_MANIFEST) -> list[str]:
    """Lane names the manifest declares, for ``--repo``.

    Mirrors ``check_extraction_import_boundaries.lane_choices`` rather than
    restating the set: two hand-kept lists is how the fourth hardcoded triple
    survived a rule written specifically to remove the first three.
    """
    from fcc_test_contracts.common.extraction_lane_policy import ExtractionLanePolicy

    return sorted(ExtractionLanePolicy.from_path(manifest_path).lanes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Validate and stage headless extraction packages.')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    # Lane choices are **derived**, never typed here. A hardcoded triple is the
    # shape "Extraction Lane Set = Manifest 파생 SSOT" already outlawed in the
    # runner and its operator hints; this was the fourth copy, and it silently
    # refused `fcc-chamber-node` from the day that lane was declared. The
    # sibling checker script reads the same answer from the same policy.
    parser.add_argument('--repo', choices=_lane_choices(DEFAULT_MANIFEST))
    parser.add_argument('--copy-to', type=Path, help='optional staging root; files are copied under <root>/<repo>/')
    parser.add_argument('--output', type=Path, help='optional JSON plan output path')
    args = parser.parse_args(argv)

    plan = build_extraction_plan(manifest_path=args.manifest, repository=args.repo)
    if args.copy_to and plan['compatible']:
        plan['staged_files'] = stage_extraction_package(plan, args.copy_to)
    payload = json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + '\n', encoding='utf-8')
    else:
        print(payload)
    return 0 if plan['compatible'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
