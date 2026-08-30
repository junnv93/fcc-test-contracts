"""ADR-0020 — unit seals for the derived lane ownership policy.

The manifest declares ownership; everything else derives from it. These tests
pin the derivation rules against synthetic manifests so a change in the rules
fails here rather than silently reshaping the real gate.

Companion suites: ``tests/test_contracts_platform_extraction_manifest.py``
(the real manifest is a total partition) and
``tests/test_extraction_import_boundaries.py`` (the checker built on top).
"""
import sys
import unittest
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

from fcc_test_contracts.common.extraction_lane_policy import (  # noqa: E402
    EXCLUDED,
    MANIFEST_VERSION,
    SHARED_KERNEL_LANE,
    UNCLASSIFIED,
    ExtractionLanePolicy,
)


def _manifest(**overrides) -> dict:
    base = {
        'manifest_version': MANIFEST_VERSION,
        'governance': {
            'governed_roots': ['src/'],
            'governed_suffixes': ['.py'],
            'out_of_scope_roots': [{'path': 'tests/', 'reason': 'sequenced later'}],
            'unclassified_baseline': 0,
        },
        'exclusions': [{'path': '*/__pycache__/*', 'reason': 'bytecode'}],
        'package_names': {'lane-a': 'pkg_a', 'lane-b': 'pkg_b'},
        'shared_kernel': {
            'depends_on': [],
            'source_roots': [{'path': 'src/domain/', 'notes': 'domain'}],
        },
        'repositories': {
            'lane-a': {
                'owner': 'a',
                'purpose': 'a',
                'depends_on': [],
                'forbidden_external': ['pandas'],
                'source_roots': [{'path': 'src/alpha/', 'notes': 'alpha'}],
                'source_files': [],
                'entries': [],
            },
            'lane-b': {
                'owner': 'b',
                'purpose': 'b',
                'depends_on': ['lane-a', SHARED_KERNEL_LANE],
                'forbidden_external': [],
                'source_roots': [{'path': 'src/beta/', 'notes': 'beta'}],
                'source_files': [],
                'entries': [],
            },
        },
    }
    base.update(overrides)
    return base


class TestManifestVersionGate(unittest.TestCase):
    def test_policy_refuses_a_v1_document(self):
        """v1 has no ownership block; parsing it would silently yield an empty
        partition that classifies everything as unclassified."""
        with self.assertRaises(ValueError):
            ExtractionLanePolicy.from_manifest(_manifest(manifest_version=1))


class TestPathOwnershipResolution(unittest.TestCase):
    def setUp(self):
        self.policy = ExtractionLanePolicy.from_manifest(_manifest())

    def test_directory_prefix_claims_its_subtree(self):
        self.assertEqual(self.policy.lane_for_path('src/alpha/thing.py'), 'lane-a')
        self.assertEqual(self.policy.lane_for_path('src/beta/thing.py'), 'lane-b')

    def test_shared_kernel_is_an_owner(self):
        self.assertEqual(
            self.policy.lane_for_path('src/domain/models/enums.py'), SHARED_KERNEL_LANE
        )

    def test_unowned_path_is_unclassified_not_silently_absorbed(self):
        self.assertEqual(self.policy.lane_for_path('src/orphan.py'), UNCLASSIFIED)

    def test_longest_specificity_wins_over_declaration_order(self):
        manifest = _manifest()
        manifest['repositories']['lane-b']['source_files'] = ['src/alpha/carveout.py']
        policy = ExtractionLanePolicy.from_manifest(manifest)

        self.assertEqual(policy.lane_for_path('src/alpha/carveout.py'), 'lane-b')
        self.assertEqual(policy.lane_for_path('src/alpha/other.py'), 'lane-a')

    def test_exclusions_win_over_ownership_claims(self):
        self.assertEqual(
            self.policy.lane_for_path('src/alpha/__pycache__/thing.py'), EXCLUDED
        )

    def test_equal_specificity_across_owners_is_reported_as_ambiguous(self):
        manifest = _manifest()
        manifest['repositories']['lane-b']['source_roots'] = [
            {'path': 'src/alpha/', 'notes': 'contested'}
        ]
        policy = ExtractionLanePolicy.from_manifest(manifest)

        self.assertTrue(policy.ambiguous_rules())

    def test_unambiguous_manifest_reports_no_clashes(self):
        self.assertEqual(self.policy.ambiguous_rules(), ())


class TestPublishedNamespaceDerivation(unittest.TestCase):
    def test_a_lane_publishes_where_its_files_already_live_when_nothing_moves(self):
        policy = ExtractionLanePolicy.from_manifest(_manifest())

        self.assertIn('alpha', policy.namespaces('lane-a'))

    def test_a_relocated_module_publishes_only_under_its_future_path(self):
        manifest = _manifest()
        manifest['repositories']['lane-a']['entries'] = [{
            'current_path': 'src/alpha/thing.py',
            'future_path': 'pkg_a/thing.py',
            'kind': 'python_module',
            'notes': 'moves',
        }]
        manifest['repositories']['lane-a']['source_roots'] = []
        manifest['repositories']['lane-a']['source_files'] = ['src/alpha/thing.py']
        policy = ExtractionLanePolicy.from_manifest(manifest)

        self.assertIn('pkg_a.thing', policy.namespaces('lane-a'))
        self.assertNotIn('alpha.thing', policy.namespaces('lane-a'))

    def test_a_directory_keeps_publishing_when_one_module_stays(self):
        """Dropping the package namespace because *some* file moved would
        delete every other lane's ban on the rest of that directory."""
        manifest = _manifest()
        manifest['repositories']['lane-a']['entries'] = [{
            'current_path': 'src/alpha/stays.py',
            'future_path': 'src/alpha/stays.py',
            'kind': 'python_module',
            'notes': 'stays put',
        }]
        policy = ExtractionLanePolicy.from_manifest(manifest)

        self.assertIn('alpha', policy.namespaces('lane-a'))

    def test_a_fully_relocated_directory_stops_publishing_its_old_name(self):
        manifest = _manifest()
        manifest['repositories']['lane-a']['entries'] = [{
            'current_path': 'src/alpha/thing.py',
            'future_path': 'pkg_a/thing.py',
            'kind': 'python_module',
            'notes': 'moves',
        }]
        policy = ExtractionLanePolicy.from_manifest(manifest)

        self.assertNotIn('alpha', policy.namespaces('lane-a'))

    def test_globs_claim_paths_but_never_invent_a_namespace(self):
        manifest = _manifest()
        manifest['repositories']['lane-a']['source_roots'] = [
            {'path': 'src/alpha/prefixed_*', 'notes': 'glob'}
        ]
        policy = ExtractionLanePolicy.from_manifest(manifest)

        self.assertEqual(policy.lane_for_path('src/alpha/prefixed_x.py'), 'lane-a')
        self.assertNotIn('alpha.prefixed_', policy.namespaces('lane-a'))

    def test_non_python_roots_claim_no_namespace(self):
        manifest = _manifest()
        manifest['repositories']['lane-a']['source_roots'] = [
            {'path': 'docs/api/', 'notes': 'artifacts'}
        ]
        policy = ExtractionLanePolicy.from_manifest(manifest)

        self.assertNotIn('docs.api', policy.namespaces('lane-a'))


class TestDerivedImportRules(unittest.TestCase):
    def setUp(self):
        self.policy = ExtractionLanePolicy.from_manifest(_manifest())

    def test_allowed_and_forbidden_never_overlap(self):
        """One declaration produces both sides, so the contradiction the old
        hand-maintained pair carried is structurally impossible."""
        for lane in self.policy.owners:
            with self.subTest(lane=lane):
                allowed = set(self.policy.allowed_prefixes(lane))
                forbidden = set(self.policy.forbidden_prefixes(lane))
                self.assertEqual(allowed & forbidden, set())

    def test_a_lane_may_reach_its_declared_dependency(self):
        self.assertIn('alpha', self.policy.allowed_prefixes('lane-b'))
        self.assertIn('domain', self.policy.allowed_prefixes('lane-b'))

    def test_dependency_direction_is_not_symmetric(self):
        self.assertIn('beta', self.policy.forbidden_prefixes('lane-a'))
        self.assertNotIn('beta', self.policy.allowed_prefixes('lane-a'))

    def test_shared_kernel_is_not_granted_implicitly(self):
        """lane-a declares no dependencies, so it does not get the domain layer
        for free — that implicit grant would quietly un-isolate a
        dependency-free contracts lane."""
        self.assertNotIn('domain', self.policy.allowed_prefixes('lane-a'))
        self.assertIn('domain', self.policy.forbidden_prefixes('lane-a'))

    def test_declared_third_party_bans_are_carried_through(self):
        self.assertIn('pandas', self.policy.forbidden_prefixes('lane-a'))

    def test_a_lane_declaring_nothing_yields_a_vacuous_gate(self):
        """The failure mode this policy exists to make visible.

        ``fcc-unlicensed-headless`` shipped with an empty forbidden *and* empty
        allowed tuple, so its gate could not report a single import violation.
        The rules must be capable of reproducing that state — otherwise the
        real-manifest non-vacuity invariant in
        ``test_contracts_platform_extraction_manifest`` would be untestable —
        while the real manifest is asserted never to be in it.
        """
        manifest = _manifest()
        manifest['repositories']['lane-c'] = {
            'owner': 'c', 'purpose': 'c',
            'depends_on': ['lane-a', 'lane-b', SHARED_KERNEL_LANE],
            'forbidden_external': [],
            'source_roots': [], 'source_files': [], 'entries': [],
        }
        manifest['package_names']['lane-c'] = ''
        policy = ExtractionLanePolicy.from_manifest(manifest)

        self.assertEqual(policy.forbidden_prefixes('lane-c'), ())
        self.assertEqual(policy.namespaces('lane-c'), ())

    def test_module_attribution_uses_current_names(self):
        self.assertEqual(self.policy.lane_for_module('alpha.thing'), 'lane-a')
        self.assertEqual(self.policy.lane_for_module('domain.models.x'), SHARED_KERNEL_LANE)
        self.assertEqual(self.policy.lane_for_module('pandas'), UNCLASSIFIED)

    def test_may_depend_on_reflects_the_declaration(self):
        self.assertTrue(self.policy.may_depend_on('lane-b', 'lane-a'))
        self.assertFalse(self.policy.may_depend_on('lane-a', 'lane-b'))


class TestScriptsNamespaceVisibility(unittest.TestCase):
    """``scripts-namespace-blind-axis`` (2026-08-12) — ``scripts/`` ships its
    own ``__init__.py`` in this monorepo (80 in-repo import sites already
    spell it ``scripts.foo``), so deriving a namespace for it is *observed*
    from a tree :meth:`ExtractionLanePolicy.bound_to` actually walks, not
    invented from a rule *pattern* the way :func:`_namespace_from_path`
    refuses to invent ``docs.api``. Every scenario here needs a real
    ``scripts/__init__.py`` on disk — that existence check is the whole
    anti-fabrication mechanism, so a synthetic manifest alone (no tree)
    cannot exercise it.
    """

    def _tree(self, tmpdir, *, scripts_files=()):
        """A minimal on-disk tree with a real ``scripts/__init__.py``."""
        root = Path(tmpdir)
        (root / 'scripts').mkdir(parents=True, exist_ok=True)
        (root / 'scripts' / '__init__.py').write_text('', encoding='utf-8')
        for rel in scripts_files:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('', encoding='utf-8')
        return root

    def _manifest_with_scripts(self, **overrides):
        manifest = _manifest(**overrides)
        manifest['governance']['governed_roots'] = ['src/', 'scripts/']
        return manifest

    def test_entry_point_roots_finds_only_scripts(self):
        import tempfile

        policy = ExtractionLanePolicy.from_manifest(self._manifest_with_scripts())
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self._tree(tmpdir)
            self.assertEqual(policy.entry_point_roots(root), ('scripts/',))

    def test_a_governed_root_without_a_top_level_init_does_not_qualify(self):
        """The structural half of the ``docs/``/``apps/web/`` closure — a
        ``.py`` file alone is not evidence of a package, only a top-level
        ``__init__.py`` is."""
        import tempfile

        manifest = self._manifest_with_scripts()
        manifest['governance']['governed_roots'] = ['src/', 'scripts/', 'apps/web/']
        policy = ExtractionLanePolicy.from_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self._tree(tmpdir)
            web = root / 'apps' / 'web'
            web.mkdir(parents=True, exist_ok=True)
            (web / 'run-worker.py').write_text('', encoding='utf-8')

            self.assertEqual(policy.entry_point_roots(root), ('scripts/',))

    def test_entry_point_roots_excludes_the_python_source_root_and_test_root(self):
        import tempfile

        manifest = self._manifest_with_scripts()
        manifest['governance']['governed_roots'] = ['src/', 'scripts/', 'tests/']
        manifest['governance']['test_lane_attribution'] = {'root': 'tests/'}
        policy = ExtractionLanePolicy.from_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self._tree(tmpdir)
            for governed in ('src', 'tests'):
                (root / governed).mkdir(parents=True, exist_ok=True)
                (root / governed / '__init__.py').write_text('', encoding='utf-8')

            self.assertEqual(policy.entry_point_roots(root), ('scripts/',))

    def test_candidate_governed_roots_are_not_empty(self):
        """Non-vacuity for the negative control below: if the candidate set
        were empty, '``docs/``/``apps/web/`` excluded' and 'nothing was ever
        looked at' would be the same green."""
        policy = ExtractionLanePolicy.from_manifest(self._manifest_with_scripts())
        excluded = {'src/', policy.test_root}
        candidates = [r for r in policy.governed_roots if r not in excluded]
        self.assertGreater(len(candidates), 0)

    def test_a_scripts_owned_file_resolves_by_module_name_once_bound(self):
        import tempfile

        manifest = self._manifest_with_scripts()
        manifest['repositories']['lane-a']['source_files'] = ['scripts/thing.py']
        policy = ExtractionLanePolicy.from_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmpdir:
            bound = policy.bound_to(self._tree(tmpdir, scripts_files=['scripts/thing.py']))

            self.assertIn('scripts.thing', bound.namespaces('lane-a'))
            self.assertEqual(bound.lane_for_module('scripts.thing'), 'lane-a')
            # ``lane_for_path`` agrees — the fallback is a reuse, not a second
            # definition (the wave's own problem-statement seal).
            self.assertEqual(
                bound.lane_for_module('scripts.thing'),
                bound.lane_for_path('scripts/thing.py'),
            )

    def test_an_unbound_policy_is_byte_identical_to_before_this_axis(self):
        manifest = self._manifest_with_scripts()
        manifest['repositories']['lane-a']['source_files'] = ['scripts/thing.py']
        policy = ExtractionLanePolicy.from_manifest(manifest)

        self.assertEqual(policy.lane_for_module('scripts.thing'), UNCLASSIFIED)
        self.assertNotIn('scripts.thing', policy.namespaces('lane-a'))

    def test_a_nonexistent_scripts_module_is_never_minted(self):
        """P0 regression: a rule *pattern* must not conjure a module that is
        not actually on disk. The totality-backstop directory rule
        (``scripts/`` in the real manifest) is exactly the shape that used to
        make this true of every dotted ``scripts.*`` name, whether or not the
        file existed."""
        import tempfile

        manifest = self._manifest_with_scripts()
        manifest['repositories']['lane-b']['source_roots'] = [
            *manifest['repositories']['lane-b']['source_roots'],
            {'path': 'scripts/', 'notes': 'totality backstop'},
        ]
        policy = ExtractionLanePolicy.from_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmpdir:
            bound = policy.bound_to(self._tree(tmpdir))  # scripts/__init__.py only

            self.assertEqual(
                bound.lane_for_module('scripts.this_module_does_not_exist'), UNCLASSIFIED
            )
            self.assertEqual(bound.lane_for_module('pandas'), UNCLASSIFIED)

    def test_docs_and_apps_web_still_claim_no_namespace(self):
        """Negative control — the wave that opened scripts/ must not also
        open the two roots its own plan named as still-fabricated, even once
        a tree is bound and each ships a plain ``.py`` file."""
        import tempfile

        manifest = self._manifest_with_scripts()
        manifest['governance']['governed_roots'] = ['src/', 'scripts/', 'docs/api/', 'apps/web/']
        manifest['repositories']['lane-a']['source_roots'] = [
            *manifest['repositories']['lane-a']['source_roots'],
            {'path': 'docs/api/', 'notes': 'artifacts'},
            {'path': 'apps/web/', 'notes': 'frontend'},
        ]
        policy = ExtractionLanePolicy.from_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self._tree(tmpdir)
            (root / 'docs' / 'api').mkdir(parents=True, exist_ok=True)
            (root / 'docs' / 'api' / 'thing.json').write_text('{}', encoding='utf-8')
            (root / 'apps' / 'web').mkdir(parents=True, exist_ok=True)
            (root / 'apps' / 'web' / 'run-worker.py').write_text('', encoding='utf-8')
            bound = policy.bound_to(root)

            self.assertEqual(bound.entry_point_roots(root), ('scripts/',))
            self.assertNotIn('docs.api', bound.namespaces('lane-a'))
            self.assertNotIn('apps.web', bound.namespaces('lane-a'))
            self.assertEqual(bound.lane_for_module('docs.api'), UNCLASSIFIED)
            self.assertEqual(bound.lane_for_module('apps.web'), UNCLASSIFIED)

    def test_a_glob_owned_scripts_file_resolves_by_module_name_via_lane_for_path(self):
        """A glob rule (``scripts/platform_*`` in the real manifest) already
        claims *path* ownership via ``lane_for_path``. The fallback reuses
        that answer through the entry-point index rather than re-deriving
        glob-matching in module-name space — the second-definition this
        module's SSOT contract forbids.
        """
        import tempfile

        manifest = self._manifest_with_scripts()
        manifest['repositories']['lane-a']['source_roots'] = [
            {'path': 'scripts/alpha_*', 'notes': 'glob'}
        ]
        manifest['repositories']['lane-b']['source_roots'] = [
            *manifest['repositories']['lane-b']['source_roots'],
            {'path': 'scripts/', 'notes': 'totality backstop'},
        ]
        policy = ExtractionLanePolicy.from_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmpdir:
            bound = policy.bound_to(
                self._tree(tmpdir, scripts_files=['scripts/alpha_thing.py'])
            )

            self.assertEqual(bound.lane_for_path('scripts/alpha_thing.py'), 'lane-a')
            self.assertEqual(bound.lane_for_module('scripts.alpha_thing'), 'lane-a')

    def test_double_identity_resolves_to_one_lane_not_two(self):
        """A namespace package (no ``__init__.py`` — PEP 420) is reachable
        both as ``scripts.dev_seed.central`` and bare ``dev_seed.central``.
        Both must resolve to the same lane: two names, one file, one owner.
        """
        import tempfile

        manifest = self._manifest_with_scripts()
        manifest['repositories']['lane-a']['source_roots'] = [
            *manifest['repositories']['lane-a']['source_roots'],
            {'path': 'scripts/dev_seed/', 'notes': 'nested, no __init__.py'},
        ]
        policy = ExtractionLanePolicy.from_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmpdir:
            bound = policy.bound_to(
                self._tree(tmpdir, scripts_files=['scripts/dev_seed/central.py'])
            )

            self.assertEqual(bound.lane_for_module('scripts.dev_seed.central'), 'lane-a')
            self.assertEqual(bound.lane_for_module('dev_seed.central'), 'lane-a')
            self.assertEqual(bound.lane_for_module('dev_seed'), 'lane-a')

    def test_cross_lane_imports_binds_itself(self):
        """One of the three ``root``-taking methods that must not depend on
        a caller remembering to bind (M1-c) — a forgotten bind would
        silently under-report a real crossing through ``scripts/``."""
        import tempfile

        manifest = self._manifest_with_scripts()
        manifest['repositories']['lane-b']['source_roots'] = [
            *manifest['repositories']['lane-b']['source_roots'],
            {'path': 'scripts/', 'notes': 'totality backstop'},
        ]
        policy = ExtractionLanePolicy.from_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self._tree(tmpdir)
            caller = root / 'src' / 'alpha' / 'user.py'
            caller.parent.mkdir(parents=True, exist_ok=True)
            caller.write_text('import scripts.thing\n', encoding='utf-8')
            (root / 'scripts' / 'thing.py').write_text('', encoding='utf-8')

            crossings = policy.cross_lane_imports(root)

        self.assertIn('lane-a -> lane-b @ src', crossings)

    def test_ambiguous_module_names_catches_a_real_tie(self):
        """Non-vacuity: the seal must be able to fire, not just stay silent.

        A bare entry-point name (``dup``) that a totality-backstop rule
        gives to lane-b collides with lane-a's ``src/``-derived namespace of
        the same word — the exact shape where ``import dup`` could silently
        mean either thing.
        """
        import tempfile

        manifest = self._manifest_with_scripts()
        manifest['repositories']['lane-a']['source_roots'] = [
            *manifest['repositories']['lane-a']['source_roots'],
            {'path': 'src/dup/', 'notes': 'src-side of the collision'},
        ]
        manifest['repositories']['lane-b']['source_roots'] = [
            *manifest['repositories']['lane-b']['source_roots'],
            {'path': 'scripts/', 'notes': 'totality backstop owns the entry-point file'},
        ]
        policy = ExtractionLanePolicy.from_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self._tree(tmpdir, scripts_files=['scripts/dup.py'])
            (root / 'src' / 'dup').mkdir(parents=True, exist_ok=True)
            (root / 'src' / 'dup' / '__init__.py').write_text('', encoding='utf-8')

            ambiguous = policy.ambiguous_module_names(root)

        self.assertIn('dup', ambiguous)

    def test_ambiguous_module_names_reports_a_stdlib_collision(self):
        import tempfile

        policy = ExtractionLanePolicy.from_manifest(self._manifest_with_scripts())
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self._tree(tmpdir, scripts_files=['scripts/json.py'])

            ambiguous = policy.ambiguous_module_names(root)

        self.assertIn('json', ambiguous)

    def test_ambiguous_module_names_is_empty_on_a_clean_tree(self):
        import tempfile

        policy = ExtractionLanePolicy.from_manifest(self._manifest_with_scripts())
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self._tree(tmpdir, scripts_files=['scripts/thing.py'])

            self.assertEqual(policy.ambiguous_module_names(root), ())


class TestTreeClassification(unittest.TestCase):
    def test_walk_prunes_out_of_scope_and_excluded_trees(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for rel in (
                'src/alpha/kept.py',
                'src/alpha/__pycache__/dropped.py',
                'tests/dropped.py',
            ):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('', encoding='utf-8')

            policy = ExtractionLanePolicy.from_manifest(_manifest())
            report = policy.classify_tree(root)

        self.assertEqual(report.counts['lane-a'], 1)
        self.assertEqual(report.unclassified_count, 0)
        self.assertEqual(report.counts[EXCLUDED], 0)

    def test_an_unowned_file_surfaces_as_unclassified(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / 'src' / 'orphan.py'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('', encoding='utf-8')

            report = ExtractionLanePolicy.from_manifest(_manifest()).classify_tree(root)

        self.assertEqual(report.unclassified, ('src/orphan.py',))


def _kernel_tree(root: Path, *, kernel: str = 'domain') -> None:
    """A shared kernel with one reached branch, one unreached module, and a hop.

    ``consumer`` reaches ``mid`` which reaches ``leaf``: a one-hop closure would
    deliver a tree that cannot import the module it just delivered.
    """
    files = {
        f'src/{kernel}/__init__.py': '',
        f'src/{kernel}/models/__init__.py': '',
        f'src/{kernel}/models/leaf.py': '',
        f'src/{kernel}/services/__init__.py': '',
        f'src/{kernel}/services/mid.py': f'from {kernel}.models.leaf import Thing\n',
        f'src/{kernel}/services/unreached.py': 'FORBIDDEN = 1\n',
        'src/beta/consumer.py': f'from {kernel}.services.mid import helper\n',
        'src/alpha/other.py': f'from {kernel}.services.mid import helper\n',
    }
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')


class TestSharedKernelDeliveryClosure(unittest.TestCase):
    """Ownership stays whole; the box takes only what the lane reaches.

    The same distinction ``tests_for_lane`` draws on the test axis. Shipping the
    layer whole would hand a joining team every measurement judgement in it,
    which is what ADR-0018 D-5 keeps closed.
    """

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_the_closure_follows_imports_transitively_and_carries_the_packages(self):
        _kernel_tree(self.root)
        policy = ExtractionLanePolicy.from_manifest(_manifest())

        closure = policy.shared_kernel_closure_for_lane(
            self.root, 'lane-b', ('src/beta/consumer.py',),
        )

        self.assertEqual(closure, (
            'src/domain/__init__.py',
            'src/domain/models/__init__.py',
            'src/domain/models/leaf.py',
            'src/domain/services/__init__.py',
            'src/domain/services/mid.py',
        ))

    def test_a_module_nobody_reaches_stays_behind(self):
        """The whole point: what is owned is not what is delivered."""
        _kernel_tree(self.root)
        policy = ExtractionLanePolicy.from_manifest(_manifest())

        closure = policy.shared_kernel_closure_for_lane(
            self.root, 'lane-b', ('src/beta/consumer.py',),
        )

        self.assertNotIn('src/domain/services/unreached.py', closure)

    def test_a_lane_that_did_not_declare_the_dependency_gets_nothing(self):
        """``depends_on`` stays the only door into the kernel.

        ``lane-a`` imports the very same module, so this is not vacuous — the
        seed is non-empty and the answer is still empty.
        """
        _kernel_tree(self.root)
        policy = ExtractionLanePolicy.from_manifest(_manifest())

        self.assertFalse(policy.may_depend_on('lane-a', SHARED_KERNEL_LANE))
        self.assertEqual(
            policy.shared_kernel_closure_for_lane(self.root, 'lane-a', ('src/alpha/other.py',)),
            (),
        )
        # Non-vacuity: the identical seed under a declaring lane does deliver.
        self.assertTrue(
            policy.shared_kernel_closure_for_lane(self.root, 'lane-b', ('src/alpha/other.py',)),
        )

    def test_the_namespace_comes_from_the_manifest_not_from_the_word_domain(self):
        """Move the shared kernel's root and the closure follows, code untouched.

        A literal ``'domain'`` would make this the one rule the manifest could
        not restate — and the manifest is where ownership is declared.
        """
        _kernel_tree(self.root, kernel='kernel')
        manifest = _manifest()
        manifest['shared_kernel']['source_roots'] = [
            {'path': 'src/kernel/', 'notes': 'relocated shared kernel'},
        ]
        policy = ExtractionLanePolicy.from_manifest(manifest)

        closure = policy.shared_kernel_closure_for_lane(
            self.root, 'lane-b', ('src/beta/consumer.py',),
        )

        self.assertIn('src/kernel/services/mid.py', closure)
        self.assertTrue(all(rel.startswith('src/kernel/') for rel in closure))

    def test_a_package_init_pulls_in_what_it_imports(self):
        """Measured defect, 2026-08-12 — the ``__init__`` chain is not an epilogue.

        Adding it after the fixpoint left ``domain/models/__init__.py`` in the
        box with its own module-level imports never followed, so
        ``domain.models.test_plan`` was missing and **seven** delivered test
        files could not be collected. Every gate was green while that was true;
        running the delivered suite is what said otherwise.
        """
        _kernel_tree(self.root)
        (self.root / 'src/domain/models/__init__.py').write_text(
            'from domain.models.reexported import Thing\n', encoding='utf-8',
        )
        (self.root / 'src/domain/models/reexported.py').write_text('', encoding='utf-8')
        policy = ExtractionLanePolicy.from_manifest(_manifest())

        closure = policy.shared_kernel_closure_for_lane(
            self.root, 'lane-b', ('src/beta/consumer.py',),
        )

        self.assertIn('src/domain/models/reexported.py', closure)

    def test_a_relative_import_is_followed(self):
        """A relative import carries no dotted name, so a level-0-only reader
        sees a file that imports nothing. ``src/domain/`` really uses this form
        (``from .enums import BandType``), so the closure would have shipped
        modules whose siblings were missing."""
        _kernel_tree(self.root)
        (self.root / 'src/domain/services/mid.py').write_text(
            'from .sibling import helper\nfrom . import cousin\n', encoding='utf-8',
        )
        for name in ('sibling.py', 'cousin.py'):
            (self.root / 'src/domain/services' / name).write_text('', encoding='utf-8')
        policy = ExtractionLanePolicy.from_manifest(_manifest())

        closure = policy.shared_kernel_closure_for_lane(
            self.root, 'lane-b', ('src/beta/consumer.py',),
        )

        self.assertIn('src/domain/services/sibling.py', closure)
        self.assertIn('src/domain/services/cousin.py', closure)

    def test_a_submodule_named_in_the_alias_list_is_followed(self):
        """``from domain.models import leaf`` puts the module in the alias list.

        Reading only the ``module`` field delivers the package and leaves the
        module inside it behind."""
        _kernel_tree(self.root)
        (self.root / 'src/beta/consumer.py').write_text(
            'from domain.models import leaf\n', encoding='utf-8',
        )
        policy = ExtractionLanePolicy.from_manifest(_manifest())

        closure = policy.shared_kernel_closure_for_lane(
            self.root, 'lane-b', ('src/beta/consumer.py',),
        )

        self.assertIn('src/domain/models/leaf.py', closure)

    def test_package_data_beside_a_delivered_module_travels_with_it(self):
        """Measured defect, 2026-08-12 — a module is not always all it needs.

        ``domain/models/reference_catalog.py`` reads ``decision_catalogue.json``
        from its own package **at import time**. Thirteen delivered platform
        test files could not be collected because of it, and that was *after*
        every ``domain.*`` name had stopped being unresolved — the dependency
        axis reads imports, and a data file is not one.
        """
        _kernel_tree(self.root)
        (self.root / 'src/domain/models/catalogue.json').write_text('{}', encoding='utf-8')
        (self.root / 'src/domain/services/unreached.json').write_text('{}', encoding='utf-8')
        manifest = _manifest()
        manifest['governance']['governed_suffixes'] = ['.py', '.json']
        policy = ExtractionLanePolicy.from_manifest(manifest)

        closure = policy.shared_kernel_closure_for_lane(
            self.root, 'lane-b', ('src/beta/consumer.py',),
        )

        self.assertIn('src/domain/models/catalogue.json', closure)
        # Scoped to directories the closure already delivers from — ``services``
        # is one of them here, so the sibling data file rides along with the
        # module that shares its package rather than being reached for.
        self.assertIn('src/domain/services/unreached.json', closure)

    def test_package_data_does_not_reach_into_undelivered_directories(self):
        """The scope is where modules landed, not the whole layer."""
        _kernel_tree(self.root)
        aside = self.root / 'src/domain/aside'
        aside.mkdir(parents=True)
        (aside / 'left_behind.json').write_text('{}', encoding='utf-8')
        manifest = _manifest()
        manifest['governance']['governed_suffixes'] = ['.py', '.json']
        policy = ExtractionLanePolicy.from_manifest(manifest)

        closure = policy.shared_kernel_closure_for_lane(
            self.root, 'lane-b', ('src/beta/consumer.py',),
        )

        self.assertNotIn('src/domain/aside/left_behind.json', closure)

    def test_a_lane_owned_file_never_travels_under_the_kernel_claim(self):
        """Only files the manifest gives to the shared kernel may move here."""
        _kernel_tree(self.root)
        policy = ExtractionLanePolicy.from_manifest(_manifest())

        closure = policy.shared_kernel_closure_for_lane(
            self.root, 'lane-b', ('src/beta/consumer.py',),
        )

        self.assertTrue(all(
            policy.lane_for_path(rel) == SHARED_KERNEL_LANE for rel in closure
        ))


if __name__ == '__main__':
    unittest.main()
