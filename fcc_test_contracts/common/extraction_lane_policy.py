"""Repository-split lane ownership policy derived from the extraction manifest.

Single source of truth for two questions that the repository split depends on:

1. *Path ownership* — which repository lane owns a given source path?
2. *Namespace ownership* — which import prefixes may a lane reach, and which
   must it never reach?

Both answers are **derived** from
``docs/api/headless_contract_extraction_manifest.v1.json``. Consumers
(the import boundary checker, the totality invariants, the extraction runner)
must not keep their own copy of lane rules: a second hand-maintained list is
how the two sides silently contradicted each other before
(``fcc-unlicensed-headless`` had empty forbidden *and* empty allowed prefixes,
making its gate vacuous).

Dependency-free by contract: standard library only, so it stays importable from
CLI tooling, tests, and any lane's runtime. Sealed by
``tests/test_architecture_conformance.py::TestApplicationCommonPurity``.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
import fnmatch
import json
import os
from pathlib import Path
import sys

MANIFEST_VERSION = 2

#: Pseudo-lane for source that no single provider owns. Declared in the
#: manifest under its own top-level key rather than inside ``repositories``
#: because it is not an extraction target of its own.
SHARED_KERNEL_LANE = 'shared-kernel'

#: Classification outcomes that are *not* a lane.
EXCLUDED = 'excluded'
UNCLASSIFIED = 'unclassified'

#: Python source root inside the monorepo. Paths below it map onto import
#: namespaces by stripping this prefix; anything else claims no namespace.
PYTHON_SOURCE_ROOT = 'src/'

#: Why a test file resolves to no lane. The first two are *derived*
#: conclusions, not hand-maintained lists — a list of 175 file paths is the
#: shape this repository has repeatedly had to repay, because the next file
#: added is the one nobody adds to the list. The third is the one exception:
#: a test whose *content* audits the whole monorepo (it globs
#: ``PROJECT_ROOT / 'tests'`` or ``PROJECT_ROOT / 'scripts'`` directly) rather
#: than exercising one lane's source, even though its imports resolve to a
#: single lane. Import-based attribution cannot see that distinction — it is
#: a content question, and this manifest's whole design is to answer
#: ownership from imports only — so this one reason is *declared*, by path,
#: in ``governance.test_lane_attribution.monorepo_governance_tests``, with a
#: mandatory reason string per entry. See
#: :meth:`ExtractionLanePolicy.lane_for_test_file`.
TEST_RETAINED_NO_SOURCE = 'monorepo_test_no_lane_source'
TEST_RETAINED_CROSSES_LANES = 'monorepo_test_crosses_sibling_lanes'
TEST_RETAINED_GOVERNANCE = 'monorepo_test_repo_wide_governance'
TEST_RETAINED_REASONS = (
    TEST_RETAINED_NO_SOURCE, TEST_RETAINED_CROSSES_LANES, TEST_RETAINED_GOVERNANCE,
)

#: Manifest entry kinds that redirect an entry from "relocate this path" to
#: "derive what this lane needs". They are *manifest vocabulary*, so they live
#: beside the rest of it — the packager re-exports the names it has always
#: published, which keeps one definition and one binding.
LANE_TEST_SUITE_KIND = 'lane_test_suite'
SHARED_KERNEL_CLOSURE_KIND = 'shared_kernel_closure'

#: How an import edge is counted. **Neither value is a default**, because the
#: two questions this repository asks want opposite answers:
#:
#: * ``module_level`` — only imports executed by the mere act of importing a
#:   module. That is what "excluding this package must break the frozen build"
#:   means, and it is why a function-local import inside ``try/except`` does
#:   not count: it may never run.
#: * ``static`` — every import a static follower can see, function-local ones
#:   included. That is what Nuitka's import-following actually does, so it is
#:   what "is this module inside the delivered GUI artifact" means.
#:
#: Measured on this tree the two differ, and picking the wrong one is not a
#: rounding error: under ``module_level`` seeds the artifact model reports
#: ``main.py`` and ``test_runner_core`` as *absent from the GUI build*, which
#: would authorise shipping the GUI's own entry points out of this repository.
IMPORT_EDGE_MODULE_LEVEL = 'module_level'
IMPORT_EDGE_STATIC = 'static'
IMPORT_EDGE_RELATIONS: frozenset[str] = frozenset({
    IMPORT_EDGE_MODULE_LEVEL, IMPORT_EDGE_STATIC,
})

#: What "the files this lane consumes" means. The third argument of
#: :meth:`ExtractionLanePolicy.shared_kernel_closure_for_lane` changes its
#: answer, and **no record of this repository ever wrote down which basis it
#: used** — which is how three different sizes for the same set (22 / 27 / 41)
#: came to circulate as if they were measurements of the same thing.
#:
#: * ``delivery`` — the files this lane's box actually carries. The packager's
#:   question: what must travel so the box imports.
#: * ``ownership`` — every governed file the lane owns in the monorepo. The
#:   adjudication question: which kernel modules does this lane *read at all*,
#:   whether or not it is being extracted today.
#:
#: They are not interchangeable and they do not agree. A lane that is not an
#: extraction target has almost no delivery basis (its manifest declares no
#: box) while owning hundreds of files, so asking the delivery question about
#: it returns a number that looks like an answer and is not one.
CONSUMED_BASIS_DELIVERY = 'delivery'
CONSUMED_BASIS_OWNERSHIP = 'ownership'
CONSUMED_BASES: frozenset[str] = frozenset({
    CONSUMED_BASIS_DELIVERY, CONSUMED_BASIS_OWNERSHIP,
})


class UnknownImportEdgeRelation(ValueError):
    """An edge relation outside :data:`IMPORT_EDGE_RELATIONS` was requested.

    Loud rather than defaulted. A default here would silently answer a
    different question than the caller asked, and the caller would have no way
    to notice — the closure returns a plausible set either way.
    """


class UnknownConsumedBasis(ValueError):
    """A consumption basis outside :data:`CONSUMED_BASES` was requested.

    Same reasoning as :class:`UnknownImportEdgeRelation`, and the same history
    behind it: an unlabelled basis is exactly what produced 22 / 27 / 41.
    """

_WILDCARD_CHARS = ('*', '?', '[')

# A delivered test can drive a repository-local executable without importing
# it, and it can read a repository-local document without naming it in an
# import.  These are protocol shapes, not repository paths: the policy derives
# the actual files from the test AST and the concrete tree.
_TEST_RUNTIME_LAUNCHERS = frozenset({'Popen', 'call', 'check_call', 'check_output', 'run'})
_TEST_RUNTIME_READERS = frozenset({'open', 'read_bytes', 'read_text'})


@dataclass(frozen=True)
class OwnershipRule:
    """One path-ownership claim: a directory prefix, a glob, or a single file."""

    pattern: str
    lane: str
    notes: str = ''

    @property
    def is_glob(self) -> bool:
        return any(ch in self.pattern for ch in _WILDCARD_CHARS)

    @property
    def specificity(self) -> int:
        """Literal characters before the first wildcard.

        Longest-specificity-wins, the same disambiguation routing tables and
        ``.gitignore`` use. A file rule always beats the directory rule that
        contains it because its literal prefix is strictly longer.
        """
        if not self.is_glob:
            return len(self.pattern)
        cut = min(
            (self.pattern.index(ch) for ch in _WILDCARD_CHARS if ch in self.pattern),
            default=len(self.pattern),
        )
        return cut

    def matches(self, rel_path: str) -> bool:
        if self.is_glob:
            return fnmatch.fnmatch(rel_path, self.pattern)
        if self.pattern.endswith('/'):
            return rel_path.startswith(self.pattern)
        return rel_path == self.pattern


@dataclass(frozen=True)
class ClassificationReport:
    """Result of classifying a tree against the manifest's ownership rules."""

    counts: dict[str, int]
    unclassified: tuple[str, ...]
    excluded: tuple[str, ...]
    #: Why test files resolved to no lane, keyed by :data:`TEST_RETAINED_REASONS`.
    #: Carried so "no lane owns it" and "nobody looked" stay distinguishable.
    test_retained: dict[str, int] = field(default_factory=dict)

    @property
    def unclassified_count(self) -> int:
        return len(self.unclassified)


#: Dispositions a declared composition-root crossing may carry — what happens
#: to that site when the lanes become separate repositories. Closed on purpose:
#: an unknown token is red rather than silently tolerated, and every token here
#: is exercised by at least one real site. ``same_lane_after_reowning`` was in
#: the first draft of this axis and was deleted when measurement refuted it —
#: re-owning either chamber adapter *raises* the reverse pair, so "re-declare
#: ownership, no code change" was true of no candidate.
CROSSING_DISPOSITIONS: frozenset[str] = frozenset({
    'redundant_today',
    'reowning_blocked_by_residual',
    'root_to_root',
    'supplied_by_target_repo',
    'fetched_over_contract',
    'decided_repair_pending',
    'split_blocker_undecided',
})

#: Dispositions that record debt rather than a settled design. Their counts are
#: budgeted in the manifest and judged by equality, so neither can grow without
#: an explicit edit a reviewer sees.
#:
#: ``decided_repair_pending`` and ``split_blocker_undecided`` are deliberately
#: **separate** tokens. Collapsing them would let a ledger keep saying "waiting
#: for the operator" after the operator has answered — the stale-prescription
#: failure this repository keeps paying for. One means *nobody has decided*,
#: the other means *someone decided and the code has not caught up*, and only
#: the second can be worked on today.
CROSSING_DEBT_DISPOSITIONS: frozenset[str] = frozenset({
    'redundant_today',
    'decided_repair_pending',
    'split_blocker_undecided',
})

#: Dispositions whose claim the gate **executes**. Named as a set rather than
#: left to prose because the prose got it wrong once already (a manifest note
#: said "four of the six" when the vocabulary has seven), and because the
#: complement below has to be derivable rather than remembered.
EXECUTED_CROSSING_DISPOSITIONS: frozenset[str] = frozenset({
    'redundant_today',
    'reowning_blocked_by_residual',
    'root_to_root',
})

#: Dispositions whose correctness **no gate checks** — derived, never written by
#: hand, so a new token is announced as unverified instead of silently
#: inheriting the confidence of the three that are.
#:
#: This constant exists because an adversarial review demonstrated the gap
#: rather than argued it: swapping ``supplied_by_target_repo`` with
#: ``fetched_over_contract`` on two real sites left every assertion green, as
#: did replacing every ``reason`` with a sentence that is simply false. The
#: minimum length below stops ``"x"``; nothing stops a fluent lie. Saying so is
#: the same discipline ``self_audit_message.VALUE_AXIS_LIMITATION`` applies to
#: its own fifteen unchecked rows — a partial gate that stays quiet about its
#: edges reads as full verification.
UNVERIFIED_CROSSING_DISPOSITIONS: frozenset[str] = frozenset(
    CROSSING_DISPOSITIONS - EXECUTED_CROSSING_DISPOSITIONS
)

#: A reason shorter than this is not a reason. Not a style rule: the axis exists
#: because an unreasoned exemption is invisible, and ``"x"`` is an unreasoned
#: exemption that satisfies "non-empty". It cannot distinguish a true
#: explanation from a false one — see :data:`UNVERIFIED_CROSSING_DISPOSITIONS`.
MINIMUM_CROSSING_REASON_LENGTH = 40


@dataclass(frozen=True)
class CompositionRootCrossing:
    """One declared cross-lane import inside a declared composition root.

    ``composition_roots`` on its own is a *file-level* exemption: the whole
    file leaves :meth:`ExtractionLanePolicy.cross_lane_imports`, so a declared
    root can accumulate an unbounded and unreasoned set of crossings and no
    axis asks. This record is the site-level replacement — the target module,
    why it is there, and what becomes of it at split time.

    ``replacement``/``residual``/``decision_ref`` are the evidence each
    disposition owes; which one is mandatory is decided by
    :meth:`missing_evidence`, so the obligation lives beside the vocabulary
    rather than in whichever test happens to look.
    """

    module: str
    disposition: str
    reason: str
    #: ``redundant_today`` only — the lane-neutral module that already exists.
    replacement: str = ''
    #: ``redundant_today`` only — the name the crossing import binds. Without it
    #: the replacement claim is satisfiable by *any* already-imported module in
    #: an allowed lane, and the resulting sentence ("deleting this import is
    #: safe because that other one is already there") is nonsense that would
    #: ``NameError`` at run time. An adversarial review demonstrated exactly
    #: that, so the symbol is declared and the gate checks the replacement
    #: actually defines it.
    symbol: str = ''
    #: ``reowning_blocked_by_residual`` only — the imports that must close
    #: before re-owning the target actually lowers anything.
    residual: tuple[str, ...] = ()
    #: ``split_blocker_undecided`` and ``decided_repair_pending`` — where the
    #: decision (pending or taken) is recorded.
    decision_ref: str = ''
    #: ``decided_repair_pending`` only, and **forbidden** on
    #: ``split_blocker_undecided``: the ISO date the operator decided. The two
    #: tokens otherwise differ only by spelling, so swapping a site between them
    #: was invisible — and that distinction covers most of the debt. A required
    #: field on one and a forbidden field on the other makes the swap structural
    #: rather than orthographic.
    decided_on: str = ''

    @classmethod
    def from_dict(cls, payload: dict) -> 'CompositionRootCrossing':
        return cls(
            module=str(payload.get('module', '')),
            disposition=str(payload.get('disposition', '')),
            reason=str(payload.get('reason', '')),
            replacement=str(payload.get('replacement', '')),
            symbol=str(payload.get('symbol', '')),
            residual=tuple(payload.get('residual') or ()),
            decision_ref=str(payload.get('decision_ref', '')),
            decided_on=str(payload.get('decided_on', '')),
        )

    @property
    def is_debt(self) -> bool:
        return self.disposition in CROSSING_DEBT_DISPOSITIONS

    def missing_evidence(self) -> tuple[str, ...]:
        """Field names this disposition requires and this record does not carry.

        Returned rather than raised so a caller can report every offending site
        at once instead of stopping at the first.
        """
        missing: list[str] = []
        if not self.module:
            missing.append('module')
        if len(self.reason.strip()) < MINIMUM_CROSSING_REASON_LENGTH:
            missing.append('reason')
        if self.disposition == 'redundant_today':
            if not self.replacement:
                missing.append('replacement')
            if not self.symbol:
                missing.append('symbol')
        if self.disposition == 'reowning_blocked_by_residual' and not self.residual:
            missing.append('residual')
        if (
            self.disposition in ('split_blocker_undecided', 'decided_repair_pending')
            and not self.decision_ref.strip()
        ):
            missing.append('decision_ref')
        if self.disposition == 'decided_repair_pending' and not self.decided_on.strip():
            missing.append('decided_on')
        return tuple(missing)

    def forbidden_evidence(self) -> tuple[str, ...]:
        """Field names this disposition must NOT carry.

        The mirror of :meth:`missing_evidence`, and it exists for one token
        pair: ``decided_repair_pending`` and ``split_blocker_undecided`` differ
        only by spelling otherwise, so moving a site between them changed
        nothing a gate could see — while that very distinction is what the
        ledger uses to say which debt is workable today. Requiring
        ``decided_on`` on one and forbidding it on the other makes the swap
        structural.
        """
        forbidden: list[str] = []
        if self.disposition == 'split_blocker_undecided' and self.decided_on.strip():
            forbidden.append('decided_on')
        if self.disposition != 'redundant_today' and (self.replacement or self.symbol):
            forbidden.extend(
                name for name, value in (('replacement', self.replacement),
                                         ('symbol', self.symbol)) if value
            )
        if self.disposition != 'reowning_blocked_by_residual' and self.residual:
            forbidden.append('residual')
        return tuple(forbidden)


@dataclass(frozen=True)
class ExtractionLanePolicy:
    """Lane ownership resolved from a parsed manifest document."""

    lanes: tuple[str, ...]
    governed_roots: tuple[str, ...]
    governed_suffixes: tuple[str, ...]
    out_of_scope_roots: tuple[OwnershipRule, ...]
    exclusions: tuple[OwnershipRule, ...]
    rules: tuple[OwnershipRule, ...]
    depends_on: dict[str, tuple[str, ...]]
    forbidden_external: dict[str, tuple[str, ...]]
    package_names: dict[str, str]
    composition_roots: tuple[str, ...]
    cross_lane_import_baseline: dict[str, int]
    unclassified_baseline: int
    test_root: str
    #: Declared exceptions to import-based test attribution — paths (relative
    #: to the repo root) of tests whose *content* audits the whole monorepo
    #: rather than one lane's source, mapped to a mandatory reason. See
    #: :data:`TEST_RETAINED_GOVERNANCE`.
    test_monorepo_governance: dict[str, str] = field(default_factory=dict)
    #: Declared non-Python test-root data a lane's delivered suite needs —
    #: fixtures no ``import`` statement names, so :meth:`tests_for_lane`'s
    #: AST closure cannot discover them on its own. Lane name -> paths
    #: (relative to the repo root, under ``test_root``). See
    #: ``governance.test_lane_attribution.data_fixtures`` and its
    #: ``delivery_non_python_note``: "a lane that comes to need golden data
    #: will need a declared rule, not a silent one."
    test_data_fixtures: dict[str, tuple[str, ...]] = field(default_factory=dict)
    _namespaces: dict[str, tuple[str, ...]] = field(default_factory=dict)
    _current_namespaces: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Entry-point module identities bound to a concrete tree by
    #: :meth:`bound_to`. Empty (the dataclass default) on every instance
    #: :meth:`from_manifest`/:meth:`from_path` produce directly — binding is
    #: opt-in, so a caller that never binds sees exactly today's behavior.
    _entry_point_index: dict[str, str] = field(default_factory=dict)
    #: Per-site record of what each declared composition root reaches across a
    #: lane boundary, keyed by the root's repo-relative path. Every path in
    #: :attr:`composition_roots` is a key — including the six that reach
    #: nothing, so "zero crossings" is *declared* rather than merely unmeasured.
    #: Appended at the end of the field list so existing positional
    #: construction keeps its argument order.
    composition_root_crossings: dict[str, tuple[CompositionRootCrossing, ...]] = field(
        default_factory=dict
    )
    #: Declared ceilings for :data:`CROSSING_DEBT_DISPOSITIONS`, judged by
    #: equality against counts derived from
    #: :attr:`composition_root_crossings`. Kept as its own declaration on
    #: purpose: a budget derived from the thing it is compared against cannot
    #: fail.
    composition_root_crossing_debt_budget: dict[str, int] = field(default_factory=dict)

    # ---------------------------------------------------------------- loading

    @classmethod
    def from_manifest(cls, manifest: dict) -> 'ExtractionLanePolicy':
        version = manifest.get('manifest_version')
        if version != MANIFEST_VERSION:
            raise ValueError(
                f'extraction manifest must be version {MANIFEST_VERSION}, got {version!r}'
            )

        governance = manifest.get('governance') or {}
        repositories = manifest.get('repositories') or {}
        shared = manifest.get('shared_kernel') or {}

        lanes = tuple(sorted(repositories))
        rules: list[OwnershipRule] = []
        namespaces: dict[str, tuple[str, ...]] = {}
        depends_on: dict[str, tuple[str, ...]] = {}
        forbidden_external: dict[str, tuple[str, ...]] = {}

        owners: list[tuple[str, dict]] = [
            *repositories.items(),
            (SHARED_KERNEL_LANE, shared),
        ]
        current_namespaces: dict[str, tuple[str, ...]] = {}
        for lane, spec in owners:
            lane_rules = _rules_for_owner(lane, spec)
            rules.extend(lane_rules)
            package_name = (manifest.get('package_names') or {}).get(lane, '')
            namespaces[lane] = _published_namespaces(
                lane_rules, spec, package_name=package_name
            )
            current_namespaces[lane] = _current_namespaces(lane_rules)
            depends_on[lane] = tuple(spec.get('depends_on') or ())
            forbidden_external[lane] = tuple(spec.get('forbidden_external') or ())

        exclusions = tuple(
            OwnershipRule(pattern=item['path'], lane=EXCLUDED, notes=item.get('reason', ''))
            for item in (manifest.get('exclusions') or [])
        )
        out_of_scope = tuple(
            OwnershipRule(pattern=item['path'], lane=EXCLUDED, notes=item.get('reason', ''))
            for item in (governance.get('out_of_scope_roots') or [])
        )

        return cls(
            lanes=lanes,
            governed_roots=tuple(governance.get('governed_roots') or ()),
            governed_suffixes=tuple(governance.get('governed_suffixes') or ()),
            out_of_scope_roots=out_of_scope,
            exclusions=exclusions,
            rules=tuple(rules),
            depends_on=depends_on,
            forbidden_external=forbidden_external,
            package_names=dict(manifest.get('package_names') or {}),
            composition_roots=tuple(governance.get('composition_roots') or ()),
            composition_root_crossings={
                root: tuple(
                    CompositionRootCrossing.from_dict(item) for item in (sites or ())
                )
                for root, sites in (
                    governance.get('composition_root_crossings') or {}
                ).items()
            },
            composition_root_crossing_debt_budget=dict(
                governance.get('composition_root_crossing_debt_budget') or {}
            ),
            cross_lane_import_baseline=dict(
                governance.get('cross_lane_import_baseline') or {}
            ),
            unclassified_baseline=int(governance.get('unclassified_baseline', 0)),
            test_root=str(
                (governance.get('test_lane_attribution') or {}).get('root', '')
            ),
            test_monorepo_governance=dict(
                (governance.get('test_lane_attribution') or {}).get(
                    'monorepo_governance_tests'
                ) or {}
            ),
            test_data_fixtures={
                lane: tuple(paths)
                for lane, paths in (
                    (governance.get('test_lane_attribution') or {}).get(
                        'data_fixtures'
                    ) or {}
                ).items()
            },
            _namespaces=namespaces,
            _current_namespaces=current_namespaces,
        )

    @classmethod
    def from_path(cls, manifest_path: Path) -> 'ExtractionLanePolicy':
        return cls.from_manifest(json.loads(Path(manifest_path).read_text(encoding='utf-8')))

    # ------------------------------------------------------- path ownership

    @property
    def owners(self) -> tuple[str, ...]:
        """Lanes plus the shared kernel — every owner that can hold a path."""
        return (*self.lanes, SHARED_KERNEL_LANE)

    def is_governed(self, rel_path: str) -> bool:
        if self.governed_suffixes and not rel_path.endswith(self.governed_suffixes):
            return False
        return any(_prefix_matches(rel_path, root) for root in self.governed_roots)

    def is_excluded(self, rel_path: str) -> bool:
        return any(rule.matches(rel_path) for rule in self.exclusions)

    def is_excluded_dir(self, rel_dir: str) -> bool:
        """Whether a directory is wholly excluded, so the walk can prune it.

        A ``dir/*`` exclusion excludes the directory itself; testing the
        directory against the file pattern alone would miss it and force the
        walk to descend anyway.
        """
        return self._dir_matches(rel_dir, self.exclusions)

    def should_prune_dir(self, rel_dir: str) -> bool:
        """Whether a walk may skip this directory entirely.

        Covers both explicit exclusions and roots governance declares
        out of scope. Descending into the virtualenv and then discarding it is
        how the old checker came to read 8,453 files and report a PySide6
        deploy template's syntax error as a boundary violation.
        """
        rel_dir = rel_dir.replace('\\', '/').strip('/')
        if self._dir_matches(rel_dir, self.exclusions):
            return True
        return any(
            _prefix_matches(rel_dir, rule.pattern) or rel_dir == rule.pattern.rstrip('/')
            for rule in self.out_of_scope_roots
        )

    def _dir_matches(self, rel_dir: str, rules: tuple[OwnershipRule, ...]) -> bool:
        rel_dir = rel_dir.replace('\\', '/').strip('/')
        for rule in rules:
            pattern = rule.pattern
            if rule.matches(rel_dir) or rule.matches(rel_dir + '/'):
                return True
            if pattern.endswith('/*') and fnmatch.fnmatch(rel_dir, pattern[:-2]):
                return True
        return False

    def lane_for_path(self, rel_path: str) -> str:
        """Resolve the owner of ``rel_path``.

        Returns a lane name, :data:`SHARED_KERNEL_LANE`, :data:`EXCLUDED`, or
        :data:`UNCLASSIFIED`. Exclusions are checked first so an explicitly
        excluded path never silently inherits a broad directory claim.
        """
        rel_path = rel_path.replace('\\', '/')
        if self.is_excluded(rel_path):
            return EXCLUDED
        best: OwnershipRule | None = None
        for rule in self.rules:
            if not rule.matches(rel_path):
                continue
            if best is None or rule.specificity > best.specificity:
                best = rule
        return best.lane if best else UNCLASSIFIED

    def ambiguous_rules(self) -> tuple[tuple[OwnershipRule, OwnershipRule], ...]:
        """Rule pairs from different owners that tie on specificity.

        A tie means ``lane_for_path`` would depend on manifest ordering, which
        is not an ownership decision anybody made. The manifest must be
        unambiguous; this is asserted by the invariants.
        """
        clashes: list[tuple[OwnershipRule, OwnershipRule]] = []
        for i, left in enumerate(self.rules):
            for right in self.rules[i + 1:]:
                if left.lane == right.lane:
                    continue
                if left.pattern == right.pattern or left.specificity == right.specificity:
                    if _rules_can_overlap(left, right):
                        clashes.append((left, right))
        return tuple(clashes)

    def entry_point_roots(self, root: Path) -> tuple[str, ...]:
        """Governed roots the tree itself proves are real Python packages.

        Neither :data:`PYTHON_SOURCE_ROOT` (already has its own namespace
        rule) nor the test root (owned by :meth:`lane_for_test_file`, a
        different question) qualify. Of what remains, a root counts only
        when the tree ships a top-level ``__init__.py`` under it — the same
        evidence ``contract_cli.sibling_module`` already reads to pick "this
        world's canonical name". This is a *derivation*, not a list: a
        governed root added tomorrow is included or excluded by the same
        rule automatically.

        Measured against the real tree: of nine governed roots, only
        ``scripts/`` has a top-level ``__init__.py``. The others carry no
        ``.py`` at all, or — ``apps/web/`` — a single file whose name
        (``run-test-plan-generation-worker.py``) is not a legal module
        identifier. Minting a namespace for those would be exactly the
        fabricated rule :func:`_namespace_from_path` already refuses for
        ``docs/`` and ``apps/web/``; this method must not open that door by
        another name.
        """
        root = Path(root)
        excluded = {PYTHON_SOURCE_ROOT, self.test_root}
        found: list[str] = []
        for governed in self.governed_roots:
            if governed in excluded:
                continue
            stripped = governed.rstrip('/')
            if not stripped:
                continue
            if (root / stripped / '__init__.py').is_file():
                found.append(f'{stripped}/')
        return tuple(sorted(found))

    def entry_point_module_index(self, root: Path) -> dict[str, str]:
        """Import name (both dotted-under-root and bare) -> repo-relative path.

        The sibling of :meth:`test_module_index`, over
        :meth:`entry_point_roots` instead of the test root. Existence is the
        whole anti-fabrication mechanism here: only files and directories
        actually found under ``root`` produce a key, so ``pandas`` or a
        never-copied ``scripts.foo`` can never appear — the false-resolution
        defect this axis exists to close.

        Both identities are indexed to the *same path*, which is why this is
        not an ownership decision: ``scripts/dev_seed/`` ships no
        ``__init__.py`` (a PEP 420 namespace package, importable once
        ``scripts/`` itself is on ``sys.path`` — exactly what
        ``tests/conftest.py`` does), so ``import dev_seed`` and
        ``import scripts.dev_seed`` both resolve here, both to
        ``scripts/dev_seed/``, and therefore both to whatever lane
        :meth:`lane_for_path` gives that path. Two names, one file, one
        owner — never two.
        """
        root = Path(root)
        index: dict[str, str] = {}
        for entry_root in self.entry_point_roots(root):
            base = root / entry_root.rstrip('/')
            prefix = entry_root.rstrip('/').replace('/', '.')
            if not base.is_dir():
                continue
            for current, dirnames, filenames in os.walk(base):
                current_path = Path(current)
                rel_dir = current_path.relative_to(root).as_posix()
                dirnames[:] = sorted(
                    name for name in dirnames
                    if not self.is_excluded_dir(f'{rel_dir}/{name}')
                )
                rel_to_base = current_path.relative_to(base)
                dir_parts = () if rel_to_base == Path('.') else rel_to_base.parts
                if dir_parts:
                    bare = '.'.join(dir_parts)
                    rel = current_path.relative_to(root).as_posix() + '/'
                    index.setdefault(bare, rel)
                    index.setdefault(f'{prefix}.{bare}', rel)
                for name in sorted(filenames):
                    if not name.endswith('.py') or name == '__init__.py':
                        continue
                    parts = (*dir_parts, name[: -len('.py')])
                    bare = '.'.join(parts)
                    rel = (current_path / name).relative_to(root).as_posix()
                    index.setdefault(bare, rel)
                    index.setdefault(f'{prefix}.{bare}', rel)
        return index

    def bound_to(self, root: Path) -> 'ExtractionLanePolicy':
        """Bind entry-point module identities to a concrete tree.

        Idempotent (:func:`dataclasses.replace` over a freshly recomputed
        index — binding twice to the same root produces the same policy) and
        additive: an unbound policy carries an empty index, which makes
        :meth:`lane_for_module`'s fallback and :meth:`namespaces`'s filter
        both no-ops, so every existing caller that never binds keeps
        behaving exactly as it did before this axis existed. Binding target
        is deliberately the *monorepo* root, not a staged tree — "who owns
        ``scripts.foo``" is a monorepo ownership question, and the manifest
        describes the monorepo.
        """
        return replace(self, _entry_point_index=self.entry_point_module_index(root))

    def ambiguous_module_names(self, root: Path) -> tuple[str, ...]:
        """Bare entry-point names this policy would resolve two ways.

        :meth:`entry_point_module_index` gives every entry-point file two
        identities, and the bare one is a plain word — ``reporting``,
        ``auth`` — with no ``scripts.`` prefix marking where it came from.
        That is exactly the shape of name that can silently mean something
        else: a *different* lane's ``src/``-derived namespace, or a stdlib
        module. Both are reported; neither is inferred away.

        Walking the real tree's entry-point files — not a hand-listed set —
        so a new bare name added tomorrow is checked automatically. The
        invariant this seals is ``== ()``: today's tree ties zero names,
        which is a **fact about the tree**, not a guarantee this method
        gives for free — see the synthetic counterfactual coverage for a
        case where it does not stay empty.
        """
        root = Path(root)
        index = self.entry_point_module_index(root)
        entry_prefixes = tuple(
            r.rstrip('/').replace('/', '.') for r in self.entry_point_roots(root)
        )
        stdlib = set(sys.stdlib_module_names) | set(sys.builtin_module_names)

        ambiguous: list[str] = []
        for name in sorted(index):
            if any(name == p or name.startswith(p + '.') for p in entry_prefixes):
                continue  # dotted-under-root identity, not a bare name
            if name in stdlib:
                ambiguous.append(name)
                continue
            entry_owner = self.lane_for_path(index[name])
            for owner in self.owners:
                if owner == entry_owner:
                    continue
                if name in self.current_namespaces(owner):
                    ambiguous.append(name)
                    break
        return tuple(ambiguous)

    # -------------------------------------------------------- test ownership

    def is_test_path(self, rel_path: str) -> bool:
        return bool(self.test_root) and _prefix_matches(
            rel_path.replace('\\', '/'), self.test_root
        )

    def lane_for_test_file(self, path: Path) -> tuple[str, str]:
        """Owner of a test file, plus the reason when it has none.

        A test belongs to the lane owning **the source it exercises**, and the
        only machine-readable evidence of that is what it imports. Owners are
        reduced along ``depends_on``: a test touching the contracts lane *and*
        the platform lane exercises the platform, because the platform is the
        thing that depends on contracts.

        Three outcomes are not lanes, and all three are conclusions rather than
        omissions:

        * **no first-party import** — the file exercises the repository itself
          (documentation ownership, CI cost policy, the audit gates) or is
          shared harness (``tests/fakes``, fixtures, golden data). It travels
          with no lane because it tests no lane's source.
        * **two sibling lanes** — it reaches both the platform and the provider,
          which no single extracted repository will contain, so it cannot travel
          with either.
        * **declared monorepo governance** — its imports resolve to exactly one
          lane, but its *content* audits the whole repository tree (a
          ``PROJECT_ROOT``-relative glob over ``tests/`` or ``scripts/``), which
          import-based attribution cannot see. Measured: shipping
          ``benchmark_harness.py`` to the contracts lane (2026-08-13) pulled two
          such audits into that lane's delivery closure and both failed running
          standalone in the staged package — one asserts non-vacuity over
          ``scripts/bench_*.py``, a glob no single lane's ``scripts/`` subset
          satisfies. Declared in
          ``governance.test_lane_attribution.monorepo_governance_tests`` with a
          mandatory reason, checked before import resolution so a declared file
          never enters the transitive closure through anything it imports.
        """
        posix = path.as_posix().replace('\\', '/')
        for declared in self.test_monorepo_governance:
            declared_posix = declared.replace('\\', '/')
            if posix == declared_posix or posix.endswith('/' + declared_posix):
                return EXCLUDED, TEST_RETAINED_GOVERNANCE
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError, OSError):
            # A file this walk cannot parse is test data or a deliberate
            # syntax fixture, not a lane's source.
            return EXCLUDED, TEST_RETAINED_NO_SOURCE

        owners = {
            self.lane_for_module(module) for module in _imported_modules(tree)
        } - {UNCLASSIFIED, EXCLUDED}
        if not owners:
            return EXCLUDED, TEST_RETAINED_NO_SOURCE

        downstream = {
            owner for owner in owners
            if not any(
                other != owner and owner in self._dependency_closure(other)
                for other in owners
            )
        }
        if len(downstream) == 1:
            return next(iter(downstream)), ''
        return EXCLUDED, TEST_RETAINED_CROSSES_LANES

    def test_module_index(self, root: Path) -> dict[str, str]:
        """Import name → path, for every Python file under the test root.

        Built so the delivery closure can ask "does this import name a *test
        root* module?" without guessing.

        **The suite spells the same module two ways and the index must answer to
        both.** Names rooted at the test root are how the harness is usually
        imported (``from support.parity import …``, ``from fakes import …``),
        and that was the only spelling this index published until 2026-08-26.
        The other one is rooted at the repository (``from tests.fakes.X import
        …``) and it is equally valid Python: the repository root is on the path
        in the monorepo and at the box root in a delivered tree, so both resolve
        in both places. The index, however, matched by dotted prefix — and
        ``fakes.foo`` is not a prefix of ``tests.fakes.foo`` — so every import
        written the second way resolved to **nothing**, and the closure shipped
        the test without the module it imports.

        Measured on the day it was fixed: 37 test-root files carried an import
        the index could not see and **13 of them were attributed to an
        extraction target**. Most had survived only because some *other* test
        happened to spell the same module the visible way, which is the
        "delivery by luck" this policy's own delivery docstring already names.
        The first module reached only by the invisible spelling took the whole
        platform box down — ``tests/fakes/`` was not in the delivered tree at
        all, and one ``ModuleNotFoundError`` at collection time took 1,470
        collected tests to 0.

        The alias prefix is **derived from** :attr:`test_root`, never spelled:
        rename the test root in the manifest and both namespaces follow.

        Aliases never shadow a test-root-rooted name. The two spellings name the
        same file everywhere they overlap today — :meth:`shadowed_test_module_names`
        exists to say so out loud rather than leave it to walk order — and if a
        genuine collision is ever introduced, the primary spelling wins and that
        method names the pair.

        ⚠️ **The test root's own ``__init__.py`` is deliberately not published
        under either spelling**, and the reason was measured rather than
        reasoned. Publishing it gives the longest-prefix matcher something to
        shorten to: ``from tests.support import api_surface_boundary`` also
        names the intermediate ``tests.support``, which has no file of its own,
        so the match fell back to ``tests`` and scheduled ``tests/__init__.py``
        into the contracts box. That file is one byte and looked harmless. It is
        not — a delivered box has its sibling lanes on ``PYTHONPATH``, and an
        ``__init__.py`` turns that sibling's ``tests/`` into a **regular**
        package, which terminates the search that a PEP 420 namespace package
        would otherwise have spread across both boxes. Measured: with the file
        shipped, the platform box could not import ``tests.fakes`` or
        ``tests.support.sample_inventory_central`` even though both were sitting
        in its own tree; deleting that one byte from the *other* box turned the
        same nine tests green. A module is published; a package marker that
        nobody imports for its contents is not.
        """
        index: dict[str, str] = {}
        aliases: dict[str, str] = {}
        for primary, alias, rel in self._test_module_names(root):
            if primary:
                index[primary] = rel
                aliases[alias] = rel
        for name, rel in aliases.items():
            index.setdefault(name, rel)
        return index

    def shadowed_test_module_names(self, root: Path) -> tuple[tuple[str, str, str], ...]:
        """Alias names that would have named a different file than the primary.

        Empty today and asserted empty, because a non-empty answer means one
        dotted name has two files behind it and the delivery closure would be
        picking by dictionary order. Reported rather than raised: the callers of
        :meth:`test_module_index` are gates, and a gate that cannot build its
        index says nothing at all about the tree it was asked to judge.
        """
        names = list(self._test_module_names(root))
        primary = {name: rel for name, _, rel in names if name}
        return tuple(sorted(
            (alias, primary[alias], rel)
            for _, alias, rel in names
            if primary.get(alias) not in (None, rel)
        ))

    def _test_module_names(self, root: Path):
        """``(test-root-rooted name, repository-rooted name, path)`` per file.

        One walk, one naming rule, two consumers. Splitting it in two is how the
        index and the collision report drift into disagreeing about which name
        belongs to which file — and the one that drifts is the report, because
        nothing reads it on the day it stops matching.

        The test-root-rooted name is empty for the test root's own
        ``__init__.py``: it has no module name under that spelling, and it is
        deliberately not published under the other one either — see
        :meth:`test_module_index` for the measurement behind that.
        """
        base = Path(root) / self.test_root.rstrip('/')
        if not self.test_root or not base.is_dir():
            return
        prefix = tuple(
            part for part in Path(self.test_root.rstrip('/')).parts if part
        )
        for path in _iter_files(Path(root), self):
            rel = path.relative_to(Path(root)).as_posix()
            if not self.is_test_path(rel) or path.suffix != '.py':
                continue
            parts = list(Path(rel[len(self.test_root):]).with_suffix('').parts)
            if parts and parts[-1] == '__init__':
                parts = parts[:-1]
            yield '.'.join(parts), '.'.join((*prefix, *parts)), rel

    def tests_for_lane(self, root: Path, lane: str) -> tuple[str, ...]:
        """Test-root files that must travel with ``lane``'s package.

        Attribution and delivery answer different questions, and only the first
        one was being asked. Attribution says *who owns* a test; delivery says
        *what must be in the box* for that test to run. Deriving the second from
        the first is the whole point of this method.

        The set is the lane's attributed tests, closed transitively over the
        test-root modules they import, plus ``conftest.py`` — which no file
        imports and pytest loads regardless, so it is named by the protocol
        that requires it rather than by a hand-maintained list.

        Without the closure, ``fcc-test-platform`` would ship 73 tests and
        neither the ``conftest.py`` that puts its package on ``sys.path`` nor
        the ``support/central_pg_sqlite_shim`` those tests import. Both resolve
        elsewhere under attribution: the conftest lands in the *provider* lane,
        and it lands there because one fixture happens to import a correction
        template helper. That is not an ownership decision anybody made.

        Binds :meth:`entry_point_module_index` to ``root`` itself, rather than
        trusting a caller to have bound it — a caller that forgot would
        silently get today's blind answer for any ``scripts/`` import an
        attributed test happens to make.

        Also unions in :attr:`test_data_fixtures` for ``lane`` — non-Python
        test-root data (e.g. an ``.xlsx`` a test reads at module scope) that
        no import statement can name, so the AST closure above cannot see it.
        Declared, not inferred: see ``delivery_non_python_note`` in the
        manifest.
        """
        root = Path(root)
        self = self.bound_to(root)
        index = self.test_module_index(root)
        by_path = {rel: name for name, rel in index.items()}

        pending = [
            rel for rel in sorted(by_path)
            if self.lane_for_test_file(root / rel)[0] == lane
        ]
        conftest = f'{self.test_root}conftest.py'
        if (root / conftest).is_file():
            pending.append(conftest)

        selected: set[str] = set()
        while pending:
            rel = pending.pop()
            if rel in selected:
                continue
            selected.add(rel)
            pending.extend(
                target
                for target in self._test_imports_of(root / rel, index, rel=rel)
                if target not in selected
            )
        selected.update(self.test_data_fixtures.get(lane, ()))
        return tuple(sorted(selected))

    def test_runtime_support_for_lane(
        self,
        root: Path,
        lane: str,
        already_planned: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        """Repository files a delivered lane's tests need at runtime.

        Test attribution is import-derived, but not every runtime dependency
        is an import.  Two legitimate shapes are visible in the test source:

        * a path passed to a process-launch API, such as a script under a
          concrete, tree-proven ``entry_point_root``; and
        * an ungoverned repository document read at the use site inside a test
          function.

        The paths are resolved from ``Path(__file__)`` expressions against the
        actual tree.  Source lookups are intentionally not carried here: a
        source path in a test is a relocation assumption, and the test should
        use the imported module or the layout record instead.  Likewise,
        module-level document constants are not promoted into a package: those
        are monorepo assertions that must remain visible as their existing
        delivered-test baseline, not silently become lane assets.

        ``already_planned`` lets the package builder subtract files that the
        manifest already schedules.  Delivery closure may therefore carry a
        support file owned by another lane without changing that file's
        ownership decision; the returned set only says what this box needs.
        """
        root = Path(root)
        self = self.bound_to(root)
        # The dependency-free contracts lane is intentionally self-contained;
        # its repository-wide subprocess probes are governance checks, not
        # deliverable runtime closure. A lane with the declared shared-kernel
        # dependency is a delivery surface and may carry concrete runtime
        # support discovered from its own tests.
        if not self.may_depend_on(lane, SHARED_KERNEL_LANE):
            return ()
        planned = set(already_planned)
        selected: set[str] = set()
        for rel in self.tests_for_lane(root, lane):
            path = root / rel
            if path.suffix != '.py' or not path.is_file():
                continue
            selected.update(self._test_runtime_support_of(root, path, lane=lane))
        return tuple(sorted(selected - planned))

    def _test_runtime_support_of(self, root: Path, path: Path, *, lane: str) -> set[str]:
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError, OSError):
            return set()

        bindings = _static_test_path_bindings(tree, path)
        entry_roots = self.entry_point_roots(root)
        found: set[str] = set()

        def visit(
            node: ast.AST,
            *,
            in_function: bool = False,
            local_names: frozenset[str] = frozenset(),
        ) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local = frozenset(_path_binding_names(node))
                for child in node.body:
                    visit(child, in_function=True, local_names=local)
                return

            if isinstance(node, ast.Call):
                function = node.func
                if (
                    isinstance(function, ast.Attribute)
                    and function.attr in _TEST_RUNTIME_LAUNCHERS
                ):
                    argv = list(node.args[:1])
                    argv.extend(
                        keyword.value for keyword in node.keywords
                        if keyword.arg in {None, 'args'}
                    )
                    for argument in argv:
                        for candidate in _static_test_path_values(
                            argument, bindings, path
                        ):
                            rel = _repository_file(root, candidate)
                            if rel and not rel.startswith('src/') and any(
                                _prefix_matches(rel, entry_root)
                                for entry_root in entry_roots
                            ):
                                found.add(rel)

                if (
                    in_function
                    and isinstance(function, ast.Attribute)
                    and function.attr in _TEST_RUNTIME_READERS
                ):
                    receiver = function.value
                    # A module-level document constant belongs to the
                    # monorepo assertion that declared it.  Only a path
                    # assembled at the read site, or a path bound locally in
                    # this function, is a lane runtime support dependency.
                    if not (
                        isinstance(receiver, ast.Name)
                        and receiver.id not in local_names
                    ):
                        for candidate in _static_test_path_values(
                            receiver, bindings, path
                        ):
                            rel = _repository_file(root, candidate)
                            if (
                                rel
                                and not self.is_test_path(rel)
                                and not rel.startswith('src/')
                            ):
                                found.add(rel)

            for child in ast.iter_child_nodes(node):
                visit(child, in_function=in_function, local_names=local_names)

        visit(tree)
        return found

    def delivered_test_paths(self, root: Path, lanes: tuple[str, ...]) -> tuple[str, ...]:
        """Union of :meth:`tests_for_lane` over ``lanes`` — what actually ships.

        This is the "전 레인 납품 테스트 집합" the delivery-loss axis watches:
        the set of test-root files that travel in *some* shipping lane's box,
        regardless of which one. The defect this method's caller guards
        against shipped 2026-08-13 — three test files silently dropped from
        every lane's box in the same commit that made ``scripts/`` imports
        resolvable again, while the *total* delivered-test count rose from 94
        to 100 because ten unrelated files joined in the same commit. A
        count-based gate could not have told the two apart; a superset check
        against a recorded floor of this exact set can, and names the file
        that fell out rather than reporting a number that still went up.
        """
        root = Path(root)
        found: set[str] = set()
        for lane in lanes:
            found.update(self.tests_for_lane(root, lane))
        return tuple(sorted(found))

    def source_module_index(self, root: Path) -> dict[str, str]:
        """Import name -> repo-relative path, over :data:`PYTHON_SOURCE_ROOT`.

        The sibling of :meth:`entry_point_module_index` and
        :meth:`test_module_index`, over the third root. Existence is again the
        whole anti-fabrication mechanism: only files actually found under
        ``root`` produce a key, so a third-party name or a never-written module
        can never appear in a closure derived from this.

        This answers *what the interpreter would find*, not *who owns it* —
        ownership is :meth:`lane_for_path`, and keeping them apart is why a
        caller can ask "which lane owns the modules this seed set reaches"
        without this method needing to know what a lane is. Excluded trees are
        pruned, because a file the manifest excludes is not part of any
        question this repository asks.
        """
        root = Path(root)
        base = root / PYTHON_SOURCE_ROOT.rstrip('/')
        index: dict[str, str] = {}
        if not base.is_dir():
            return index
        for current, dirnames, filenames in os.walk(base):
            current_path = Path(current)
            rel_dir = current_path.relative_to(root).as_posix()
            dirnames[:] = sorted(
                name for name in dirnames
                if not self.should_prune_dir(f'{rel_dir}/{name}')
            )
            parts = current_path.relative_to(base).parts
            for name in sorted(filenames):
                if not name.endswith('.py'):
                    continue
                rel = (current_path / name).relative_to(root).as_posix()
                if self.is_excluded(rel):
                    continue
                dotted = '.'.join(
                    parts if name == '__init__.py' else (*parts, name[: -len('.py')])
                )
                if dotted:
                    index.setdefault(dotted, rel)
        return index

    def reachable_modules(
        self, root: Path, seeds: tuple[str, ...], *, edges: str,
        barriers: tuple[str, ...] = (),
    ) -> frozenset[str]:
        """First-party modules ``seeds`` reaches, transitively.

        **One definition of "reaches" for the whole repository.** Before this
        existed there were two — a private one in the build-artifact invariant
        and an ad-hoc one in every session that needed to answer a repo-split
        question — and the sessions' answers were never written down, which is
        how the same set came to have three sizes.

        ``edges`` is required and has no default; see
        :data:`IMPORT_EDGE_RELATIONS` for why choosing one silently would
        answer a different question than the caller asked.

        Names that do not resolve under :data:`PYTHON_SOURCE_ROOT` are dropped
        rather than recorded: a closure of *first-party* modules is what every
        caller wants, and ``PySide6`` is not a lane's to ship or to keep.
        Symbols imported from a module (``from x import y`` where ``y`` is a
        function) resolve to no file and drop out by the same rule.

        ``barriers`` are dotted prefixes that are **neither entered nor
        reported**: a module under one of them is not in the answer, and
        nothing behind it is reached *through* it. Default empty, so every
        existing caller is byte-identical.

        ⚠️ **Cutting after the walk is a different answer, not a tidier one.**
        Filtering the result of an unbarriered closure keeps everything the
        barrier's own imports dragged in, which for a Nuitka
        ``--nofollow-import-to`` target means reporting modules the frozen
        program provably does not contain. Measured on this tree that gap was
        **31 modules** and two of them were declared split blockers, so the
        inventory named work that did not exist. The cut belongs *before* the
        follow, which is why it is a parameter here rather than a
        comprehension at each call site.
        """
        if edges not in IMPORT_EDGE_RELATIONS:
            raise UnknownImportEdgeRelation(
                f'unknown import edge relation {edges!r}; '
                f'declared: {sorted(IMPORT_EDGE_RELATIONS)}'
            )
        root = Path(root)
        index = self.source_module_index(root)
        blocked = tuple(str(barrier) for barrier in barriers)
        reached: set[str] = set()
        pending = [str(seed) for seed in seeds]
        while pending:
            module = pending.pop()
            if module in reached:
                continue
            if any(
                module == barrier or module.startswith(barrier + '.')
                for barrier in blocked
            ):
                continue
            rel = index.get(module)
            if rel is None:
                continue
            reached.add(module)
            pending.extend(_imported_modules_of(
                root / rel, package=_package_of(rel), edges=edges,
            ))
        return frozenset(reached)

    def consumed_for_lane(
        self, root: Path, lane: str, basis: str, *, planned: tuple = (),
    ) -> tuple[str, ...]:
        """The files ``lane`` consumes, under a **named** ``basis``.

        The third argument of :meth:`shared_kernel_closure_for_lane` decides
        that method's answer, and until this existed every caller built it by
        hand. Two of them built it the *same* way — filtering the planned
        entries by kind — in two places, and the repository's records built it
        in ways nobody wrote down at all.

        ``basis`` comes from :data:`CONSUMED_BASES` and is required:

        * :data:`CONSUMED_BASIS_DELIVERY` reads ``planned`` — the entries the
          packager has already resolved for this lane — and drops the closure
          entry itself, which cannot seed its own derivation. Accepts planned
          dicts or bare paths, because the two existing callers hold each.
        * :data:`CONSUMED_BASIS_OWNERSHIP` ignores ``planned`` and derives from
          the tree: every governed, non-excluded file this lane owns. This is
          the basis that can answer for a lane with no box.

        Returns a sorted tuple so two callers on the same basis cannot differ
        by ordering — the closure is order-independent, but its *evidence*
        should not be.
        """
        if basis not in CONSUMED_BASES:
            raise UnknownConsumedBasis(
                f'unknown consumption basis {basis!r}; declared: {sorted(CONSUMED_BASES)}'
            )
        if basis == CONSUMED_BASIS_DELIVERY:
            paths: set[str] = set()
            for item in planned:
                if isinstance(item, dict):
                    if item.get('kind') == SHARED_KERNEL_CLOSURE_KIND:
                        continue
                    current = item.get('current_path')
                else:
                    current = item
                if current:
                    paths.add(str(current).replace('\\', '/'))
            return tuple(sorted(paths))

        root = Path(root)
        owned: set[str] = set()
        for path in _iter_files(root, self):
            rel = path.relative_to(root).as_posix()
            if not self.is_governed(rel) or self.is_excluded(rel):
                continue
            if self.lane_for_path(rel) == lane:
                owned.add(rel)
        return tuple(sorted(owned))

    def shared_kernel_closure_for_lane(
        self, root: Path, lane: str, consumed: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Shared-kernel files that must be in ``lane``'s box, derived.

        **Ownership and delivery are different questions**, and this repository
        settled that one wave ago on the *test* axis
        (:meth:`tests_for_lane`). This is the same sentence on the *source*
        axis: ``shared-kernel`` keeps owning all of ``src/domain/``, and what
        travels is only what the lane's own files reach.

        Shipping the layer whole would hand a joining team every measurement
        judgement this repository has — ``power_judgment``,
        ``ant_gain_validation``, ``gain_recorrection_policy``,
        ``dccf_share_policy`` — none of which the platform surface calls. That
        is the outcome ADR-0018 D-5 keeps closed, and widening later is always
        possible where recalling shipped judgement code is not.

        ``consumed`` is the lane's already-planned files: the seed is what
        *they* import, closed transitively (a shared-kernel module reaching a
        sibling brings it along) and completed with the package ``__init__``
        chain, without which the delivered tree is not importable.

        Returns ``()`` for a lane that has not declared the dependency. The
        closure must not be a second way into the kernel — ``depends_on`` stays
        the only door, which is what :meth:`_dependency_closure` means when it
        says the shared kernel is never implicitly injected.
        """
        if not self.may_depend_on(lane, SHARED_KERNEL_LANE):
            return ()
        root = Path(root)
        namespaces = self.current_namespaces(SHARED_KERNEL_LANE)
        if not namespaces:
            return ()

        pending: list[str] = []
        for rel in consumed:
            pending.extend(self._kernel_targets_of(root, rel, namespaces))
        selected: set[str] = set()
        while pending:
            rel = pending.pop()
            if rel in selected:
                continue
            selected.add(rel)
            # Both of these belong *inside* the fixpoint, and measurement is how
            # that was learned: adding the ``__init__`` chain afterwards left
            # ``domain/models/__init__.py`` in the box with its own imports never
            # followed, so ``domain.models.test_plan`` — which it imports at
            # module level — was missing and seven delivered test files could not
            # be collected. The gates were all green; only running the delivered
            # suite said so.
            pending.extend(self._kernel_targets_of(root, rel, namespaces))
            pending.extend(self._package_init_chain(root, rel))
        selected.update(self._package_data_for(root, selected))
        return tuple(sorted(selected))

    def _package_data_for(self, root: Path, modules: set[str]) -> set[str]:
        """Governed non-``.py`` files sitting beside a delivered module.

        A closure of imports finds modules, and a module is not always all a
        module needs: ``domain/models/reference_catalog.py`` reads
        ``decision_catalogue.json`` from its own package **at import time**, so
        without it the delivered tree fails to import the module it just
        delivered. Measured 2026-08-12: thirteen platform test files could not
        be collected for exactly that reason, after the ``domain.*`` names had
        already stopped being unresolved.

        Derived from where the modules landed rather than listed — a list is
        where the next data file goes missing — and scoped to directories this
        closure already delivers from, so it cannot reach into parts of the
        layer that are staying behind.
        """
        found: set[str] = set()
        for directory in {Path(rel).parent for rel in modules}:
            base = root / directory
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                if not child.is_file() or child.suffix == '.py':
                    continue
                rel = (directory / child.name).as_posix()
                if (
                    self.is_governed(rel)
                    and not self.is_excluded(rel)
                    and self.lane_for_path(rel) == SHARED_KERNEL_LANE
                ):
                    found.add(rel)
        return found

    def _kernel_targets_of(
        self, root: Path, rel: str, namespaces: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Shared-kernel files that ``rel`` imports, absolute or relative."""
        package = _package_of(rel)
        found: list[str] = []
        for module in _imported_modules_of(root / rel, package=package):
            if not _matches_any_namespace(module, namespaces):
                continue
            path = self._shared_kernel_path_for_module(root, module)
            if path is not None:
                found.append(path)
        return tuple(found)

    def _shared_kernel_path_for_module(self, root: Path, module: str) -> str | None:
        """Repo-relative path of a shared-kernel module, or ``None``.

        ``None`` covers three honest outcomes that must not be told apart here:
        the name is a symbol rather than a module, the file is excluded or
        ungoverned, or ownership resolves elsewhere. Only files the manifest
        actually gives to the shared kernel may travel under its claim.
        """
        stem = module.replace('.', '/')
        for candidate in (f'{PYTHON_SOURCE_ROOT}{stem}.py', f'{PYTHON_SOURCE_ROOT}{stem}/__init__.py'):
            if not (root / candidate).is_file():
                continue
            if not self.is_governed(candidate) or self.is_excluded(candidate):
                continue
            if self.lane_for_path(candidate) != SHARED_KERNEL_LANE:
                continue
            return candidate
        return None

    def _package_init_chain(self, root: Path, rel: str) -> tuple[str, ...]:
        """``__init__.py`` files between a delivered module and the source root.

        A module lands in a directory Python must be able to import. Leaving
        these out produces a tree that unpacks with every file the closure named
        and still cannot resolve one of them.
        """
        found: list[str] = []
        parent = Path(rel).parent
        while parent.as_posix().startswith(PYTHON_SOURCE_ROOT.rstrip('/')):
            candidate = (parent / '__init__.py').as_posix()
            if (
                (root / candidate).is_file()
                and self.is_governed(candidate)
                and not self.is_excluded(candidate)
                and self.lane_for_path(candidate) == SHARED_KERNEL_LANE
            ):
                found.append(candidate)
            parent = parent.parent
        return tuple(found)

    def _test_imports_of(
        self, path: Path, index: dict[str, str], *, rel: str = '',
    ) -> tuple[str, ...]:
        """Test-root files ``path`` imports, by longest module-name match.

        Reads through :func:`_imported_modules_of` rather than
        :func:`_imported_modules` so a **relative** import is not invisible.
        ``from .fake_instrument import …`` carries no dotted name at all, and a
        level-0-only reader sees a file that imports nothing — the exact blind
        spot the shared-kernel closure was built to close, one axis over. It
        costs nothing today (measured 2026-08-26: one test-root file has
        relative imports and no lane schedules it) and it removes the trap that
        fires the moment one does, which is the same file: ``tests/fakes/__init__.py``
        re-exports fourteen fakes this way, so a lane that ever schedules it and
        does not get them ships a package that raises on import.

        ``rel`` is the repository-relative path, used only to resolve those
        relative imports against the file's own package. Omitting it degrades to
        the level-0-only answer rather than guessing a package.
        """
        found: set[str] = set()
        package = _package_of(rel, self.test_root) if rel else ''
        for module in _imported_modules_of(path, package=package):
            name = max(
                (
                    candidate for candidate in index
                    if module == candidate or module.startswith(candidate + '.')
                ),
                key=len,
                default='',
            )
            if name:
                found.add(index[name])
        return tuple(sorted(found))

    def classify_tree(self, root: Path) -> ClassificationReport:
        """Walk ``root`` and classify every governed file.

        Binds :meth:`entry_point_module_index` to ``root`` — test files
        under ``root`` are attributed by what they import, and an unbound
        policy would misclassify one that imports ``scripts/``.
        """
        root = Path(root)
        self = self.bound_to(root)
        counts: dict[str, int] = {owner: 0 for owner in self.owners}
        counts[EXCLUDED] = 0
        unclassified: list[str] = []
        excluded: list[str] = []
        retained: dict[str, int] = {reason: 0 for reason in TEST_RETAINED_REASONS}

        for path in _iter_files(root, self):
            rel = path.relative_to(root).as_posix()
            if not self.is_governed(rel):
                continue
            if self.is_test_path(rel):
                owner, reason = (
                    self.lane_for_test_file(path) if path.suffix == '.py'
                    else (EXCLUDED, TEST_RETAINED_NO_SOURCE)
                )
                if reason:
                    retained[reason] = retained.get(reason, 0) + 1
            else:
                owner = self.lane_for_path(rel)
            if owner == UNCLASSIFIED:
                unclassified.append(rel)
                continue
            counts[owner] = counts.get(owner, 0) + 1
            if owner == EXCLUDED:
                excluded.append(rel)

        return ClassificationReport(
            counts=counts,
            unclassified=tuple(sorted(unclassified)),
            excluded=tuple(sorted(excluded)),
            test_retained=dict(retained),
        )

    # -------------------------------------------------- namespace ownership

    def namespaces(self, lane: str) -> tuple[str, ...]:
        """Import prefixes the lane *publishes* — the names its files will have
        after extraction.

        A module the manifest relocates is published under its ``future_path``
        only. ``application.headless.platform_cutover_readiness`` becomes
        ``fcc_test_platform.cutover_readiness``, so a staged platform tree
        importing the old name is reaching for a path that will not exist —
        exactly the "forgot to rewrite the import" signal the gate exists for.

        When bound (:meth:`bound_to`), also publishes every entry-point
        identity :meth:`lane_for_path` resolves to this lane — every
        ``scripts/*.py`` entry has no relocation entry in this manifest (its
        ``future_path`` equals its ``current_path``), so publishing its
        current identity verbatim is correct, not a simplification. This is
        the one place that opens the import-boundary and dependency-
        resolution gates to ``scripts/``: both derive their allowed/forbidden
        sets from this method, never from :meth:`current_namespaces`.
        Unbound, this is exactly today's answer — the entry-point index is
        empty, so the filter below adds nothing.
        """
        published = self._namespaces.get(lane, ())
        if not self._entry_point_index:
            return published
        bound = {
            name for name, rel in self._entry_point_index.items()
            if self.lane_for_path(rel) == lane
        }
        return tuple(sorted(set(published) | bound))

    def current_namespaces(self, lane: str) -> tuple[str, ...]:
        """Import prefixes the lane owns *in the monorepo as it stands*.

        Used to attribute an in-repo import to its owning lane, which is a
        different question from what a staged tree may import.
        """
        return self._current_namespaces.get(lane, ())

    def _dependency_closure(self, lane: str) -> tuple[str, ...]:
        """Transitive ``depends_on`` closure, including the lane itself.

        The shared kernel is *not* injected implicitly: a lane that may read it
        must say so. ``fcc-test-contracts`` is dependency-free precisely
        because it declares no dependencies, and an implicit injection would
        silently grant it the domain layer.
        """
        seen: list[str] = []
        pending = [lane]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.append(current)
            pending.extend(self.depends_on.get(current, ()))
        return tuple(seen)

    def allowed_prefixes(self, lane: str) -> tuple[str, ...]:
        """Namespaces a staged tree for ``lane`` may import.

        What it publishes itself, plus what each declared dependency publishes.
        """
        allowed: list[str] = []
        for owner in self._dependency_closure(lane):
            allowed.extend(self.namespaces(owner))
        return tuple(sorted(set(allowed)))

    def lane_for_module(self, module: str) -> str:
        """Owning lane of an in-repo import target, by longest namespace match.

        Answers a different question than :meth:`allowed_prefixes`: that one
        governs staged trees, this one governs the monorepo as it stands, where
        modules still carry their current names.

        The namespace-matching pass is unchanged from before this axis
        existed and always wins when it produces an answer — ``main`` resolves
        from ``src/main.py`` and never reaches the fallback below, because
        ``src/`` always has a rule. Only when that pass is silent
        (:data:`UNCLASSIFIED`) does this fall back to the entry-point index
        bound by :meth:`bound_to`: a dict lookup, so it is either a real file
        this policy has evidence for, or nothing — never a guess. This is
        also why the fallback goes through :meth:`lane_for_path` rather than
        re-deriving ownership in module-name space: a glob rule like
        ``scripts/platform_*`` already resolves correctly by path, and
        reimplementing that logic here would be the second definition this
        module's SSOT contract forbids.

        Unbound (the default), this method is byte-identical to before the
        entry-point axis existed.
        """
        best_lane = UNCLASSIFIED
        best_len = -1
        for owner in self.owners:
            for namespace in self.current_namespaces(owner):
                if module == namespace or module.startswith(namespace + '.'):
                    if len(namespace) > best_len:
                        best_lane, best_len = owner, len(namespace)
        if best_lane != UNCLASSIFIED:
            return best_lane
        rel = self._entry_point_index.get(module)
        if rel is None:
            return UNCLASSIFIED
        return self.lane_for_path(rel)

    def may_depend_on(self, lane: str, other: str) -> bool:
        """Whether ``lane`` is permitted to import from ``other``."""
        return other in self._dependency_closure(lane)

    def is_composition_root(self, rel_path: str) -> bool:
        return rel_path.replace('\\', '/') in set(self.composition_roots)

    def declared_crossings_for(self, rel_path: str) -> tuple[CompositionRootCrossing, ...]:
        """Declared crossing records for one composition root."""
        return self.composition_root_crossings.get(rel_path.replace('\\', '/'), ())

    def declared_crossing_modules(self, rel_path: str) -> frozenset[str]:
        """Module names ``rel_path`` is declared to reach across a lane boundary."""
        return frozenset(
            crossing.module for crossing in self.declared_crossings_for(rel_path)
        )

    def declared_crossing_debt_counts(self) -> dict[str, int]:
        """Per-disposition site counts derived from the declaration.

        The comparison partner is
        :attr:`composition_root_crossing_debt_budget`, a *separate* manifest
        value — deriving both sides from one source would make the assertion
        unable to fail.
        """
        counts = {disposition: 0 for disposition in sorted(CROSSING_DEBT_DISPOSITIONS)}
        for sites in self.composition_root_crossings.values():
            for crossing in sites:
                if crossing.is_debt:
                    counts[crossing.disposition] += 1
        return counts

    def _file_crossings(self, path: Path, rel: str) -> tuple[tuple[str, str], ...]:
        """Cross-lane imports in one file, as ``(target_lane, module)`` pairs.

        The single definition of *what a crossing is*. Both
        :meth:`cross_lane_imports` (which skips composition roots) and
        :meth:`measured_composition_root_crossings` (which reports only them)
        call it, so the two axes cannot drift into disagreeing about the same
        import — which is precisely the state this axis was created to end:
        one axis exempted these files entirely while the other had no concept
        of them.
        """
        owner = self.lane_for_path(rel)
        if owner in (UNCLASSIFIED, EXCLUDED):
            return ()
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            return ()
        found: list[tuple[str, str]] = []
        for module in _imported_modules(tree):
            target = self.lane_for_module(module)
            if target in (UNCLASSIFIED, EXCLUDED) or target == owner:
                continue
            if self.may_depend_on(owner, target):
                continue
            found.append((target, module))
        return tuple(found)

    def measured_composition_root_crossings(
        self, root: Path,
    ) -> dict[str, frozenset[str]]:
        """Cross-lane modules each declared composition root actually reaches.

        The inverse of the exemption in :meth:`cross_lane_imports`: that method
        answers *"what does the tree couple, ignoring the roots"*, this one
        answers *"what do the roots couple"*. Keyed by every path in
        :attr:`composition_roots` — a root that reaches nothing maps to an
        empty set rather than being absent, so a declaration can be compared
        against it by set equality without a missing key reading as agreement.

        A root path that does not exist in ``root`` is reported as an empty set
        for the same reason; the *existence* question belongs to the manifest
        totality invariants, not here.
        """
        root = Path(root)
        bound = self.bound_to(root)
        measured: dict[str, frozenset[str]] = {}
        for rel in bound.composition_roots:
            path = root / rel
            if not path.is_file():
                measured[rel] = frozenset()
                continue
            measured[rel] = frozenset(
                module for _target, module in bound._file_crossings(path, rel)
            )
        return measured

    def cross_lane_imports(self, root: Path) -> dict[str, tuple[tuple[str, str], ...]]:
        """In-repo imports that cross a lane boundary against ``depends_on``.

        Keyed ``'<owner> -> <target> @ <top-level root>'``. The root qualifier
        is not cosmetic: 32 of the 38 Unlicensed→platform crossings live under
        ``scripts/``, and a single lumped count would let a real ``src/``
        regression hide behind operator-tooling churn.

        Composition roots are exempt because wiring across lanes is their
        entire job. Reports the monorepo as it stands, which is a different
        question from whether a *staged* tree is importable — see
        :meth:`allowed_prefixes` for that one.

        Binds :meth:`entry_point_module_index` to ``root`` — otherwise a
        ``scripts.foo`` import target resolves :data:`UNCLASSIFIED` and a
        real cross-lane crossing through ``scripts/`` goes unreported.
        """
        root = Path(root)
        self = self.bound_to(root)
        found: dict[str, list[tuple[str, str]]] = {}
        for path in _iter_files(root, self):
            if path.suffix != '.py':
                continue
            rel = path.relative_to(root).as_posix()
            if self.is_composition_root(rel):
                continue
            owner = self.lane_for_path(rel)
            for target, module in self._file_crossings(path, rel):
                top_level = rel.split('/')[0]
                key = f'{owner} -> {target} @ {top_level}'
                found.setdefault(key, []).append((rel, module))
        return {key: tuple(sorted(value)) for key, value in sorted(found.items())}

    def forbidden_prefixes(self, lane: str) -> tuple[str, ...]:
        """Namespaces the lane must never import.

        Derived as *every other owner's namespaces outside the dependency
        closure*, plus the lane's declared third-party bans. Because both sides
        come from one declaration, an allowed prefix can never also be listed
        as forbidden — the contradiction that made the old hand-maintained
        pair unreliable is structurally impossible here.
        """
        allowed = set(self.allowed_prefixes(lane))
        forbidden: list[str] = list(self.forbidden_external.get(lane, ()))
        for owner in self.owners:
            if owner == lane:
                continue
            # Every other owner's monorepo namespaces are banned, then the
            # published names of permitted dependencies are subtracted back
            # out via `allowed`. A permitted dependency is therefore reachable
            # under the name it publishes and *only* under that name — leaving
            # its monorepo namespaces in neither set is the gap that let a
            # staged platform tree import `application.common` unchallenged.
            forbidden.extend(self.namespaces(owner))
        return tuple(sorted({prefix for prefix in forbidden if prefix not in allowed}))


# ----------------------------------------------------------------- helpers


def _rules_for_owner(lane: str, spec: dict) -> list[OwnershipRule]:
    rules = [
        OwnershipRule(pattern=item['path'], lane=lane, notes=item.get('notes', ''))
        for item in (spec.get('source_roots') or [])
    ]
    rules.extend(
        OwnershipRule(pattern=path, lane=lane)
        for path in (spec.get('source_files') or [])
    )
    return rules


def _namespace_from_path(path: str, *, package_name: str = '') -> str:
    """Import prefix for a repository path, or ``''`` when it has none.

    Only two shapes are importable: source under :data:`PYTHON_SOURCE_ROOT`,
    and paths already rooted at a lane's published package. Everything else
    (``docs/``, ``apps/web/``, ``scripts/``) is content or an entry point, not a
    package — minting ``docs.api`` as a namespace would be a fabricated rule.
    """
    path = path.strip()
    if path.startswith(PYTHON_SOURCE_ROOT):
        remainder = path[len(PYTHON_SOURCE_ROOT):]
    elif package_name and (path == package_name or path.startswith(package_name + '/')):
        remainder = path
    else:
        return ''
    if remainder.endswith('.py'):
        remainder = remainder[: -len('.py')]
    remainder = remainder.strip('/')
    return remainder.replace('/', '.') if remainder else ''


def _published_namespaces(
    rules: list[OwnershipRule], spec: dict, *, package_name: str
) -> tuple[str, ...]:
    """Namespaces the owner will expose after extraction.

    A path with a relocation ``entry`` publishes under its ``future_path``; a
    path without one publishes where it already lives, because the manifest has
    not scheduled it to move. Globs claim paths but never a namespace: a glob's
    literal head (``src/application/headless/platform_``) is not a module name,
    and inventing one would be a guess.
    """
    namespaces: set[str] = set()
    if package_name:
        namespaces.add(package_name)

    entries = spec.get('entries') or []
    for entry in entries:
        future = _namespace_from_path(entry.get('future_path', ''), package_name=package_name)
        if future:
            namespaces.add(future)

    for rule in rules:
        if rule.is_glob:
            continue
        namespace = _namespace_from_path(rule.pattern, package_name=package_name)
        if namespace and not _rule_is_relocated(
            rule, namespace, entries, package_name=package_name
        ):
            namespaces.add(namespace)
    return tuple(sorted(namespaces))


def _rule_is_relocated(
    rule: OwnershipRule, namespace: str, entries: list[dict], *, package_name: str
) -> bool:
    """Whether every relocation under ``rule`` moves its namespace elsewhere.

    ``src/application/common/`` is fully relocated into
    ``fcc_test_contracts/common/``, so the lane no longer publishes
    ``application.common``. ``src/application/headless/`` keeps its entries in
    place, so it still does — and a directory that keeps even one module must
    keep publishing, or the other lanes lose the ban that covers the rest of it.
    """
    prefix = rule.pattern if rule.pattern.endswith('/') else rule.pattern + '/'
    under = [
        entry for entry in entries
        if entry.get('current_path', '') == rule.pattern
        or entry.get('current_path', '').startswith(prefix)
    ]
    if not under:
        return False
    for entry in under:
        future = _namespace_from_path(entry.get('future_path', ''), package_name=package_name)
        if future == namespace or future.startswith(namespace + '.'):
            return False
    return True


def _current_namespaces(rules: list[OwnershipRule]) -> tuple[str, ...]:
    """Namespaces the owner holds in the monorepo today."""
    namespaces: set[str] = set()
    for rule in rules:
        if rule.is_glob:
            continue
        namespace = _namespace_from_path(rule.pattern)
        if namespace:
            namespaces.add(namespace)
    return tuple(sorted(namespaces))


def _package_of(rel: str, source_root: str = PYTHON_SOURCE_ROOT) -> str:
    """Dotted package a source file lives in, for resolving relative imports.

    ``source_root`` names the tree the dotted name is rooted at. It defaults to
    the Python source root because that is where this arithmetic started, and it
    is a parameter rather than a second function because the test root needs the
    identical computation — a copy would drift, and the copy that drifted would
    be the one nobody reads.
    """
    prefix = tuple(part for part in Path(source_root.rstrip('/')).parts if part)
    parts = Path(rel).parts
    if not prefix or parts[: len(prefix)] != prefix:
        return ''
    inner = list(parts[len(prefix):])
    if inner and inner[-1].endswith('.py') and inner[-1] != '__init__.py':
        inner = inner[:-1]
    elif inner and inner[-1] == '__init__.py':
        inner = inner[:-1]
    return '.'.join(inner)


def _imported_modules_of(
    path: Path, *, package: str = '', edges: str = IMPORT_EDGE_STATIC,
) -> set[str]:
    """Import targets of one file, relative imports resolved against ``package``.

    ``edges`` selects the relation, from :data:`IMPORT_EDGE_RELATIONS`. Under
    ``module_level`` only the direct children of ``ast.Module.body`` are read,
    so an import inside a function, a class body, a ``try/except`` or an
    ``if TYPE_CHECKING`` block is excluded — those may never execute, which is
    the whole point of that relation. Under ``static`` the whole tree is
    walked. **Relative imports are resolved under both**: a level-0-only reader
    sees a file that imports nothing, and ``src/domain/`` really does write
    ``from .enums import BandType``.

    Broader than :func:`_imported_modules`, which answers a different question:
    that one attributes *declared* names to lanes, while this one has to find
    every file a delivered tree will actually need. Two shapes it must not miss:

    * ``from .enums import BandType`` — a relative import carries no dotted name
      at all, so a level-0-only reader sees a file that imports nothing.
    * ``from domain.models import test_plan`` — the dotted name is the package
      and the *module* is in the alias list, so resolving only the ``module``
      field delivers the package without the module inside it.

    Names that resolve to a symbol rather than a file are harmless: the caller
    asks the filesystem, and a symbol has no file.

    An unreadable file yields nothing. That is not "imports nothing" in
    general, but every caller here walks files the manifest governs, where a
    parse failure is test data or a deliberate syntax fixture — the same
    conclusion :meth:`lane_for_test_file` already draws.
    """
    if edges not in IMPORT_EDGE_RELATIONS:
        raise UnknownImportEdgeRelation(
            f'unknown import edge relation {edges!r}; '
            f'declared: {sorted(IMPORT_EDGE_RELATIONS)}'
        )
    try:
        tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()

    nodes = tree.body if edges == IMPORT_EDGE_MODULE_LEVEL else ast.walk(tree)
    modules: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _import_from_base(node, package)
            if not base:
                continue
            modules.add(base)
            modules.update(f'{base}.{alias.name}' for alias in node.names)
    return modules


def _import_from_base(node: ast.ImportFrom, package: str) -> str:
    """Dotted name an ``ImportFrom`` reads from, or ``''`` when unresolvable."""
    if node.level == 0:
        return node.module or ''
    if not package:
        return ''
    parts = package.split('.')
    trimmed = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
    if not trimmed:
        return ''
    base = '.'.join(trimmed)
    return f'{base}.{node.module}' if node.module else base


def _matches_any_namespace(module: str, namespaces: tuple[str, ...]) -> bool:
    return any(
        module == namespace or module.startswith(namespace + '.')
        for namespace in namespaces
    )


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def _static_test_path_bindings(tree: ast.AST, path: Path) -> dict[str, Path]:
    """Resolve simple ``Path(__file__)`` bindings used by a test.

    This is deliberately a small symbolic evaluator rather than execution of
    test code.  The package planner must be able to inspect a test without
    importing it, and only path values rooted at the test file can become
    repository support candidates.
    """
    bindings: dict[str, Path] = {}
    assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    for _ in range(len(assignments) + 1):
        changed = False
        for node in assignments:
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            value = _static_test_path_value(node.value, bindings, path)
            if not isinstance(value, Path):
                continue
            for target in targets:
                name = (
                    target.id if isinstance(target, ast.Name)
                    else target.attr if isinstance(target, ast.Attribute)
                    else None
                )
                if name and bindings.get(name) != value:
                    bindings[name] = value
                    changed = True
        if not changed:
            break
    return bindings


def _path_binding_names(node: ast.AST) -> set[str]:
    """Names assigned in one test function, for local path-use detection."""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = (
                child.targets if isinstance(child, ast.Assign)
                else (child.target,)
            )
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _static_test_path_values(
    node: ast.AST,
    bindings: dict[str, Path],
    path: Path,
) -> set[Path]:
    """Collect all statically resolvable path values below ``node``."""
    found: set[Path] = set()
    value = _static_test_path_value(node, bindings, path)
    if isinstance(value, Path):
        found.add(value)
    for child in ast.iter_child_nodes(node):
        found.update(_static_test_path_values(child, bindings, path))
    return found


def _static_test_path_value(
    node: ast.AST,
    bindings: dict[str, Path],
    path: Path,
) -> Path | str | None:
    """Evaluate the path-expression subset used by repository tests."""
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, ast.Call):
        resolver_name = (
            node.func.id if isinstance(node.func, ast.Name)
            else node.func.attr if isinstance(node.func, ast.Attribute)
            else None
        )
        if resolver_name in {'resolve_repo_artifact', 'resolve_dependency_artifact'} and node.args:
            argument = _static_test_path_value(node.args[-1], bindings, path)
            if isinstance(argument, str):
                return Path(argument)
        if isinstance(node.func, ast.Name) and node.func.id == 'Path':
            if (
                node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == '__file__'
            ):
                return path
            if node.args:
                argument = _static_test_path_value(node.args[0], bindings, path)
                if isinstance(argument, Path):
                    return argument
                if isinstance(argument, str):
                    return Path(argument)
            return None
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            'absolute', 'resolve', 'resolve_path'
        }:
            value = _static_test_path_value(node.func.value, bindings, path)
            return value if isinstance(value, Path) else None
        if isinstance(node.func, ast.Name) and node.func.id == 'str' and node.args:
            value = _static_test_path_value(node.args[0], bindings, path)
            return value if isinstance(value, Path) else None
        return None

    if isinstance(node, ast.Attribute):
        # ``self._SCRIPT`` is how a class-level path binding is used by a test
        # method.  The binding name is still the architecture-relevant fact;
        # no class or test name is special-cased here.
        if node.attr in bindings:
            return bindings[node.attr]
        if node.attr == 'parent':
            value = _static_test_path_value(node.value, bindings, path)
            return value.parent if isinstance(value, Path) else None
        return None

    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Attribute) and node.value.attr == 'parents':
            value = _static_test_path_value(node.value.value, bindings, path)
            index = node.slice
            if (
                isinstance(value, Path)
                and isinstance(index, ast.Constant)
                and isinstance(index.value, int)
            ):
                try:
                    return value.parents[index.value]
                except IndexError:
                    return None
        return None

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _static_test_path_value(node.left, bindings, path)
        right = _static_test_path_value(node.right, bindings, path)
        if isinstance(left, Path) and isinstance(right, str):
            return left / right
        return None

    return None


def _repository_file(root: Path, candidate: Path) -> str | None:
    """Return a safe repository-relative file path, or no candidate."""
    root = Path(root).resolve()
    resolved = candidate if candidate.is_absolute() else root / candidate
    try:
        rel = resolved.resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return None
    if not rel or not (root / rel).is_file():
        return None
    return rel


def _prefix_matches(rel_path: str, root: str) -> bool:
    if root.endswith('/'):
        return rel_path.startswith(root)
    return rel_path == root or rel_path.startswith(root + '/')


def _rules_can_overlap(left: OwnershipRule, right: OwnershipRule) -> bool:
    """Conservative overlap test used only to surface ambiguous declarations."""
    if left.pattern == right.pattern:
        return True
    if left.is_glob or right.is_glob:
        return fnmatch.fnmatch(right.pattern, left.pattern) or fnmatch.fnmatch(
            left.pattern, right.pattern
        )
    return _prefix_matches(right.pattern, left.pattern) or _prefix_matches(
        left.pattern, right.pattern
    )


def _iter_files(root: Path, policy: ExtractionLanePolicy):
    """Yield files under the manifest's governed roots, pruning excluded trees.

    Walking the whole repository is what made the old checker read 8,453 files
    including the virtualenv and report its template syntax errors as boundary
    violations. Governance declares the surface; the walk obeys it.

    Excluded directories are pruned rather than walked-then-discarded — reading
    every file under ``node_modules`` only to throw it away costs 28k stats per
    invocation on this repository.
    """
    for governed in policy.governed_roots:
        base = root / governed.rstrip('/')
        if base.is_file():
            yield base
            continue
        if not base.is_dir():
            continue
        for current, dirnames, filenames in os.walk(base):
            rel_dir = Path(current).relative_to(root).as_posix()
            dirnames[:] = sorted(
                name for name in dirnames
                if not policy.is_excluded_dir(f'{rel_dir}/{name}')
            )
            for name in sorted(filenames):
                yield Path(current) / name
