"""Lane reachability & consumption-basis axis.

**One question, asked three times, answered three different ways.**

The repository split needs three answers and every one of them is *"what does
X reach"*:

1. the third argument of ``shared_kernel_closure_for_lane`` — three sizes for
   the same set (22 / 27 / 41) circulate because no record ever wrote down
   which basis produced them;
2. *"what is web-related"* — carried as a name-match estimate whose own author
   wrote *"that number is not precise"*;
3. *"what follows ``session_api_composition`` out"* — never measured.

A closure that is re-derived per session is a closure whose answer nobody can
reproduce, and this axis exists because that already happened. So the
derivation is **one** (:meth:`ExtractionLanePolicy.reachable_modules`), the two
parameters that change its answer are **closed vocabularies** with typed
errors instead of defaults, and every number is recorded beside the token that
produced it.

⚠️ **The two vocabularies are not stylistic.** Measured on this tree, choosing
``module_level`` for the artifact question reports ``main.py`` and
``test_runner_core`` as *absent from the GUI build* — which would authorise
shipping the GUI's own entry points to another repository. Choosing the
delivery basis for an ownership question returns a plausible number for a lane
that has no box. Both mistakes look like answers.
"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / 'src'
for _p in (PROJECT_ROOT, SRC_ROOT, PROJECT_ROOT / 'scripts'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fcc_test_contracts.common.extraction_lane_policy import (  # noqa: E402
    CONSUMED_BASES,
    CONSUMED_BASIS_DELIVERY,
    CONSUMED_BASIS_OWNERSHIP,
    IMPORT_EDGE_MODULE_LEVEL,
    IMPORT_EDGE_RELATIONS,
    IMPORT_EDGE_STATIC,
    MINIMUM_CROSSING_REASON_LENGTH,
    PYTHON_SOURCE_ROOT,
    SHARED_KERNEL_CLOSURE_KIND,
    SHARED_KERNEL_LANE,
    ExtractionLanePolicy,
    UnknownConsumedBasis,
    UnknownImportEdgeRelation,
    _imported_modules_of,
    _package_of,
)
from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact  # noqa: E402

# A literal, not a computed argument. The delivered-artifact-path axis reads
# this call statically and classifies a computed argument as "dynamic, cannot
# read", which removes this file from its judgement while making the census
# look healthier — a trap this repository has already walked into once.
MANIFEST_PATH = resolve_repo_artifact(
    __file__, 'docs/api/headless_contract_extraction_manifest.v1.json',
)
BUILD_NUITKA_PATH = PROJECT_ROOT / 'build_nuitka.py'

#: The lane whose deployment artifact decides what may leave. Derived below
#: from the manifest rather than asserted: it is the lane that owns the build
#: entry point.
_ARTIFACT_LANE = 'fcc-unlicensed-headless'

#: How a module comes to be in the GUI artifact. Two tokens, because the two
#: take **different repairs**: an import-resident module leaves when its
#: importer stops naming it, and a package-resident one is shipped by
#: ``--include-package`` whatever the imports say, so it leaves only by moving
#: out of the force-included tree or by the build rule being narrowed.
_RESIDENCY_IMPORT = 'import'
_RESIDENCY_PACKAGE = 'package'
_RESIDENCY_TOKENS = (_RESIDENCY_IMPORT, _RESIDENCY_PACKAGE)

#: Whether this tree can be *measured*, as opposed to merely *read*.
#:
#: This file travels into the ``fcc-test-contracts`` box (it imports the
#: contracts-owned lane policy), and that box deliberately contains neither
#: ``src/`` nor ``build_nuitka.py`` — the provider lane is not an extraction
#: target. The declaration questions ("does every site carry a reason", "is the
#: vocabulary closed") are answerable there and must keep running; the
#: measurement questions are **unanswerable**, which is not the same as wrong.
#:
#: ⚠️ A skip is quieter than a failure, so this predicate is asserted **false-
#: negative-proof** below: :class:`TestTheMeasurementTreeIsPresentInTheMonorepo`
#: fails if the monorepo ever takes this branch. Without that, a typo in either
#: path would silently turn every measurement in this file into a pass.
_MEASUREMENT_TREE = (
    (PROJECT_ROOT / PYTHON_SOURCE_ROOT.rstrip('/')).is_dir()
    and BUILD_NUITKA_PATH.is_file()
)
_NO_TREE_REASON = (
    'delivered box: neither src/ nor build_nuitka.py is here, so artifact '
    'membership cannot be measured — only the declaration can be read'
)

#: Marks a test that needs the monorepo tree to answer at all.
_requires_tree = unittest.skipUnless(_MEASUREMENT_TREE, _NO_TREE_REASON)


def _policy() -> ExtractionLanePolicy:
    return ExtractionLanePolicy.from_path(MANIFEST_PATH)


def _manifest() -> dict:
    return json.loads(Path(MANIFEST_PATH).read_text(encoding='utf-8'))


def _nuitka_constant(name: str):
    """Read one module-level constant out of ``build_nuitka.py`` by AST.

    The build file is the single source of truth for *what the GUI program
    contains*; this axis reads it and never writes it. Reading by AST rather
    than importing keeps the answer independent of whether Nuitka, PySide6 or
    a display are present.
    """
    tree = ast.parse(BUILD_NUITKA_PATH.read_text(encoding='utf-8'))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Constant):
            return value.value
        if isinstance(value, ast.List):
            return [e.value for e in value.elts if isinstance(e, ast.Constant)]
    raise AssertionError(f'build_nuitka.py has no module-level {name}')


def _under(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + '.')


def _gui_artifact_seeds(
    policy: ExtractionLanePolicy, root: Path,
) -> tuple[tuple[str, ...], frozenset[str], tuple[str, ...]]:
    """``(seeds, package_forced, barriers)`` for the GUI build, from the build file.

    ``INCLUDE_PACKAGES`` force-ships whole trees, ``INCLUDE_MODULES`` names the
    flat ``src/`` modules reached dynamically, the entry script seeds the static
    follow, and ``EXCLUDE_MODULES`` (``--nofollow-import-to``) is a barrier.
    Nothing here decides anything the build file has not already decided.
    """
    entry_file = str(_nuitka_constant('MAIN_FILE')).replace('\\', '/')
    assert entry_file.startswith(PYTHON_SOURCE_ROOT) and entry_file.endswith('.py')
    entry = entry_file[len(PYTHON_SOURCE_ROOT):-len('.py')].replace('/', '.')

    packages = _nuitka_constant('INCLUDE_PACKAGES')
    modules = _nuitka_constant('INCLUDE_MODULES')
    barriers = tuple(_nuitka_constant('EXCLUDE_MODULES'))

    index = policy.source_module_index(root)
    forced = frozenset(
        m for m in index
        if any(_under(m, p) for p in packages)
        and not any(_under(m, b) for b in barriers)
    )
    return (entry, *modules, *sorted(forced)), forced, barriers


def gui_artifact_modules(policy: ExtractionLanePolicy, root: Path) -> frozenset[str]:
    """Modules the delivered GUI program contains, derived from the build file.

    ⚠️ :data:`IMPORT_EDGE_STATIC`, deliberately. Nuitka's import-following
    follows function-local imports too, and the ``module_level`` relation
    exists for the opposite question (*"would excluding this necessarily break
    the frozen build"*). Using it here is not conservative, it is wrong in the
    unsafe direction.

    ⚠️ **This was set algebra until 2026-08-29 and set algebra answers a
    different question.** The old body walked the entry closure, then unioned
    the ``INCLUDE_PACKAGES`` members, then subtracted the excluded names — and
    each of those two orderings is a defect of its own, in *opposite*
    directions, which is why neither showed up as an implausible number:

    * subtracting *after* the walk let the closure travel **through**
      ``infrastructure.adapters.driving.api``, a ``--nofollow-import-to``
      target the frozen program does not contain. 31 phantom modules, two of
      them declared split blockers with work scoped against them;
    * unioning the packages *after* the walk meant a force-included module's
      own imports were never followed. Nuitka compiles what
      ``--include-package`` names and resolves its imports like any other
      compiled module, so this hid a real, module-level dependency edge —
      ``application.reporting.db_only_report_reconstruction_runner`` →
      ``application.headless.platform_report_reconstruction_evidence`` — and
      with it three ``fcc-test-platform`` modules the GUI genuinely ships.

    Repairing only the first (the one the 2026-08-29 handoff named) takes the
    inventory to three and is **wrong in the unsafe direction**: it would
    authorise two modules to leave that the frozen program carries. Both
    orderings are the same mistake — deciding membership outside the walk — so
    the fix is one walk whose seeds and barriers are both handed to it.
    """
    seeds, _forced, barriers = _gui_artifact_seeds(policy, root)
    return policy.reachable_modules(
        root, seeds, edges=IMPORT_EDGE_STATIC, barriers=barriers,
    )


def gui_artifact_package_forced(
    policy: ExtractionLanePolicy, root: Path,
) -> frozenset[str]:
    """Artifact residents ``--include-package`` ships whatever imports say.

    The distinction the ``door`` field alone cannot express. A door is an
    *import*, so "close the door and it leaves" is only true for a module that
    is in the artifact **because** something imports it. A module under an
    ``--include-package`` tree is shipped by the build rule itself: every one
    of its importers can go and it stays. Measured, two declared blockers are
    in that state, and the outbox wave was scoped as door-closing against one
    of them.
    """
    _seeds, forced, _barriers = _gui_artifact_seeds(policy, root)
    return forced & gui_artifact_modules(policy, root)


def measured_split_blockers(
    policy: ExtractionLanePolicy, root: Path,
) -> dict[str, str]:
    """Artifact residents whose lane the artifact's own lane may not depend on.

    Both halves derived. "Web-related" is not a date and not a name match: it
    is *the GUI program carries it* AND *its owner is a lane this program is
    forbidden to reach*. Returns ``{module: owning lane}``.
    """
    index = policy.source_module_index(root)
    forbidden = {
        lane for lane in policy.owners
        if not policy.may_depend_on(_ARTIFACT_LANE, lane)
    }
    return {
        module: policy.lane_for_path(index[module])
        for module in gui_artifact_modules(policy, root)
        if policy.lane_for_path(index[module]) in forbidden
    }


def provider_side_doors(
    policy: ExtractionLanePolicy, root: Path, blockers: dict[str, str],
) -> dict[str, tuple[str, ...]]:
    """For each blocker, the artifact modules that are *not* blockers and import it.

    The distinction is the whole value of the inventory: a blocker with no door
    of its own leaves for free once its siblings do, and a blocker with four
    doors is a design question rather than a move.
    """
    index = policy.source_module_index(root)
    doors: dict[str, set[str]] = {module: set() for module in blockers}
    for module in gui_artifact_modules(policy, root):
        if module in blockers:
            continue
        rel = index[module]
        for target in _imported_modules_of(
            root / rel, package=_package_of(rel), edges=IMPORT_EDGE_STATIC,
        ):
            if target in doors:
                doors[target].add(module)
    return {module: tuple(sorted(found)) for module, found in doors.items()}


@_requires_tree
class TestTheClosureHasOneDefinition(unittest.TestCase):
    """M-1 — the repository walks imports transitively in exactly one place.

    A second implementation is not a style problem here. The previous private
    copy read ``node.level == 0`` only, so it could not see a relative import
    at all, and it disagreed with the policy's own reader by two modules while
    both looked correct.
    """

    #: Files allowed to contain a transitive-import fixpoint. Exactly one, and
    #: this axis's own helpers are not among them — ``gui_artifact_modules``
    #: composes the SSOT, it does not re-walk.
    _CLOSURE_OWNER = 'src/application/common/extraction_lane_policy.py'

    def _python_files(self) -> list[Path]:
        policy = _policy()
        found: list[Path] = []
        for root_name in ('src', 'scripts', 'tests'):
            base = PROJECT_ROOT / root_name
            for path in base.rglob('*.py'):
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                if policy.is_excluded(rel):
                    continue
                found.append(path)
        return found

    def test_the_census_is_not_vacuous(self):
        self.assertGreater(len(self._python_files()), 1000)

    #: Second import closures that exist and are **not** repaid by this wave,
    #: with the reason. Ratchet-down only: a new entry is a decision, and the
    #: silent alternative — narrowing the detector until the census is empty —
    #: is the failure this repository has named ("narrowing a predicate loses
    #: the unenumerated"). Filed in the ledger with an owner.
    _KNOWN_SECOND_CLOSURES = {
        'tests/test_dev_seed_manifest_provider_leg.py::_static_dev_seed_closure':
            'Answers a different question — which dev-seed manifest legs a '
            'provider reaches — over a different index, and its repair belongs '
            'to whichever wave owns the dev-seed manifest.',
    }

    @staticmethod
    def _is_transitive_import_closure(node: ast.AST) -> bool:
        """Structure, not spelling.

        ⚠️ The first version of this predicate matched substrings of
        ``ast.dump`` and therefore matched **string literals** — including its
        own source, and including two unrelated worklists. A seal that asks
        about spelling is true in defective code too. This one asks about
        nodes: does the function *reference* an import-reading name (never a
        constant), and does it drive a worklist loop that feeds itself?
        """
        referenced: set[str] = set()
        pops = extends = False
        loops = [inner for inner in ast.walk(node) if isinstance(inner, ast.While)]
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name):
                referenced.add(inner.id)
            elif isinstance(inner, ast.Attribute):
                referenced.add(inner.attr)
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
                if inner.func.attr == 'pop':
                    pops = True
                elif inner.func.attr in {'extend', 'append'}:
                    extends = True
        reads_imports = bool(
            {'_imported_modules_of', 'ImportFrom', 'Import'} & referenced
        )
        # ⚠️ The third condition is what separates a *module-graph* closure
        # from a *symbol* closure. Without it the predicate flagged a capsule
        # builder that walks the names inside one already-parsed tree and never
        # opens a second file — it references ``ast.Import`` because it copies
        # import statements, not because it follows them. A closure of modules
        # must leave the file it started in, so the worklist body has to read
        # or parse another one.
        leaves_the_file = any(
            isinstance(inner, ast.Call)
            and (
                (isinstance(inner.func, ast.Attribute)
                 and inner.func.attr in {'parse', 'read_text', 'read_bytes'})
                or (isinstance(inner.func, ast.Name)
                    and inner.func.id == '_imported_modules_of')
            )
            for loop in loops for inner in ast.walk(loop)
        )
        return reads_imports and bool(loops) and pops and extends and leaves_the_file

    def _measured_second_closures(self) -> list[str]:
        offenders: list[str] = []
        for path in self._python_files():
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if rel == self._CLOSURE_OWNER:
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if self._is_transitive_import_closure(node):
                    offenders.append(f'{rel}::{node.name}')
        return sorted(offenders)

    def test_only_one_unrecorded_file_walks_imports_transitively(self):
        """A worklist loop that feeds itself from an import reader.

        That is what a transitive closure *is*, and it is what a second copy
        would have to do. Judged by **set equality** against the recorded
        exceptions, so a new copy is red and a repaid one is red too — a
        baseline nobody lowers is a baseline nobody believes.
        """
        self.assertEqual(
            self._measured_second_closures(), sorted(self._KNOWN_SECOND_CLOSURES),
            'the set of second transitive import closures changed. One '
            'definition — ExtractionLanePolicy.reachable_modules — or the two '
            'answer the same question differently and nobody notices.',
        )

    def test_the_policy_itself_still_contains_the_one_definition(self):
        """M-8 — the equality above would also pass if the SSOT disappeared."""
        tree = ast.parse(
            (PROJECT_ROOT / self._CLOSURE_OWNER).read_text(encoding='utf-8')
        )
        owned = [
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and self._is_transitive_import_closure(node)
        ]
        self.assertIn('reachable_modules', owned)

    def test_the_detector_fires_on_a_synthetic_second_copy(self):
        """M-8 — the recorded-set result must be capable of growing."""
        source = (
            'import ast\n'
            'def walk(seeds, index):\n'
            '    seen, pending = set(), list(seeds)\n'
            '    while pending:\n'
            '        name = pending.pop()\n'
            '        tree = ast.parse(index[name])\n'
            '        for node in ast.walk(tree):\n'
            '            if isinstance(node, ast.ImportFrom):\n'
            '                pending.extend(a.name for a in node.names)\n'
            '        seen.add(name)\n'
            '    return seen\n'
        )
        self.assertTrue(
            self._is_transitive_import_closure(ast.parse(source).body[1])
        )

    def test_the_detector_ignores_the_two_false_positives_it_first_produced(self):
        """Negative controls, both taken from real code this axis mis-flagged.

        (a) a plain worklist that never touches imports — the first version
        matched it because its *source text* contained the substrings looked
        for; (b) a symbol closure inside one already-parsed tree, which
        references ``ast.Import`` because it copies import statements rather
        than following them. Both are pop/extend loops and neither computes a
        module graph.
        """
        plain = (
            'def replicate(seeds):\n'
            '    pending, done = list(seeds), []\n'
            '    while pending:\n'
            '        item = pending.pop()\n'
            '        done.append(item)\n'
            '        pending.extend(item.children)\n'
            '    return done\n'
        )
        symbol_closure = (
            'import ast\n'
            'def build_capsule(tree, symbols):\n'
            '    imports = {}\n'
            '    for node in tree.body:\n'
            '        if isinstance(node, (ast.Import, ast.ImportFrom)):\n'
            '            imports[node] = node\n'
            '    pending, selected = ["Root"], []\n'
            '    while pending:\n'
            '        name = pending.pop()\n'
            '        selected.append(name)\n'
            '        pending.extend(symbols[name].deps)\n'
            '    return selected\n'
        )
        for label, source, node_index in (
            ('plain worklist', plain, 0), ('symbol closure', symbol_closure, 1),
        ):
            with self.subTest(control=label):
                self.assertFalse(self._is_transitive_import_closure(
                    ast.parse(source).body[node_index]
                ))


class TestTheEdgeRelationIsAChoice(unittest.TestCase):
    """M-2 — two relations, both load-bearing, unknown token raises."""

    def setUp(self):
        self.policy = _policy()

    @_requires_tree
    def test_the_vocabulary_is_closed_and_both_members_are_used(self):
        self.assertEqual(
            IMPORT_EDGE_RELATIONS,
            frozenset({IMPORT_EDGE_MODULE_LEVEL, IMPORT_EDGE_STATIC}),
        )
        used = (PROJECT_ROOT / 'tests/test_build_artifact_invariants.py').read_text(
            encoding='utf-8'
        )
        self.assertIn(
            'IMPORT_EDGE_MODULE_LEVEL', used,
            'the module_level relation has no caller — a vocabulary member '
            'nobody uses is a member nobody maintains',
        )
        self.assertIn('IMPORT_EDGE_STATIC', Path(__file__).read_text(encoding='utf-8'))

    def test_an_unknown_relation_raises_instead_of_defaulting(self):
        with self.assertRaises(UnknownImportEdgeRelation):
            self.policy.reachable_modules(PROJECT_ROOT, ('main_entry',), edges='all')
        with self.assertRaises(UnknownImportEdgeRelation):
            _imported_modules_of(
                SRC_ROOT / 'main_entry.py', package='', edges='module-level',
            )

    @_requires_tree
    def test_the_closure_crosses_a_package_through_its_init(self):
        """A package is a node in the graph, not a namespace the walk skips.

        ⚠️ **Added because a mutation survived.** Making
        :meth:`source_module_index` drop ``__init__.py`` left every other
        assertion in this file green — the residents happen to be leaf modules
        — while the closure lost the ability to cross a package at all. The
        shared-kernel closure already paid for exactly this once: adding the
        ``__init__`` chain *outside* the fixpoint left ``domain/models/`` in the
        box with its own imports never followed, and seven delivered tests
        could not be collected.

        The case is **derived from the tree**, not named: find a package whose
        ``__init__.py`` imports a first-party module, and require the closure
        seeded at the package name to reach it. Naming one would go stale the
        day that file changes.
        """
        policy = self.policy
        index = policy.source_module_index(PROJECT_ROOT)
        candidates: list[tuple[str, str]] = []
        for dotted, rel in sorted(index.items()):
            if not rel.endswith('/__init__.py'):
                continue
            for target in sorted(_imported_modules_of(
                PROJECT_ROOT / rel, package=_package_of(rel), edges=IMPORT_EDGE_STATIC,
            )):
                if target in index and target != dotted:
                    candidates.append((dotted, target))
                    break
        self.assertTrue(
            candidates,
            'no package __init__.py imports a first-party module, so this '
            'assertion cannot distinguish an index that names packages from '
            'one that does not — re-derive the case rather than deleting it',
        )
        for package, target in candidates[:3]:
            with self.subTest(package=package):
                self.assertIn(package, index, 'the index does not name the package')
                reached = policy.reachable_modules(
                    PROJECT_ROOT, (package,), edges=IMPORT_EDGE_STATIC,
                )
                self.assertIn(
                    target, reached,
                    f'seeding at package {package!r} did not reach {target!r}, '
                    'which its __init__.py imports — the walk cannot cross a package',
                )

    @_requires_tree
    def test_module_level_is_contained_in_static_and_they_differ(self):
        """Derived on the real tree, both directions.

        Containment alone would pass for two identical relations, and equality
        would mean the vocabulary has one member wearing two names.
        """
        seeds = ('main_entry',)
        narrow = self.policy.reachable_modules(
            PROJECT_ROOT, seeds, edges=IMPORT_EDGE_MODULE_LEVEL,
        )
        wide = self.policy.reachable_modules(
            PROJECT_ROOT, seeds, edges=IMPORT_EDGE_STATIC,
        )
        self.assertTrue(narrow, 'the narrow relation reached nothing')
        self.assertLess(
            len(narrow), len(wide),
            'module_level and static agree on this tree, which would mean the '
            'distinction this axis rests on does not exist',
        )
        self.assertTrue(narrow <= wide)

    @_requires_tree
    def test_choosing_the_narrow_relation_would_evict_the_gui_entry_points(self):
        """The measurement that makes the ``static`` choice non-arbitrary.

        Under ``module_level`` seeds, the artifact model reports modules the GUI
        plainly runs as absent from the build. Recording it as an executed
        assertion rather than a sentence keeps the next reader from "fixing"
        the relation back.
        """
        modules = _nuitka_constant('INCLUDE_MODULES')
        entry_file = str(_nuitka_constant('MAIN_FILE')).replace('\\', '/')
        entry = entry_file[len(PYTHON_SOURCE_ROOT):-len('.py')].replace('/', '.')
        narrow = self.policy.reachable_modules(
            PROJECT_ROOT, tuple([entry, *modules]), edges=IMPORT_EDGE_MODULE_LEVEL,
        )
        index = self.policy.source_module_index(PROJECT_ROOT)
        evicted = sorted(
            m for m in ('main', 'test_runner_core')
            if m in index and m not in narrow
        )
        self.assertTrue(
            evicted,
            'the narrow relation no longer evicts a GUI runtime module — the '
            'reason recorded for choosing IMPORT_EDGE_STATIC has expired and '
            'must be re-measured rather than restated',
        )


class TestTheConsumedBasisIsAChoice(unittest.TestCase):
    """M-3 — the argument that made one set have three sizes is now named."""

    def setUp(self):
        self.policy = _policy()

    def test_the_vocabulary_is_closed(self):
        self.assertEqual(
            CONSUMED_BASES,
            frozenset({CONSUMED_BASIS_DELIVERY, CONSUMED_BASIS_OWNERSHIP}),
        )

    def test_an_unknown_basis_raises_instead_of_defaulting(self):
        with self.assertRaises(UnknownConsumedBasis):
            self.policy.consumed_for_lane(PROJECT_ROOT, 'fcc-test-platform', 'planned')

    @_requires_tree
    def test_the_two_bases_disagree_on_the_real_tree(self):
        """If they agreed there would be nothing to have been confused about."""
        lane = 'fcc-test-platform'
        ownership = self.policy.consumed_for_lane(
            PROJECT_ROOT, lane, CONSUMED_BASIS_OWNERSHIP,
        )
        self.assertTrue(ownership, 'the ownership basis found nothing')
        kernel_by_ownership = self.policy.shared_kernel_closure_for_lane(
            PROJECT_ROOT, lane, ownership,
        )
        self.assertTrue(kernel_by_ownership)

        from prepare_headless_extraction_package import build_extraction_plan
        plan = build_extraction_plan(manifest_path=Path(MANIFEST_PATH), repository=lane)
        delivery = self.policy.consumed_for_lane(
            PROJECT_ROOT, lane, CONSUMED_BASIS_DELIVERY, planned=plan['packages'][lane],
        )
        self.assertTrue(delivery, 'the delivery basis found nothing')
        kernel_by_delivery = self.policy.shared_kernel_closure_for_lane(
            PROJECT_ROOT, lane, delivery,
        )
        self.assertNotEqual(
            set(kernel_by_ownership), set(kernel_by_delivery),
            'the two bases produce the same kernel closure, which would make '
            'the vocabulary decorative — and would leave 22/27/41 unexplained',
        )

    def test_the_delivery_basis_drops_the_closure_entry_from_its_own_seed(self):
        """The filter that was written twice, asserted once, with a counter-case."""
        lane = 'fcc-test-platform'
        planned = [
            {'current_path': 'src/application/central_contract/pagination.py', 'kind': 'python_module'},
            {'current_path': 'src/domain/models/test_plan.py', 'kind': SHARED_KERNEL_CLOSURE_KIND},
        ]
        self.assertEqual(
            self.policy.consumed_for_lane(
                PROJECT_ROOT, lane, CONSUMED_BASIS_DELIVERY, planned=planned,
            ),
            ('src/application/central_contract/pagination.py',),
        )

    @_requires_tree
    def test_the_ownership_basis_answers_for_a_lane_with_no_box(self):
        """The case the delivery basis structurally cannot answer.

        ``fcc-unlicensed-headless`` is ``extraction_target: false``, so its
        delivery basis is near-empty while it owns hundreds of files. Quoting a
        delivery-basis number for it is how "which kernel modules do both lanes
        read" acquired an answer nobody could reproduce.
        """
        owned = self.policy.consumed_for_lane(
            PROJECT_ROOT, _ARTIFACT_LANE, CONSUMED_BASIS_OWNERSHIP,
        )
        self.assertGreater(len(owned), 100)
        closure = self.policy.shared_kernel_closure_for_lane(
            PROJECT_ROOT, _ARTIFACT_LANE, owned,
        )
        self.assertTrue(closure)
        for rel in closure:
            self.assertEqual(self.policy.lane_for_path(rel), SHARED_KERNEL_LANE)


@_requires_tree
class TestConsumedHasOneProducer(unittest.TestCase):
    """M-4 — the kind filter that seeds the closure exists once."""

    _PRODUCER = 'src/application/common/extraction_lane_policy.py'
    _CONSUMERS = (
        'scripts/prepare_headless_extraction_package.py',
        'tests/test_contracts_platform_extraction_manifest.py',
    )

    @staticmethod
    def _kind_comprehensions(tree: ast.AST) -> list[tuple[int, type]]:
        """Comprehensions over planned entries filtered on the entry kind.

        Returns ``(lineno, comparison operator)``. **The operator is the whole
        distinction**, and conflating the two is the mistake this detector made
        first: ``!= SHARED_KERNEL_CLOSURE_KIND`` builds the *seed* (everything
        the box carries except the closure entry, which cannot seed itself),
        while ``== SHARED_KERNEL_CLOSURE_KIND`` collects the *result* (what the
        closure entry planned). Only the first is a second copy of the seed
        derivation; the second is the parity invariant's own left-hand side and
        must stay exactly where it is.
        """
        found: list[tuple[int, type]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
                continue
            names = {
                inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)
            }
            if 'SHARED_KERNEL_CLOSURE_KIND' not in names:
                continue
            constants = {
                inner.value for inner in ast.walk(node)
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
            }
            if 'current_path' not in constants:
                continue
            for compare in ast.walk(node):
                if isinstance(compare, ast.Compare) and compare.ops:
                    found.append((node.lineno, type(compare.ops[0])))
                    break
        return found

    def test_no_consumer_rebuilds_the_seed_by_filtering_on_the_kind(self):
        offenders = []
        for rel in self._CONSUMERS:
            tree = ast.parse((PROJECT_ROOT / rel).read_text(encoding='utf-8'))
            offenders.extend(
                f'{rel}:{lineno}'
                for lineno, op in self._kind_comprehensions(tree)
                if op in (ast.NotEq, ast.NotIn)
            )
        self.assertEqual(
            sorted(offenders), [],
            'a consumer rebuilds the delivery seed instead of calling '
            'consumed_for_lane. The parity invariant would then pin the plan '
            f'to a derivation that is free to disagree with it: {offenders}',
        )

    def test_the_scan_actually_reaches_kind_comprehensions(self):
        """M-8 — a detector that finds nothing to look at reports "clean".

        The parity invariant legitimately keeps ``== SHARED_KERNEL_CLOSURE_KIND``
        comprehensions. If those stop being found, the scan above has stopped
        reading the file and its emptiness means nothing.
        """
        tree = ast.parse(
            (PROJECT_ROOT / 'tests/test_contracts_platform_extraction_manifest.py')
            .read_text(encoding='utf-8')
        )
        equalities = [
            lineno for lineno, op in self._kind_comprehensions(tree) if op is ast.Eq
        ]
        self.assertGreaterEqual(len(equalities), 2)

    def test_every_consumer_calls_the_entry_point(self):
        for rel in self._CONSUMERS:
            with self.subTest(consumer=rel):
                source = (PROJECT_ROOT / rel).read_text(encoding='utf-8')
                self.assertIn('consumed_for_lane', source)
                self.assertIn('CONSUMED_BASIS_', source)

    def test_the_detector_fires_on_a_synthetic_rebuild(self):
        """M-8 — the clean result above is capable of failing, and only on ``!=``."""
        rebuild = ast.parse(
            "seed = tuple(i['current_path'] for i in items "
            "if i['kind'] != SHARED_KERNEL_CLOSURE_KIND)\n"
        )
        self.assertEqual(
            [op for _, op in self._kind_comprehensions(rebuild)], [ast.NotEq],
        )
        collect = ast.parse(
            "planned = {i['current_path'] for i in items "
            "if i['kind'] == SHARED_KERNEL_CLOSURE_KIND}\n"
        )
        self.assertEqual(
            [op for _, op in self._kind_comprehensions(collect)], [ast.Eq],
        )


@_requires_tree
class TestTheArtifactModelIsDerived(unittest.TestCase):
    """M-6 — the GUI artifact comes from the build file, with no literals."""

    def setUp(self):
        self.policy = _policy()

    def test_the_three_declarations_are_read_and_non_empty(self):
        for name in ('INCLUDE_PACKAGES', 'INCLUDE_MODULES', 'EXCLUDE_MODULES'):
            with self.subTest(constant=name):
                self.assertTrue(_nuitka_constant(name))
        self.assertTrue(str(_nuitka_constant('MAIN_FILE')).startswith(PYTHON_SOURCE_ROOT))

    def test_the_artifact_is_a_strict_subset_of_the_source_tree(self):
        index = self.policy.source_module_index(PROJECT_ROOT)
        artifact = gui_artifact_modules(self.policy, PROJECT_ROOT)
        self.assertGreater(len(index), 900, 'the source index is implausibly small')
        self.assertTrue(artifact <= set(index))
        self.assertLess(
            len(artifact), len(index),
            'the artifact contains every source module, which would make the '
            '"may this leave" question vacuously "no" for everything',
        )
        self.assertGreater(len(artifact), 500)

    def test_the_axis_carries_no_package_or_module_literal(self):
        """The build file's vocabulary must not be restated here.

        Restating it is how the axis would keep answering after the build file
        changed — the exact failure mode the manifest note names.
        """
        source = Path(__file__).read_text(encoding='utf-8')
        for name in _nuitka_constant('INCLUDE_PACKAGES'):
            with self.subTest(package=name):
                self.assertNotIn(f"'{name}'", source)

    def test_the_build_file_is_untouched_by_this_wave(self):
        """M-6 — this axis reads ``build_nuitka.py`` and never writes it."""
        import subprocess
        merge_base = subprocess.run(
            ['git', 'merge-base', 'HEAD', 'origin/main'],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        )
        if merge_base.returncode != 0:
            self.skipTest('no origin/main to compare against')
        changed = subprocess.run(
            ['git', 'diff', '--name-only', merge_base.stdout.strip(), 'HEAD'],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        )
        if changed.returncode != 0:
            self.skipTest('git diff unavailable')
        self.assertNotIn('build_nuitka.py', changed.stdout.split())


@_requires_tree
class TestTheMutationBatteryStillApplies(unittest.TestCase):
    """M-B — a mutation that no longer applies asserts nothing, quietly.

    ``mutation_harness`` reports ``NOT-APPLIED`` per mutation and treats it as a
    failure, which is right — but only for whoever runs the battery, and the
    battery is minutes-long so it is not in any routine lane. Measured
    2026-08-29, **three** of its mutations had been unapplicable since PR
    #547/#556 retired the inventory records they quoted by hand: the declaration
    arm, the "no door" arm, and the reason-is-not-a-label arm. Every seal in this
    file was green the whole time and three of the defects it claims to catch had
    nobody checking.

    This is the cheap half of the repair (the other half is that those three
    mutations now derive their text from the manifest). It asks the one question
    that goes red the moment a target drifts again, in a lane that actually runs.
    """

    _BATTERY = PROJECT_ROOT / 'scripts' / 'mutation_lane_reachability_axis.py'

    def _mutations(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'lane_reachability_mutation_battery', self._BATTERY,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.MUTATIONS

    def test_the_battery_exists_and_is_not_empty(self):
        self.assertTrue(self._BATTERY.is_file(), f'{self._BATTERY} is gone')
        self.assertGreater(
            len(self._mutations()), 5,
            'a battery this small is not covering the vocabulary it claims to',
        )

    def test_every_mutation_still_matches_its_target(self):
        """Pre- **or** post-mutation form, and that disjunction is the point.

        ⚠️ The obvious proposition — *the pre-mutation text is in the tree
        exactly once* — is a trap, and this file is inside the trap. The battery
        rewrites a target and then runs **this seal** to see whether the defect
        is caught, so a naive form of this check fails during every single
        mutation and reports all of them ``KILLED`` by itself. A battery whose
        every mutation is killed by the same test has stopped discriminating,
        and it would look exactly like a healthy one.

        What actually goes stale is the target text disappearing in *both*
        forms, which is what happened to three mutations here between PR #547
        and 2026-08-29.
        """
        for index, mutation in enumerate(self._mutations(), 1):
            with self.subTest(mutation=index, defect=mutation.defect):
                target = PROJECT_ROOT / mutation.path
                self.assertTrue(target.is_file(), f'{mutation.path} does not exist')
                body = target.read_text(encoding='utf-8')
                self.assertTrue(
                    body.count(mutation.old) == 1 or mutation.new in body,
                    f'mutation {index} ({mutation.defect}) matches its target in '
                    f'{mutation.path} in neither its pre- nor its post-mutation '
                    'form, so running the battery reports NOT-APPLIED and the '
                    'defect it revives has nobody checking it',
                )

    def test_a_mutation_that_stopped_matching_is_detected(self):
        """Non-vacuity: the disjunction above can fail, on both disjuncts."""
        battery = self._mutations()
        probe = battery[0]
        body = (PROJECT_ROOT / probe.path).read_text(encoding='utf-8')
        drifted = probe.old + 'text that is not in the repository'
        self.assertFalse(
            body.count(drifted) == 1 or drifted in body,
            'the check would pass for a mutation whose target is gone',
        )


@_requires_tree
class TestTheArtifactModelWalksOnceWithSeedsAndBarriers(unittest.TestCase):
    """M-A — the two orderings that were wrong until 2026-08-29, both directions.

    The old body decided membership *outside* the walk twice, and each decision
    was a defect pointing the opposite way, which is why the answer looked
    plausible: subtracting the excluded names after the walk over-counted by 31
    modules, unioning the force-included packages after the walk under-counted
    by a chain three modules deep, and 7 was what the two produced together.

    ⚠️ Repairing one alone is worse than repairing neither. Repairing only the
    over-count takes the inventory to three, and the four that vanish are not
    modules that may leave — they are modules the frozen program still carries
    with nobody tracking them.
    """

    def setUp(self):
        self.policy = _policy()
        self.seeds, self.forced, self.barriers = _gui_artifact_seeds(
            self.policy, PROJECT_ROOT,
        )
        self.artifact = gui_artifact_modules(self.policy, PROJECT_ROOT)

    def test_a_barrier_is_neither_reported_nor_walked_through(self):
        """Synthetic, both arms, so the semantics are pinned off this tree."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / PYTHON_SOURCE_ROOT.rstrip('/')
            src.mkdir(parents=True)
            (src / 'seed_mod.py').write_text(
                'import wall_mod\n', encoding='utf-8')
            (src / 'wall_mod.py').write_text(
                'import behind_mod\n', encoding='utf-8')
            (src / 'behind_mod.py').write_text('x = 1\n', encoding='utf-8')
            walked = self.policy.reachable_modules(
                Path(tmp), ('seed_mod',), edges=IMPORT_EDGE_STATIC,
            )
            self.assertEqual(
                walked, {'seed_mod', 'wall_mod', 'behind_mod'},
                'the unbarriered walk stopped early, so the barrier arm below '
                'would pass without the barrier doing anything',
            )
            self.assertEqual(
                self.policy.reachable_modules(
                    Path(tmp), ('seed_mod',),
                    edges=IMPORT_EDGE_STATIC, barriers=('wall_mod',),
                ),
                {'seed_mod'},
                'a barrier must remove itself AND everything only it reaches; '
                'cutting after the walk would leave behind_mod, which is the '
                'shape that put 31 phantom modules in this axis',
            )

    def test_the_excluded_subtree_is_not_a_transit_route(self):
        """Over-count arm, on the real tree, derived rather than named.

        Every module the *unbarriered* walk adds must be absent here, and every
        one of them must have no artifact-side importer outside the barrier —
        otherwise it would be a genuine resident this repair just dropped.
        """
        unbarriered = self.policy.reachable_modules(
            PROJECT_ROOT, self.seeds, edges=IMPORT_EDGE_STATIC,
        )
        phantom = {
            module for module in unbarriered - self.artifact
            if not any(_under(module, barrier) for barrier in self.barriers)
        }
        self.assertTrue(
            phantom,
            'nothing enters only through a --nofollow-import-to target, so this '
            'test no longer exercises the defect it was written for',
        )
        index = self.policy.source_module_index(PROJECT_ROOT)
        for module in sorted(phantom):
            with self.subTest(module=module):
                inside = {
                    other for other in self.artifact
                    if module in _imported_modules_of(
                        PROJECT_ROOT / index[other],
                        package=_package_of(index[other]),
                        edges=IMPORT_EDGE_STATIC,
                    )
                }
                self.assertEqual(
                    inside, set(),
                    f'{module} was dropped from the artifact but {sorted(inside)} '
                    'inside the artifact import it — the barrier repair removed '
                    'a real resident',
                )

    def test_a_force_included_module_has_its_own_imports_followed(self):
        """Under-count arm. The edge no model before 2026-08-29 could see.

        ``--include-package`` does not merely add names to a set: Nuitka
        compiles what it names and resolves those modules' imports like any
        other compiled module. Asserted as the non-empty set of modules that
        enter *only* that way, and at least one of them must be a declared
        blocker — that is the finding, not a rounding difference.
        """
        entry_only = self.policy.reachable_modules(
            PROJECT_ROOT,
            tuple(seed for seed in self.seeds if seed not in self.forced),
            edges=IMPORT_EDGE_STATIC, barriers=self.barriers,
        )
        only_via_packages = self.artifact - entry_only - self.forced
        self.assertTrue(
            only_via_packages,
            'no module is reached solely out of a force-included package, so '
            'the union-after-the-walk defect would be invisible again',
        )
        blockers = set(measured_split_blockers(self.policy, PROJECT_ROOT))
        self.assertTrue(
            only_via_packages & blockers,
            'the under-count arm reaches nothing a forbidden lane owns, so the '
            'inventory would be unaffected by it — which is not what was '
            'measured on 2026-08-29 and would mean this repair lost its subject',
        )

    def test_the_artifact_contains_everything_the_gui_reaches_at_module_level(self):
        """Cross-axis coherence with the frozen-build invariant.

        ``TestGuiRuntimeImportClosureNotExcluded`` asks the sibling question —
        *would excluding this break the frozen build* — off the same build file
        and a **narrower** edge relation. The two answers must nest: a module
        the GUI imports at module level and the artifact does not contain is a
        ``ModuleNotFoundError`` at startup.

        ⚠️ Recorded honestly: this held under the pre-repair model too, so it
        did not discriminate between them. It is here so that a future
        *narrowing* of the artifact model cannot silently contradict the axis
        that decides what may be excluded.
        """
        runtime = self.policy.reachable_modules(
            PROJECT_ROOT,
            tuple(seed for seed in self.seeds if seed not in self.forced),
            edges=IMPORT_EDGE_MODULE_LEVEL,
        )
        self.assertGreater(len(runtime), 100, 'the runtime closure is implausibly small')
        self.assertLess(
            len(runtime), len(self.artifact),
            'the runtime closure is not strictly smaller than the artifact, so '
            'the containment below says nothing',
        )
        self.assertEqual(
            sorted(runtime - self.artifact), [],
            'the GUI reaches these at module level and the artifact model says '
            'the frozen program does not contain them',
        )


class TestTheSplitBlockerInventory(unittest.TestCase):
    """M-7 — declaration equals measurement, each site carries a reason.

    This is the wave's actual product: the mechanical answer to *"what is
    web-related"*. It is judged by **set equality** in both directions, because
    a subset check would let a new resident arrive unrecorded and a superset
    check would let a record outlive the thing it describes.
    """

    def setUp(self):
        self.policy = _policy()
        self.declared = _manifest()['governance']['gui_artifact_lane_residents']

    @property
    def measured(self) -> dict[str, str]:
        """Lazy on purpose — the declaration questions must survive the box.

        Measuring in ``setUp`` would make every test in this class error inside
        the delivered ``fcc-test-contracts`` package, including the ones that
        only read the manifest and are perfectly answerable there.
        """
        return measured_split_blockers(self.policy, PROJECT_ROOT)

    @_requires_tree
    def test_the_inventory_is_not_vacuous(self):
        """The guard is on the **model**, not on the count.

        ⚠️ This used to read ``assertGreater(len(self.measured), 10)`` and that
        was a guard against the goal. The whole point of this axis is to drive
        the inventory to zero; a floor of ten fails on the wave that reaches
        nine, so every successful wave would have had to edit its own gate — and
        editing a gate to make your change pass is the shape this repository
        keeps paying to avoid. It fired for real on 2026-08-28 at eleven → seven.

        What "not vacuous" actually means here is *the measurement machinery
        answered*, and that is a property of the artifact model, which does not
        shrink as blockers leave. An empty inventory produced by a working model
        is a **result**; an empty one produced by a broken model is the failure
        this test exists to catch, and only the second is asserted against.
        """
        artifact = gui_artifact_modules(self.policy, PROJECT_ROOT)
        self.assertGreater(
            len(artifact), 100,
            'the artifact model produced almost nothing, so every assertion '
            'below would pass without saying anything',
        )
        for anchor in ('main_entry', 'bootstrap', 'test_orchestrator'):
            with self.subTest(anchor=anchor):
                self.assertIn(
                    anchor, artifact,
                    'the artifact model does not contain a module the GUI '
                    'program demonstrably ships, so its answers about anything '
                    'else are not trustworthy',
                )
        self.assertLess(
            len(self.measured), len(artifact),
            'every module in the artifact is a blocker, which means the lane '
            'predicate stopped discriminating',
        )

    @_requires_tree
    def test_declaration_equals_measurement(self):
        self.assertEqual(
            sorted(self.declared), sorted(self.measured),
            'the declared split-blocker inventory and the measured one differ. '
            'A module the GUI artifact newly carries from a forbidden lane must '
            'be declared with a reason; a record whose module is no longer '
            'resident must be removed in the same edit that made it leave.',
        )

    def test_every_site_carries_a_reason_and_a_door_field(self):
        for module, record in sorted(self.declared.items()):
            with self.subTest(module=module):
                self.assertIn('reason', record)
                self.assertIn('door', record)
                self.assertIn(
                    'residency', record,
                    'a record without a residency says "close the door" for a '
                    'module the build rule ships regardless of imports',
                )
                self.assertIn(record['residency'], _RESIDENCY_TOKENS)
                self.assertGreaterEqual(
                    len(record['reason'].strip()), MINIMUM_CROSSING_REASON_LENGTH,
                    'a reason short enough to be a label is not a reason',
                )

    @_requires_tree
    def test_the_declared_door_is_the_measured_door(self):
        """The claim-bearing half. A ``door`` is checkable, so it is checked.

        Empty means *no provider-side importer*, and that is the strongest
        claim in the file — it says the module leaves for free once its
        siblings do.
        """
        doors = provider_side_doors(self.policy, PROJECT_ROOT, self.measured)
        for module, record in sorted(self.declared.items()):
            with self.subTest(module=module):
                measured_doors = doors.get(module, ())
                declared = record['door']
                if declared:
                    self.assertIn(
                        declared, measured_doors,
                        f'{module} declares door {declared!r} but its measured '
                        f'provider-side importers are {measured_doors}',
                    )
                else:
                    self.assertEqual(
                        measured_doors, (),
                        f'{module} declares no door, but {measured_doors} import '
                        'it from the provider side — the "leaves for free" claim '
                        'is false and the follow-up wave would under-scope',
                    )

    def test_some_sites_have_a_door_and_some_do_not(self):
        """Both halves of the door vocabulary must be exercised.

        If every record had a door the empty case would be untested; if none
        did, the field would carry no information at all.
        """
        doors = {r['door'] for r in self.declared.values()}
        self.assertIn('', doors)
        self.assertGreater(len({d for d in doors if d}), 1)

    @_requires_tree
    def test_the_forbidden_lane_predicate_is_derived_not_listed(self):
        forbidden = {
            lane for lane in self.policy.owners
            if not self.policy.may_depend_on(_ARTIFACT_LANE, lane)
        }
        self.assertTrue(forbidden, 'the provider lane may depend on every lane')
        self.assertNotIn(_ARTIFACT_LANE, forbidden)
        self.assertNotIn(SHARED_KERNEL_LANE, forbidden)
        for lane in sorted(self.measured.values()):
            self.assertIn(lane, forbidden)

    @_requires_tree
    def test_the_declared_residency_is_the_measured_residency(self):
        """The half the ``door`` field structurally cannot carry.

        A door is an *import*, so the sentence a door encodes is *"remove this
        importer and the module leaves"*. That sentence is simply false for a
        module under an ``--include-package`` tree: the build rule ships the
        directory, so every importer can go and the module stays. Two records
        here are in exactly that state, and the 2026-08-29 handoff scoped a
        wave as door-closing against one of them — the door was real, correctly
        measured, and not the thing holding the module in.
        """
        forced = gui_artifact_package_forced(self.policy, PROJECT_ROOT)
        for module, record in sorted(self.declared.items()):
            with self.subTest(module=module):
                self.assertEqual(
                    record['residency'],
                    _RESIDENCY_PACKAGE if module in forced else _RESIDENCY_IMPORT,
                    f'{module} declares residency {record["residency"]!r}. '
                    'Measured, a package-resident module is shipped by '
                    'build_nuitka.py --include-package and an import-resident '
                    'one is not; scoping a repair against the wrong one buys '
                    'nothing.',
                )

    @_requires_tree
    def test_both_residencies_are_exercised(self):
        """Neither token may be dead, or the field carries no information."""
        declared = {record['residency'] for record in self.declared.values()}
        self.assertEqual(declared, set(_RESIDENCY_TOKENS))

    @_requires_tree
    def test_a_package_resident_blocker_is_not_freed_by_closing_its_door(self):
        """The claim above, asserted as the counterfactual it stands for.

        Derived, not asserted about named modules: for every package-resident
        blocker, the artifact is recomputed from seeds that drop *every*
        importer it has, and the module is still there. Non-vacuity is the
        import-resident arm of the same loop, which does leave.
        """
        seeds, forced, barriers = _gui_artifact_seeds(self.policy, PROJECT_ROOT)
        index = self.policy.source_module_index(PROJECT_ROOT)
        measured = self.measured
        self.assertTrue(measured, 'no blockers to reason about')
        seen_package = seen_import = False
        for module in sorted(measured):
            importers = {
                other for other in index
                if module in _imported_modules_of(
                    PROJECT_ROOT / index[other],
                    package=_package_of(index[other]),
                    edges=IMPORT_EDGE_STATIC,
                )
            }
            without = self.policy.reachable_modules(
                PROJECT_ROOT,
                tuple(seed for seed in seeds if seed not in importers),
                edges=IMPORT_EDGE_STATIC,
                barriers=barriers + tuple(sorted(importers)),
            )
            with self.subTest(module=module):
                if module in forced:
                    seen_package = True
                    self.assertIn(
                        module, without,
                        f'{module} is declared package-resident but disappears '
                        'once its importers are cut — then it was import-resident '
                        'all along and its record scopes the wrong repair',
                    )
                else:
                    seen_import = True
                    self.assertNotIn(
                        module, without,
                        f'{module} is declared import-resident but survives with '
                        'every importer cut, so closing its door buys nothing',
                    )
        self.assertTrue(seen_package and seen_import, 'one arm never ran')

    @_requires_tree
    def test_a_synthetic_new_resident_is_detected(self):
        """M-8 — the equality above can fail."""
        with tempfile.TemporaryDirectory() as tmp:
            fake = dict(self.declared)
            fake['application.platform.invented_module'] = {
                'door': '', 'reason': 'x' * MINIMUM_CROSSING_REASON_LENGTH,
            }
            Path(tmp, 'probe.json').write_text(json.dumps(fake), encoding='utf-8')
            self.assertNotEqual(sorted(fake), sorted(self.measured))


class TestTheConsumptionRecordIsReproducible(unittest.TestCase):
    """M-3/S-2 — the manifest records the basis, and the numbers are re-derived.

    ``shared_kernel_consumption`` is written by this axis rather than by hand.
    A number typed into a manifest is a number that goes stale between the
    session that measured it and the session that quotes it — which is the
    whole history this wave is closing.
    """

    def setUp(self):
        self.policy = _policy()
        self.governance = _manifest()['governance']

    def test_the_note_names_the_basis_vocabulary(self):
        note = self.governance['shared_kernel_consumption_note']
        for token in sorted(CONSUMED_BASES):
            self.assertIn(token, note)

    def test_the_record_is_derived_on_every_run(self):
        """The key exists and is empty: the numbers live in the axis, not the file."""
        self.assertIn('shared_kernel_consumption', self.governance)
        self.assertEqual(
            self.governance['shared_kernel_consumption'], {},
            'the manifest carries a hand-written consumption count. That is the '
            'shape that produced 22/27/41 — the count belongs to the derivation, '
            'and the derivation belongs to the axis below.',
        )

    @_requires_tree
    def test_the_both_lane_kernel_set_is_reproducible_and_named(self):
        """The number the domain-adjudication wave needs, with its basis.

        Reported rather than pinned: it moves as the tree moves, and pinning it
        would recreate the stale-literal problem one key over. What is sealed
        is that it can be *derived*, that it is non-trivial, and that it is
        strictly smaller than either lane's own closure — a "both" set equal to
        one side would mean the adjudication has nothing to adjudicate.
        """
        def kernel_for(lane: str) -> set[str]:
            owned = self.policy.consumed_for_lane(
                PROJECT_ROOT, lane, CONSUMED_BASIS_OWNERSHIP,
            )
            return {
                rel for rel in self.policy.shared_kernel_closure_for_lane(
                    PROJECT_ROOT, lane, owned,
                )
                if rel.endswith('.py')
            }

        provider = kernel_for(_ARTIFACT_LANE)
        platform = kernel_for('fcc-test-platform')
        self.assertTrue(provider and platform)
        both = provider & platform
        self.assertTrue(both, 'the two lanes share no kernel module at all')
        self.assertLess(len(both), len(provider))
        self.assertLess(len(both), len(platform))


class TestTheMeasurementTreeIsPresentInTheMonorepo(unittest.TestCase):
    """M-8 — the skip that keeps this file honest in a box must never fire here.

    ⚠️ **A skip is quieter than a failure.** Every measurement above is guarded
    by ``_MEASUREMENT_TREE``, so a typo in either path would turn the whole
    axis into a silent pass — in the monorepo, where it is supposed to bite.
    This asserts the negative directly, and it is deliberately **not** guarded
    itself: in the delivered box it is the one test that is allowed to fail if
    the box ever gains a ``src/``, which would mean the box stopped being what
    the manifest says it is.
    """

    def test_the_monorepo_can_measure(self):
        if not (PROJECT_ROOT / 'tests').is_dir() or not (PROJECT_ROOT / '.git').exists():
            self.skipTest('not the monorepo checkout')
        self.assertTrue(
            _MEASUREMENT_TREE,
            f'the monorepo took the delivered-box branch. src/ present: '
            f'{(PROJECT_ROOT / PYTHON_SOURCE_ROOT.rstrip("/")).is_dir()}, '
            f'build_nuitka.py present: {BUILD_NUITKA_PATH.is_file()}. '
            'Every measurement in this file would be silently skipped.',
        )

    def test_the_guarded_tests_are_a_real_subset(self):
        """A guard that covers everything, or nothing, carries no information."""
        source = Path(__file__).read_text(encoding='utf-8')
        guarded = source.count('@_requires_tree')
        total = source.count('    def test_')
        self.assertGreater(guarded, 5)
        self.assertLess(guarded, total)


if __name__ == '__main__':
    unittest.main()
