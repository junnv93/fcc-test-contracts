"""Composition-root cross-lane crossings are declared per site, not per file.

``governance.composition_roots`` is a *file-level* exemption:
:meth:`ExtractionLanePolicy.cross_lane_imports` reaches
``if self.is_composition_root(rel): continue`` and drops the whole file. A
declared root could therefore accumulate an unbounded, unreasoned set of
cross-lane imports and no axis would ask about any of them.

Measured at ``origin/main@5685134c`` by disabling that one predicate and
changing nothing else: the axis reports **50** crossings with the exemption on
and **69** with it off. **19 were invisible**, twelve of them in
``fcc-unlicensed-headless -> fcc-test-platform @ src`` — the direction a
provider/platform repository split depends on most. Six of the eleven declared
roots reach nothing at all, which is why the blanket exemption is slack rather
than a property of the category.

The staged axis had the mirror-image blind spot:
``scripts/check_extraction_import_boundaries.py`` contains the string
``composition`` **zero** times, so it does not exempt these files and folds
them into one integer instead. A count cannot see a swap, and it carries no
reason — nothing in it distinguishes a root naming a concrete behind an
existing port from a leftover import a lane-neutral replacement already
superseded.

That distinction is not academic. ``src/platform_api_composition.py`` imported
``get_logger`` twice — the lane-neutral
``application.common.logging_channel`` at line 36 (``e625c694``, 2026-08-21)
and the provider ``logger_config`` at line 144 (``cb117ea8``, 2026-05-27).
Python binds the later import, so the contracts-lane one was dead for three
months while the count stayed 6 and every gate stayed green. Its sibling
repair had landed: ``readiness_service.py`` was converted on 2026-08-13 and is
clean. The wave stopped one file short and nothing could say so.

The principle these tests generalise was already written down — and
implemented once, by hand, for one file of eleven:
``test_platform_provider_crossing_closure.py::TestTheLiveWorkerRunnerIsOnlyComposition``
counts the provider imports of ``run-test-plan-generation-worker.py``, the
root with **one** crossing. The root with **five** had nothing.
"""
import ast
import copy
import json
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'scripts'))
sys.path.insert(0, str(project_root / 'src'))

from fcc_test_contracts.common.extraction_lane_policy import (  # noqa: E402
    CROSSING_DEBT_DISPOSITIONS,
    CROSSING_DISPOSITIONS,
    EXECUTED_CROSSING_DISPOSITIONS,
    MINIMUM_CROSSING_REASON_LENGTH,
    UNVERIFIED_CROSSING_DISPOSITIONS,
    CompositionRootCrossing,
    ExtractionLanePolicy,
)
from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact  # noqa: E402

MANIFEST_REL = 'docs/api/headless_contract_extraction_manifest.v1.json'

#: Lane attribution is derived from the import closure, so this file travels
#: into the ``fcc-test-contracts`` delivery box (it imports the contracts-owned
#: lane policy). The *manifest* is resolved through the packager's relocation
#: record rather than a monorepo-shaped path, so the declaration questions stay
#: answerable inside the box.
#:
#: ⚠️ The argument is a **literal**, not ``MANIFEST_REL``. The delivered-artifact
#: -path axis reads these call sites statically, so a computed argument is a call
#: it cannot resolve and it lands in
#: ``governance.delivered_artifact_path_dynamic_baseline`` instead. Passing the
#: constant here raised the contracts-lane dynamic census 2 → 3 and turned
#: ``test_delivered_artifact_paths.py`` red — the correct repair is to make the
#: site readable, not to raise the baseline. The constant stays because the
#: monorepo-layout probe below needs the same path.
MANIFEST_PATH = resolve_repo_artifact(
    __file__, 'docs/api/headless_contract_extraction_manifest.v1.json',
)

#: The tree the *measurement* questions need. A delivered box holds
#: ``fcc_test_contracts/…``, not ``src/…``, so "what does this composition root
#: import" is a question the box **cannot answer** — which is not the same as
#: the answer being wrong. Those cases skip with a reason rather than failing.
#:
#: ⚠️ **Non-vacuity here is the monorepo run itself, and nothing else.** An
#: earlier draft of this comment claimed ``test_delivered_tree_runs.py`` sealed
#: it; measured, that file was never touched by this wave, has no notion of this
#: module, and budgets *failures* rather than skips — a box in which all of these
#: skipped would be green. Disarming the guard yields ``10 passed, 9 skipped,
#: exit 0`` with nothing objecting. The check below is the honest partial seal:
#: a tree that has ``src/`` must not have a disarmed guard.
_MONOREPO_ROOT = (
    project_root
    if (project_root / 'src' / 'application' / 'common' / 'extraction_lane_policy.py').is_file()
    and (project_root / MANIFEST_REL).is_file()
    else None
)

_NEEDS_TREE = unittest.skipIf(
    _MONOREPO_ROOT is None,
    'delivered box: the monorepo src/ layout is absent, so "what does this '
    'composition root import" cannot be measured here. The declaration '
    'questions in this module still run — only the measurement ones skip.',
)


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))


def _policy(manifest: dict | None = None) -> ExtractionLanePolicy:
    return ExtractionLanePolicy.from_manifest(manifest if manifest is not None else _manifest())


class _AxisCase(unittest.TestCase):
    def setUp(self):
        self.manifest = _manifest()
        self.governance = self.manifest['governance']
        self.policy = _policy(self.manifest)
        self.declared = {
            root: self.policy.declared_crossing_modules(root)
            for root in self.policy.composition_roots
        }


class TestTheDeclarationIsTotalOverTheDeclaredRoots(_AxisCase):
    """G2 — a new composition root cannot arrive without declaring its sites.

    Key-set *equality*, not containment: a root present in one list and absent
    from the other is the state where "we never looked" is indistinguishable
    from "it reaches nothing".
    """

    def test_every_declared_root_has_a_crossing_record(self):
        self.assertEqual(
            set(self.governance['composition_root_crossings']),
            set(self.governance['composition_roots']),
            'composition_roots and composition_root_crossings must name the same files',
        )

    def test_a_root_added_without_a_record_is_red(self):
        """Negative control — routed through the policy, not through set algebra.

        The first draft appended to a deep copy and asserted
        ``set(X | {new}) != set(X)``, which is true of any set and calls no
        production code: an adversarial review pointed out it would still pass
        if the sibling equality were weakened to containment. It now builds a
        policy from the mutated manifest and asks *that* what it declares.
        """
        mutated = copy.deepcopy(self.manifest)
        mutated['governance']['composition_roots'].append('src/some_new_root.py')
        policy = _policy(mutated)

        self.assertIn('src/some_new_root.py', policy.composition_roots)
        self.assertEqual(
            policy.declared_crossing_modules('src/some_new_root.py'), frozenset(),
            'the policy must report the undeclared root as declaring nothing, '
            'which is what makes the key-set equality catch it',
        )
        self.assertNotEqual(
            set(policy.composition_root_crossings), set(policy.composition_roots),
        )

    def test_a_root_that_reaches_nothing_declares_an_empty_list(self):
        """The six zero-crossing roots are *declared* zero, not merely absent."""
        empty = [
            root for root, sites in self.governance['composition_root_crossings'].items()
            if not sites
        ]
        self.assertTrue(
            empty,
            'no root declares zero crossings — the empty case is what proves the '
            'blanket exemption was slack rather than a property of the category',
        )


class TestTheMeasurementGuardIsDisarmedWhereItShouldBe(unittest.TestCase):
    """The ``@_NEEDS_TREE`` guard silently removes nine assertions when it fires.

    It is not decorated with ``_NEEDS_TREE`` itself — that would be the guard
    vouching for the guard. It asks a *simpler* premise than the guard's own
    conjunction: if this tree has a ``src/`` directory at all, the guard must be
    off. That catches the reachable failure (someone narrowing or mistyping one
    conjunct in the monorepo) without pretending to catch the one that needs a
    packager-written layout record.
    """

    def test_a_tree_with_a_src_directory_has_the_guard_disarmed(self):
        if not (project_root / 'src').is_dir():
            self.skipTest('delivered box: there is no src/ to reason about')
        self.assertIsNotNone(
            _MONOREPO_ROOT,
            'this tree has src/ but the measurement guard is armed — nine '
            'assertions would vanish and the module would still report success',
        )


class TestDeclarationEqualsMeasurement(_AxisCase):
    """G1 — the declaration equals what the production predicate measures.

    Set equality is the whole point. The axis this replaces kept a *count*, and
    the manifest note that owns that count says so in its own words: "a number
    that holds still through a swap is exactly where a silent replacement
    hides". A swap keeps the count and moves the set.
    """

    @_NEEDS_TREE
    def test_declared_sites_equal_measured_sites(self):
        measured = self.policy.measured_composition_root_crossings(project_root)
        self.assertEqual(
            self.declared, measured,
            'declared composition-root crossings drifted from the measured ones',
        )

    @_NEEDS_TREE
    def test_a_swapped_module_is_red_although_the_count_is_unchanged(self):
        """The criterion that distinguishes this axis from a count.

        Swap one declared module for another and the total stays 19. A
        count-based assertion passes; set equality does not.
        """
        mutated = copy.deepcopy(self.manifest)
        sites = mutated['governance']['composition_root_crossings']
        victim = next(root for root, value in sites.items() if value)
        before = len([item for value in sites.values() for item in value])
        sites[victim][0]['module'] = 'application.common.some_other_module'
        after = len([item for value in sites.values() for item in value])

        self.assertEqual(before, after, 'the mutation must not change the count')
        mutated_policy = _policy(mutated)
        mutated_declared = {
            root: mutated_policy.declared_crossing_modules(root)
            for root in mutated_policy.composition_roots
        }
        self.assertNotEqual(
            mutated_declared,
            mutated_policy.measured_composition_root_crossings(project_root),
            'a swap that preserves the count must still be caught',
        )

    @_NEEDS_TREE
    def test_the_measurement_is_the_production_predicate_not_a_copy(self):
        """The test must not carry its own scanner.

        A reimplementation of this predicate answered **23** where the real one
        answers 19 — it did not fold repeated imports of the same module from
        the same file. Both public methods must route through the single
        private definition of what a crossing is, so the two axes cannot drift
        into disagreeing about the same import.
        """
        source = (
            project_root / 'src' / 'application' / 'common' / 'extraction_lane_policy.py'
        ).read_text(encoding='utf-8')
        tree = ast.parse(source)
        klass = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == 'ExtractionLanePolicy'
        )
        callers = {
            method.name
            for method in klass.body
            if isinstance(method, ast.FunctionDef)
            and any(
                isinstance(node, ast.Attribute) and node.attr == '_file_crossings'
                for node in ast.walk(method)
            )
        }
        self.assertEqual(
            callers, {'cross_lane_imports', 'measured_composition_root_crossings'},
            'both axes must share one definition of a crossing',
        )


class TestEverySiteCarriesAReasonedDisposition(_AxisCase):
    """G3 — a site without a reason is an invisible compromise."""

    def test_dispositions_come_from_the_closed_vocabulary(self):
        offenders = []
        for root, sites in self.governance['composition_root_crossings'].items():
            for site in sites:
                if site.get('disposition') not in CROSSING_DISPOSITIONS:
                    offenders.append((root, site.get('module'), site.get('disposition')))
        self.assertEqual(
            offenders, [],
            'unknown disposition(s); permitted: ' + ', '.join(sorted(CROSSING_DISPOSITIONS)),
        )

    def test_every_site_supplies_the_evidence_its_disposition_owes(self):
        """The obligation lives beside the vocabulary, not in whichever test looks."""
        offenders = []
        for root, sites in self.governance['composition_root_crossings'].items():
            for site in sites:
                missing = CompositionRootCrossing.from_dict(site).missing_evidence()
                if missing:
                    offenders.append((root, site.get('module'), missing))
        self.assertEqual(offenders, [], f'sites missing required evidence: {offenders}')

    def test_no_site_carries_evidence_its_disposition_forbids(self):
        """The mirror of the requirement — and the reason it exists.

        ``decided_repair_pending`` and ``split_blocker_undecided`` differed only
        by spelling, so an adversarial review swapped a real site between them
        with every count preserved and nothing went red. That distinction is
        what the ledger uses to say which debt is workable **today**, and it
        covered most of the sites. It is now structural: one token requires
        ``decided_on`` and the other forbids it.
        """
        offenders = []
        for root, sites in self.governance['composition_root_crossings'].items():
            for site in sites:
                forbidden = CompositionRootCrossing.from_dict(site).forbidden_evidence()
                if forbidden:
                    offenders.append((root, site.get('module'), forbidden))
        self.assertEqual(offenders, [], f'sites carrying forbidden evidence: {offenders}')

    def test_swapping_the_two_debt_tokens_is_structurally_visible(self):
        """Negative control for the axis above, grounded in a real site.

        Two propositions, unchanged since this control was written:
        a decided site relabelled *undecided* must trip ``forbidden_evidence``
        (it still carries ``decided_on``), and an undecided site relabelled
        *decided* must trip ``missing_evidence`` (it has no ``decided_on``).

        ⚠️ **The undecided exemplar is synthesised, and 2026-08-28 is when that
        became necessary.** The operator ruled B-2, every crossing acquired a
        decided direction, and ``split_blocker_undecided`` retired to zero
        sites — legitimately, with an explicit budget of ``0`` (see
        :meth:`test_a_retired_token_is_retired_on_purpose_and_not_by_omission`).
        This control used to read one real site of *each* token, so its
        non-emptiness anchor fired the moment the census emptied. **That was
        the anchor working**, not a defect, and the repair is deliberately the
        narrow one: keep the real site for the direction that still exists, and
        derive the retired side from that same real record by removing exactly
        the field the token forbids. Nothing about what is asserted changed.

        The synthesis is itself anchored — it must come from a real record, or
        this control would be testing a dictionary literal.
        """
        decided = [
            site
            for sites in self.governance['composition_root_crossings'].values()
            for site in sites if site['disposition'] == 'decided_repair_pending'
        ]
        self.assertTrue(decided, 'non-emptiness anchor: no decided site to swap')
        real = decided[0]
        self.assertIn('decided_on', real, 'a decided site must carry decided_on')

        swapped_to_undecided = dict(real, disposition='split_blocker_undecided')
        self.assertTrue(
            CompositionRootCrossing.from_dict(swapped_to_undecided).forbidden_evidence(),
            'a decided site relabelled undecided must be caught by the forbidden axis',
        )

        undecided = {k: v for k, v in real.items() if k != 'decided_on'}
        undecided['disposition'] = 'split_blocker_undecided'
        self.assertEqual(
            CompositionRootCrossing.from_dict(undecided).forbidden_evidence(), (),
            'the synthesised undecided exemplar must itself be a valid record, '
            'or the swap below proves nothing about relabelling',
        )
        swapped_to_decided = dict(undecided, disposition='decided_repair_pending')
        self.assertIn(
            'decided_on',
            CompositionRootCrossing.from_dict(swapped_to_decided).missing_evidence(),
            'an undecided site relabelled decided must be caught by the required axis',
        )

    def test_the_retired_token_is_still_a_working_vocabulary_member(self):
        """Retiring ``split_blocker_undecided`` must not retire its RULES.

        A token with no sites is one edit away from being a token with no
        meaning. This asserts the machinery still judges it: a record wearing
        that token is accepted without ``decided_on`` and rejected with it —
        which is what makes the next undecided crossing land in a working
        vocabulary rather than a decorative one.
        """
        self.assertIn('split_blocker_undecided', CROSSING_DEBT_DISPOSITIONS)
        self.assertEqual(
            self.governance['composition_root_crossing_debt_budget']
            .get('split_blocker_undecided'),
            0,
            'the retired token must keep an explicit zero budget',
        )
        base = {
            'module': 'application.central_contract.pagination',
            'disposition': 'split_blocker_undecided',
            'reason': 'x' * (MINIMUM_CROSSING_REASON_LENGTH + 10),
        }
        self.assertEqual(
            CompositionRootCrossing.from_dict(base).forbidden_evidence(), (),
            'an undecided record without decided_on must still be accepted',
        )
        self.assertTrue(
            CompositionRootCrossing.from_dict(
                dict(base, decided_on='someone decided')
            ).forbidden_evidence(),
            'an undecided record carrying decided_on must still be rejected',
        )

    def test_the_evidence_requirement_can_actually_fail(self):
        """Negative control per axis — an empty reason and each missing field."""
        self.assertIn(
            'reason',
            CompositionRootCrossing.from_dict(
                {'module': 'm', 'disposition': 'root_to_root', 'reason': '   '}
            ).missing_evidence(),
        )
        self.assertIn(
            'replacement',
            CompositionRootCrossing.from_dict(
                {'module': 'm', 'disposition': 'redundant_today', 'reason': 'r'}
            ).missing_evidence(),
        )
        self.assertIn(
            'residual',
            CompositionRootCrossing.from_dict(
                {'module': 'm', 'disposition': 'reowning_blocked_by_residual', 'reason': 'r'}
            ).missing_evidence(),
        )
        self.assertIn(
            'decision_ref',
            CompositionRootCrossing.from_dict(
                {'module': 'm', 'disposition': 'split_blocker_undecided', 'reason': 'r'}
            ).missing_evidence(),
        )

    def test_no_token_is_declared_without_a_site_that_earns_it(self):
        """A vocabulary invented for symmetry is a vocabulary nobody verifies.

        ``same_lane_after_reowning`` was in the first draft of this axis —
        "re-declare ownership, no code change" — and measurement refuted it for
        every candidate, so the token was deleted rather than kept empty.

        ⚠️ **A token whose last site was REPAID is a different case, and it
        keeps its name.** The rule is the one
        ``cross_lane_import_baseline_note`` already states for its own keys:
        *"a key that reaches 0 stays listed: deleting it would make a
        re-introduced edge look like a brand-new pair instead of a
        regression."* So a token with no sites is permitted exactly when its
        debt budget declares **0** — which is a claim someone had to write
        down, not an absence. A non-debt token cannot reach this state at all,
        because nothing budgets it.
        """
        used = {
            site['disposition']
            for sites in self.governance['composition_root_crossings'].values()
            for site in sites
        }
        budget = self.governance['composition_root_crossing_debt_budget']
        retired = {
            token for token in set(CROSSING_DISPOSITIONS) - used
            if budget.get(token) == 0
        }
        self.assertEqual(
            used | retired, set(CROSSING_DISPOSITIONS),
            'every token must be exercised by a real site, or be a debt token '
            'whose budget explicitly declares 0',
        )

    def test_a_retired_token_is_retired_on_purpose_and_not_by_omission(self):
        """The permission above must cost a declaration, or it is a hole.

        A token drops out of ``used`` the moment its last site is deleted. If
        that alone were enough, deleting a site would silently retire its whole
        class. The budget key is what makes it deliberate: it must be present
        AND zero.
        """
        used = {
            site['disposition']
            for sites in self.governance['composition_root_crossings'].values()
            for site in sites
        }
        budget = self.governance['composition_root_crossing_debt_budget']
        for token in sorted(set(CROSSING_DISPOSITIONS) - used):
            with self.subTest(token=token):
                self.assertIn(
                    token, CROSSING_DEBT_DISPOSITIONS,
                    f'{token} has no sites and is not a debt token, so nothing '
                    'declares that its emptiness was intended',
                )
                self.assertIn(
                    token, budget,
                    f'{token} has no sites and no budget key — its retirement '
                    'is an omission, not a decision',
                )
                self.assertEqual(budget[token], 0)


class TestDispositionsThatClaimAreExecuted(_AxisCase):
    """G5 + M-3a — a disposition that makes an empirical claim is run, not trusted."""

    def _sites_with(self, disposition: str) -> list[tuple[str, dict]]:
        return [
            (root, site)
            for root, sites in self.governance['composition_root_crossings'].items()
            for site in sites
            if site.get('disposition') == disposition
        ]

    @_NEEDS_TREE
    def test_redundant_today_names_a_replacement_the_same_file_already_imports(self):
        """Otherwise the token is a label, not a claim the import can go today.

        Read out of the importing file, not out of the manifest: a manifest
        that describes itself proves nothing about the tree.
        """
        sites = self._sites_with('redundant_today')
        if not sites:
            # Repaid, not forgotten. The budget is the receipt; assert it rather
            # than skipping quietly, so a deleted site cannot pass as a repair.
            self.assertEqual(
                self.governance['composition_root_crossing_debt_budget']
                .get('redundant_today'),
                0,
                'no redundant_today site remains, but the budget does not say 0 — '
                'either a site went missing or the ratchet was not written down',
            )
            self.skipTest('redundant_today is repaid (budget 0); nothing to execute')
        for root, site in sites:
            with self.subTest(root=root, module=site['module']):
                replacement = site['replacement']
                target = project_root / 'src' / (replacement.replace('.', '/') + '.py')
                self.assertTrue(
                    target.is_file(),
                    f'{replacement} does not resolve in this tree',
                )
                # The replacement must be reachable *without* crossing the
                # boundary the original import crosses — otherwise deleting the
                # old line relocates the crossing instead of closing it. Judged
                # by the ownership SSOT, not by where the file happens to sit.
                importing_lane = self.policy.lane_for_path(root)
                replacement_lane = self.policy.lane_for_module(replacement)
                self.assertTrue(
                    replacement_lane == importing_lane
                    or self.policy.may_depend_on(importing_lane, replacement_lane),
                    f'{replacement} is owned by {replacement_lane}, which '
                    f'{importing_lane} may not depend on — swapping to it would '
                    'move the crossing, not remove it',
                )
                tree = ast.parse((project_root / root).read_text(encoding='utf-8'))
                imported = {
                    node.module
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module
                }
                self.assertIn(
                    replacement, imported,
                    f'{root} does not already import {replacement}, so the '
                    'crossing is not deletable today and the token is wrong',
                )

                # ⚠️ The three checks above are satisfied by ANY already-imported
                # module in an allowed lane, which an adversarial review proved by
                # pointing `replacement` at `application.common.access_policy` —
                # every assertion passed and the resulting claim ("deleting this
                # import is safe") would `NameError`. The claim is about a SYMBOL,
                # so the symbol is what gets checked.
                symbol = site['symbol']
                bound_by_the_crossing = {
                    alias.asname or alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module == site['module']
                    for alias in node.names
                }
                self.assertIn(
                    symbol, bound_by_the_crossing,
                    f'{root} does not bind {symbol!r} from {site["module"]}, so the '
                    'declared symbol is not what this crossing brings in',
                )
                self.assertIn(
                    symbol,
                    {
                        node.name
                        for node in ast.walk(
                            ast.parse(target.read_text(encoding='utf-8'))
                        )
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                             ast.ClassDef))
                    } | {
                        alias.asname or alias.name.split('.')[0]
                        for node in ast.walk(
                            ast.parse(target.read_text(encoding='utf-8'))
                        )
                        if isinstance(node, (ast.Import, ast.ImportFrom))
                        for alias in node.names
                    } | {
                        t.id
                        for node in ast.walk(
                            ast.parse(target.read_text(encoding='utf-8'))
                        )
                        if isinstance(node, ast.Assign)
                        for t in node.targets if isinstance(t, ast.Name)
                    },
                    f'{replacement} does not define {symbol!r} — deleting the '
                    'crossing would leave the name unbound, so this is not a '
                    'replacement, only another import that happens to be present',
                )

    @_NEEDS_TREE
    def test_root_to_root_targets_another_declared_composition_root(self):
        sites = self._sites_with('root_to_root')
        self.assertTrue(sites, 'non-emptiness anchor')
        entry_points = {
            Path(rel).stem: rel for rel in self.policy.composition_roots
        }
        for root, site in sites:
            with self.subTest(root=root, module=site['module']):
                self.assertIn(
                    site['module'], entry_points,
                    'root_to_root must name another declared composition root',
                )

    @_NEEDS_TREE
    def test_reowning_blocked_by_residual_actually_raises_and_names_the_cause(self):
        """The claim is executed: re-own the target and re-measure.

        ⚠️ The ownership mutation is asserted to have applied **before** any
        result is read. Ownership comes from ``source_files``/``source_roots``;
        a first what-if that edited ``entries`` changed nothing while looking
        exactly like "no impact".
        """
        sites = self._sites_with('reowning_blocked_by_residual')
        self.assertTrue(sites, 'non-emptiness anchor')
        for root, site in sites:
            with self.subTest(root=root, module=site['module']):
                importing_lane = self.policy.lane_for_path(root)
                rel = site['module'].replace('.', '/') + '.py'
                target_rel = f'src/{rel}'
                self.assertTrue(
                    (project_root / target_rel).is_file(),
                    f'{target_rel} does not exist',
                )
                before_lane = self.policy.lane_for_path(target_rel)
                self.assertNotEqual(before_lane, importing_lane)

                mutated = copy.deepcopy(self.manifest)
                mutated['repositories'][importing_lane].setdefault(
                    'source_files', []
                ).append(target_rel)
                mutated_policy = _policy(mutated)

                # Assert the mutation applied before reading anything from it.
                self.assertEqual(
                    mutated_policy.lane_for_path(target_rel), importing_lane,
                    'the ownership mutation did not apply — a result read now '
                    'would be indistinguishable from "re-owning has no effect"',
                )

                after = mutated_policy.cross_lane_imports(project_root)
                caused = sorted({
                    module
                    for items in after.values()
                    for src, module in items
                    if src == target_rel
                })
                self.assertEqual(
                    caused, sorted(site['residual']),
                    'declared residual must equal the measured cause of the rise',
                )
                self.assertTrue(
                    caused,
                    'a site declared reowning_blocked_by_residual whose re-owning '
                    'raises nothing should be re-owned instead of declared',
                )


class TestTheAxisSaysWhatItDoesNotCheck(_AxisCase):
    """Which dispositions carry an executed claim, and which are attestations.

    An adversarial review measured the gap rather than arguing it: swapping
    ``supplied_by_target_repo`` with ``fetched_over_contract`` on two real sites
    left every assertion green, and so did replacing every ``reason`` with a
    sentence that is simply false. A reason floor stops ``"x"``; **nothing stops
    a fluent lie**, and no gate can — truth of prose is not decidable here.

    So the axis names its own edge. This is the discipline
    ``self_audit_message.VALUE_AXIS_LIMITATION`` already applies to its fifteen
    unchecked rows: a partial gate that stays quiet about its edges reads as
    full verification, and the next session builds on a confidence that was
    never earned.
    """

    def test_the_two_disposition_classes_partition_the_vocabulary(self):
        self.assertEqual(
            EXECUTED_CROSSING_DISPOSITIONS | UNVERIFIED_CROSSING_DISPOSITIONS,
            set(CROSSING_DISPOSITIONS),
        )
        self.assertEqual(
            EXECUTED_CROSSING_DISPOSITIONS & UNVERIFIED_CROSSING_DISPOSITIONS, set(),
        )
        self.assertTrue(
            UNVERIFIED_CROSSING_DISPOSITIONS,
            'a partition claiming nothing is unverified would itself be the '
            'overstatement this class exists to prevent',
        )

    def test_every_executed_disposition_is_actually_executed_somewhere(self):
        """The set is a claim about this file, so this file is what answers it."""
        source = Path(__file__).read_text(encoding='utf-8')
        for disposition in sorted(EXECUTED_CROSSING_DISPOSITIONS):
            with self.subTest(disposition=disposition):
                self.assertIn(
                    f"_sites_with('{disposition}')", source,
                    f'{disposition} is declared executed but no check in this '
                    'module gathers its sites',
                )

    def test_no_unverified_disposition_pretends_to_be_executed(self):
        source = Path(__file__).read_text(encoding='utf-8')
        for disposition in sorted(UNVERIFIED_CROSSING_DISPOSITIONS):
            with self.subTest(disposition=disposition):
                self.assertNotIn(
                    f"_sites_with('{disposition}')", source,
                    f'{disposition} is declared unverified but this module '
                    'gathers its sites — one of the two declarations is wrong',
                )

    def test_the_reason_floor_is_a_floor_and_not_a_non_emptiness_check(self):
        self.assertGreater(MINIMUM_CROSSING_REASON_LENGTH, 1)
        self.assertIn(
            'reason',
            CompositionRootCrossing.from_dict(
                {'module': 'm', 'disposition': 'root_to_root', 'reason': 'x'}
            ).missing_evidence(),
            'a one-character reason must not satisfy "has a reason"',
        )


class TestDebtIsBudgetedAgainstAnIndependentDeclaration(_AxisCase):
    """G4 — both sides are separately editable JSON, or the check cannot fail."""

    def test_derived_debt_counts_equal_the_declared_budget(self):
        self.assertEqual(
            self.policy.declared_crossing_debt_counts(),
            dict(self.governance['composition_root_crossing_debt_budget']),
        )

    def test_the_budget_covers_exactly_the_debt_dispositions(self):
        self.assertEqual(
            set(self.governance['composition_root_crossing_debt_budget']),
            set(CROSSING_DEBT_DISPOSITIONS),
        )

    def test_adding_a_debt_site_without_touching_the_budget_is_red(self):
        mutated = copy.deepcopy(self.manifest)
        root = next(iter(mutated['governance']['composition_root_crossings']))
        mutated['governance']['composition_root_crossings'][root].append({
            'module': 'logger_config',
            'disposition': 'redundant_today',
            'reason': 'synthetic',
            'replacement': 'application.common.logging_channel',
        })
        self.assertNotEqual(
            _policy(mutated).declared_crossing_debt_counts(),
            dict(mutated['governance']['composition_root_crossing_debt_budget']),
        )


class TestTheTwoAxesNameTheSameSites(_AxisCase):
    """G6 — the SSOT unification.

    One axis exempts these files entirely; the other has no concept of them
    (``grep -c composition scripts/check_extraction_import_boundaries.py`` is
    ``0``) and folds them into an integer. Whatever the staged checker reports
    for a file that maps back to a declared composition root must be a site
    this declaration already names — otherwise the two numbers describe
    different worlds and the reader cannot tell which.
    """

    @_NEEDS_TREE
    def test_staged_violations_inside_declared_roots_are_declared(self):
        import tempfile

        from check_extraction_import_boundaries import check_import_boundaries
        from prepare_headless_extraction_package import (
            build_extraction_plan, stage_extraction_package,
        )

        future_to_current = {}
        for lane, spec in self.manifest['repositories'].items():
            for entry in spec.get('entries') or ():
                future_to_current[entry['future_path']] = entry['current_path']

        lanes = [
            lane for lane, spec in self.manifest['repositories'].items()
            if spec.get('extraction_target')
        ]
        self.assertTrue(lanes, 'non-emptiness anchor')

        checked = 0
        with tempfile.TemporaryDirectory() as tmpdir:
            for lane in lanes:
                plan = build_extraction_plan(manifest_path=MANIFEST_PATH, repository=lane)
                stage_extraction_package(plan, Path(tmpdir))
                payload = check_import_boundaries(Path(tmpdir) / lane, lane=lane)
                for violation in payload['violations']:
                    staged_path = violation['path']
                    current = future_to_current.get(staged_path, staged_path)
                    if current not in self.declared:
                        continue
                    checked += 1
                    self.assertIn(
                        violation['module'], self.declared[current],
                        f'{current} -> {violation["module"]} is reported by the '
                        'staged axis but not declared by the site axis',
                    )
        self.assertGreater(
            checked, 0,
            'no staged violation mapped back to a declared composition root — '
            'the mapping broke and this check went vacuous',
        )


class TestTheAxisDidNotRegressWhatItTouched(_AxisCase):
    """M-7 — the monorepo axis is unchanged.

    ``cross_lane_import_baseline`` is deliberately NOT widened from 50 to 69.
    That would be a ratchet **up**, which its own declared rule forbids. Two
    questions get two axes; neither pretends to be the other.
    """

    @_NEEDS_TREE
    def test_cross_lane_import_baseline_still_matches_the_measurement(self):
        measured = {
            key: len(value)
            for key, value in self.policy.cross_lane_imports(project_root).items()
        }
        declared_nonzero = {
            key: value
            for key, value in self.governance['cross_lane_import_baseline'].items()
            if value
        }
        self.assertEqual(measured, declared_nonzero)

    @_NEEDS_TREE
    def test_the_hidden_total_is_the_difference_between_the_two_axes(self):
        """The number this axis exists for, asserted rather than narrated."""
        exempt_total = sum(
            len(value) for value in self.policy.cross_lane_imports(project_root).values()
        )
        site_total = sum(
            len(value)
            for value in self.policy.measured_composition_root_crossings(project_root).values()
        )
        # 47 -> 46 (2026-08-29, outbox-coupling-axis). ⚠️ 이 축에서 **감소는**
        # **결합이 실제로 없어졌다는 뜻**이다 — 옛 감소들과 달리 이번엔 사이트가
        # 옮겨간 것이 아니다. bootstrap 이 central_db_config 로 crossing 하던
        # 이유(``DatabasePort ⊇ ResultOutboxPort`` 가 측정 어댑터에게 릴레이
        # 구현을 강제)가 사라져 그 사이트가 **닫혔고**, 노드 합성 루트가 얻은
        # 것은 같은 모듈이 아니라 더 좁은 것(result_outbox_store)이다.
        self.assertEqual(exempt_total, 46)
        # 19 at the axis's landing; 18 after the redundant_today site was
        # repaid on 2026-08-27; 19 again on 2026-08-28 when
        # reference-import-door-closure gave the operator workbook importer its
        # own composition root. ⚠️ That one is an INCREASE and it is the honest
        # direction: application.headless.central_db_config was one declared
        # crossing covering two call sites in ONE file, and is now reached from
        # two files, so it is declared twice. No coupling was added — the
        # declaration became more precise, and the exempt total below is
        # unchanged, which is what says so. A literal rather than a derivation on
        # purpose: both sides deriving from one source could not fail.
        # ...and 17 on 2026-08-28 when central-contract-shared-kernel-move CLOSED
        # two of them. That one is a decrease with a different cause from every
        # movement above it: the crossings did not move file, they stopped being
        # crossings. application.platform.api_contracts became
        # application.central_contract.api_contracts under shared-kernel, which
        # both roots already declare as a dependency — so the imports are now
        # permitted and _file_crossings does not report them at all. The exempt
        # total moved with it (50 -> 47), and that it moved is what says the two
        # axes are still looking at the same tree.
        self.assertEqual(site_total, 17)
        self.assertEqual(
            exempt_total + site_total, 63,
            'the two axes must partition the crossings, not overlap or lose any',
        )
