"""The headless contract surface stays cut along the axis its history wanted.

The previous split put one module per KIND of table — every route together,
every schema together, every DTO together. Measured against this surface's own
history that shape kept **38%** of feature commits inside a single file, with a
median commit touching three; the surface axis keeps **86%** with a median of
one, and ten of the thirteen multi-file commits under the old shape touched a
single route family. The measurement, its calibration and the finer partition
it rejected are in ``.claude/evaluations/headless-contract-axis.md``, and
``scripts/measure_contract_decomposition_axis.py`` re-runs it.

What is sealed here is not that arrangement of files. It is that **membership is
derived** — a surface owns the operations its declared prefixes name, and the
schemas only its operations reach — so the split cannot rot into a hand-kept
list that says one thing while the modules say another.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import re
import sys
import types
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))

from tests._ast_string_finder import find_string_literals_anywhere  # noqa: E402

from fcc_test_contracts.headless import api_contract_surfaces as registry  # noqa: E402
from fcc_test_contracts.headless.api_contract_shared_schemas import (  # noqa: E402
    SHARED_SCHEMAS,
)
from fcc_test_contracts.headless.api_contracts import (  # noqa: E402
    HEADLESS_API_OPERATIONS,
    HEADLESS_API_PERMISSIONS,
    HEADLESS_API_ROUTES,
    HEADLESS_API_SCHEMAS,
)

import sys as _mms_sys
from pathlib import Path as _MmsPath
_mms_sys.path.insert(0, str(_MmsPath(__file__).resolve().parent))
# ⚠️ 이 패키지는 2026-08-31 에 이사했다 — 경로가 아니라 임포트 이름으로 묻는다.
from _moved_module_source import moved_module_source  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FACADE = moved_module_source('fcc_test_contracts.headless.api_contracts')
PACKAGE_DIR = FACADE.parent

#: ``#/schemas/Name`` in the declarations, normalised to
#: ``#/components/schemas/Name`` only when the OpenAPI document is built. Both
#: spellings are accepted so this test does not depend on which side of that
#: normalisation a declaration was written on.
_REF = re.compile(r'#/(?:components/)?schemas/(\w+)$')


def surface_modules() -> tuple[types.ModuleType, ...]:
    return registry.SURFACE_MODULES


def owning_surface(path: str) -> str | None:
    """Longest declared prefix wins — the rule a router would apply."""
    best, best_len = None, -1
    for module in surface_modules():
        for prefix in module.SURFACE_PREFIXES:
            if (path == prefix or path.startswith(prefix + '/')) and len(prefix) > best_len:
                best, best_len = module.__name__, len(prefix)
    return best


def schema_refs(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get('$ref')
        if isinstance(ref, str):
            match = _REF.match(ref)
            if match:
                found.add(match.group(1))
        for value in node.values():
            found |= schema_refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= schema_refs(value)
    return found


def schemas_reachable_from(operation_ids) -> set[str]:
    stack = [
        name
        for op in operation_ids
        for key in ('request', 'response')
        if (name := HEADLESS_API_OPERATIONS[op].get(key))
    ]
    seen: set[str] = set()
    while stack:
        name = stack.pop()
        if name in seen or name not in HEADLESS_API_SCHEMAS:
            continue
        seen.add(name)
        stack += list(schema_refs(HEADLESS_API_SCHEMAS[name]))
    return seen


class TestTheSurfacePartitionIsTotalAndDisjoint(unittest.TestCase):
    """Every route resolves to exactly one surface. A tie is a broken split."""

    def test_every_route_path_resolves_to_exactly_one_surface(self):
        unowned = {
            op: path for op, (_m, path) in HEADLESS_API_ROUTES.items()
            if owning_surface(path) is None
        }
        self.assertEqual({}, unowned, 'routes no surface prefix claims')

    def test_no_two_surfaces_declare_the_same_prefix(self):
        seen: dict[str, str] = {}
        for module in surface_modules():
            for prefix in module.SURFACE_PREFIXES:
                self.assertNotIn(
                    prefix, seen,
                    f'{prefix!r} declared by {seen.get(prefix)} and {module.__name__}',
                )
                seen[prefix] = module.__name__

    def test_every_declared_prefix_owns_at_least_one_operation(self):
        for module in surface_modules():
            for prefix in module.SURFACE_PREFIXES:
                owned = [
                    op for op, (_m, path) in HEADLESS_API_ROUTES.items()
                    if path == prefix or path.startswith(prefix + '/')
                ]
                self.assertTrue(
                    owned,
                    f'{module.__name__} declares {prefix!r} and no operation uses it '
                    '— a dead prefix silently widens the surface it belongs to',
                )

    def test_the_measurement_machinery_answered(self):
        """A lower bound, so an empty parse cannot pass every test above."""
        self.assertGreaterEqual(len(HEADLESS_API_ROUTES), 30)
        self.assertGreaterEqual(len(surface_modules()), 2)

    def test_the_rule_fires_on_a_synthetic_overlapping_prefix(self):
        """Non-vacuity: two surfaces claiming one prefix must be detectable."""
        intruder = types.SimpleNamespace(
            __name__='surface_synthetic',
            SURFACE_PREFIXES=surface_modules()[0].SURFACE_PREFIXES[:1],
        )
        seen: dict[str, str] = {}
        clash = None
        for module in (*surface_modules(), intruder):
            for prefix in module.SURFACE_PREFIXES:
                if prefix in seen:
                    clash = prefix
                seen[prefix] = module.__name__
        self.assertIsNotNone(clash, 'the duplicate-prefix check cannot see a duplicate')


class TestEveryOperationIsDeclaredInItsOwnSurfaceModule(unittest.TestCase):
    """Membership is derived. A misplaced operation is red, not a style note."""

    def test_operation_lives_in_the_module_its_path_names(self):
        misplaced = []
        for module in surface_modules():
            for op in getattr(module, 'ROUTES', {}):
                expected = owning_surface(HEADLESS_API_ROUTES[op][1])
                if expected != module.__name__:
                    misplaced.append((op, module.__name__, expected))
        self.assertEqual([], misplaced)

    def test_each_surfaces_tables_agree_with_its_route_table(self):
        for module in surface_modules():
            routes = set(getattr(module, 'ROUTES', {}))
            for attribute in ('PERMISSIONS', 'OPERATIONS'):
                table = getattr(module, attribute, None)
                if table is None:
                    continue
                self.assertEqual(
                    routes, set(table),
                    f'{module.__name__}.{attribute} keys differ from its ROUTES',
                )

    def test_the_merged_tables_are_exactly_the_union_of_the_surfaces(self):
        for attribute, merged in (
            ('ROUTES', HEADLESS_API_ROUTES),
            ('PERMISSIONS', HEADLESS_API_PERMISSIONS),
            ('OPERATIONS', HEADLESS_API_OPERATIONS),
        ):
            union: dict = {}
            for module in surface_modules():
                union.update(getattr(module, attribute, {}) or {})
            self.assertEqual(union, merged, f'{attribute} merge lost or added entries')

    def test_schemas_merge_to_the_surfaces_plus_the_shared_table(self):
        union = dict(SHARED_SCHEMAS)
        for module in surface_modules():
            union.update(getattr(module, 'SCHEMAS', {}) or {})
        self.assertEqual(union, HEADLESS_API_SCHEMAS)


class TestSchemaOwnershipIsDerivedFromReachability(unittest.TestCase):
    """``$ref`` closure decides where a schema lives — not a hand-kept list."""

    def test_a_surface_only_declares_schemas_only_it_reaches(self):
        for module in surface_modules():
            mine = schemas_reachable_from(getattr(module, 'ROUTES', {}))
            others: set[str] = set()
            for other in surface_modules():
                if other is not module:
                    others |= schemas_reachable_from(getattr(other, 'ROUTES', {}))
            wrongly_owned = set(getattr(module, 'SCHEMAS', {})) & others
            self.assertEqual(
                set(), wrongly_owned,
                f'{module.__name__} declares schemas another surface also reaches '
                '— those belong in api_contract_shared_schemas',
            )
            self.assertEqual(
                set(), set(getattr(module, 'SCHEMAS', {})) - mine,
                f'{module.__name__} declares schemas its own operations never reach',
            )

    def test_every_shared_schema_is_reached_by_more_than_one_surface(self):
        for name in SHARED_SCHEMAS:
            reaching = [
                module.__name__ for module in surface_modules()
                if name in schemas_reachable_from(getattr(module, 'ROUTES', {}))
            ]
            self.assertGreater(
                len(reaching), 1,
                f'{name} is shared but only {reaching} reaches it — it belongs to '
                'that surface, and leaving it here hides which surface owns it',
            )

    def test_every_schema_is_reachable_from_some_operation(self):
        """Dead contract fragments accumulate silently; the rule stops them."""
        reachable = schemas_reachable_from(HEADLESS_API_ROUTES)
        self.assertEqual(
            set(), set(HEADLESS_API_SCHEMAS) - reachable,
            'schemas no operation reaches — declared, serialized, never sent',
        )


class TestMergeRefusesToLoseAContractSilently(unittest.TestCase):
    """A duplicate key raises and names BOTH owners."""

    @staticmethod
    def _surface(name, table):
        module = types.ModuleType(name)
        module.ROUTES = table
        return module

    def test_two_surfaces_declaring_the_same_key_raise(self):
        a = self._surface('surface_a', {'shared_op': ('GET', '/a')})
        b = self._surface('surface_b', {'shared_op': ('GET', '/b')})
        with self.assertRaises(registry.DuplicateContractKeyError) as caught:
            registry.merge_surface_table('ROUTES', (a, b))
        message = str(caught.exception)
        self.assertIn('surface_a', message)
        self.assertIn('surface_b', message)
        self.assertIn('shared_op', message)

    def test_disjoint_surfaces_merge(self):
        a = self._surface('surface_a', {'op_a': ('GET', '/a')})
        b = self._surface('surface_b', {'op_b': ('GET', '/b')})
        self.assertEqual(
            {'op_a': ('GET', '/a'), 'op_b': ('GET', '/b')},
            registry.merge_surface_table('ROUTES', (a, b)),
        )

    def test_a_surface_without_the_table_is_skipped_not_crashed(self):
        a = self._surface('surface_a', {'op_a': ('GET', '/a')})
        empty = types.ModuleType('surface_empty')
        self.assertEqual(
            {'op_a': ('GET', '/a')},
            registry.merge_surface_table('ROUTES', (a, empty)),
        )

    def test_the_shared_table_collides_like_any_other_source(self):
        a = self._surface('surface_a', {'dup': ('GET', '/a')})
        with self.assertRaises(registry.DuplicateContractKeyError):
            registry.merge_surface_table('ROUTES', (a,), extra={'dup': ('GET', '/x')})


class TestTheRegistryCoversThePackage(unittest.TestCase):
    """A surface module nobody registered contributes nothing, quietly."""

    def test_every_surface_module_on_disk_is_registered(self):
        on_disk = {p.stem for p in PACKAGE_DIR.glob('surface_*.py')}
        registered = {m.__name__.rsplit('.', 1)[-1] for m in surface_modules()}
        self.assertEqual(
            on_disk, registered,
            'a surface_*.py that the registry does not list declares contracts '
            'nothing merges — its operations vanish from the merged tables',
        )


class TestTheFacadeOnlyAssembles(unittest.TestCase):
    """Once the facade declares contract entries the decomposition unwinds."""

    def _facade_tree(self):
        return ast.parse(FACADE.read_text(encoding='utf-8'))

    def test_the_facade_declares_no_contract_entries_of_its_own(self):
        declared = []
        for node in self._facade_tree().body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                declared.append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id != '__all__':
                        declared.append(target.id)
        self.assertEqual([], declared, 'the facade declares instead of assembling')

    def test_every_name_in_dunder_all_resolves(self):
        from fcc_test_contracts.headless import api_contracts
        unresolved = [n for n in api_contracts.__all__ if not hasattr(api_contracts, n)]
        self.assertEqual([], unresolved)

    def test_every_name_the_repository_imports_from_the_facade_resolves(self):
        from fcc_test_contracts.headless import api_contracts
        wanted: set[str] = set()
        for path in (REPO_ROOT / 'src', REPO_ROOT / 'tests', REPO_ROOT / 'scripts'):
            for file in path.rglob('*.py'):
                try:
                    tree = ast.parse(file.read_text(encoding='utf-8'))
                except (SyntaxError, UnicodeDecodeError, OSError):
                    continue
                for node in ast.walk(tree):
                    # ⚠️ 이사 뒤 저장소는 새 이름으로 임포트한다. 옛 이름만 세면
                    #    「아무도 안 쓴다」가 되어 스윕이 스스로 공허해진다.
                    if (isinstance(node, ast.ImportFrom) and node.module in (
                            'application.headless.api_contracts',
                            'fcc_test_contracts.headless.api_contracts')):
                        wanted |= {a.name for a in node.names}
        self.assertTrue(wanted, 'found no importers — the sweep itself failed')
        unresolved = sorted(n for n in wanted if not hasattr(api_contracts, n))
        self.assertEqual([], unresolved)


class TestTheContractPackageDoesNotGrow(unittest.TestCase):
    """A ratchet, not a ceiling.

    The surface axis makes the largest module BIGGER — 1,309 lines before,
    1,837 after — because ``surface_test_plan`` carries 18 of the 39 operations
    and headless surfaces carry DTOs that the central ones do not. That trade
    was measured, not overlooked: before, a test-plan change read parts of three
    files totalling ~2,900 lines; after, it reads one. Every cut that would
    shrink it was measured and rejected — splitting generation out costs 14.3
    points of single-module commits, and separating the DTOs re-creates the
    defect in 17 of 28 commits.

    What must not happen is this number drifting upward unwatched, so it
    ratchets: the recorded value may fall, never rise.
    """

    #: Measured 2026-08-29. Lower this when a module shrinks; raising it is the
    #: change this test exists to make someone argue for.
    LINE_BUDGET = {
        'surface_test_plan.py': 1837,
        'surface_reports.py': 426,
        # ⚠️ 2026-08-31 정정 — **완화가 아니라 오기 수정**이다.
        #    `338` 은 이 레포에서 **참인 적이 없다**: 이 파일은 첫 배송 이후 커밋이
        #    하나뿐이고(자란 적 없음) 실측은 351 이다. 그 숫자는 모노레포의 다른
        #    시점 측정치가 이관과 함께 따라온 것이다.
        #    근거: 나머지 **다섯은 정확히 일치**한다(1837·426·200·158·121) — 하나만
        #    어긋난다는 사실이 「전부 낡았다」가 아니라 「이 항목이 오기」임을 가른다.
        'surface_sessions.py': 351,
        'surface_jobs.py': 200,
        'surface_meta.py': 158,
        'surface_provider.py': 121,
    }

    def test_no_surface_module_exceeds_its_recorded_size(self):
        for name, budget in self.LINE_BUDGET.items():
            path = PACKAGE_DIR / name
            self.assertTrue(path.is_file(), f'{name} is gone — update the ratchet')
            actual = len(path.read_text(encoding='utf-8').splitlines())
            self.assertLessEqual(
                actual, budget,
                f'{name} grew to {actual} lines (recorded {budget}). Adding to a '
                'surface is normal; if the surface is genuinely bigger, measure '
                'whether it still wants to be one module before raising this.',
            )

    def test_the_ratchet_names_every_surface_module(self):
        on_disk = {p.name for p in PACKAGE_DIR.glob('surface_*.py')}
        self.assertEqual(
            on_disk, set(self.LINE_BUDGET),
            'a surface module with no recorded size is unwatched',
        )


class TestTheMeasurementSurvivesThisWave(unittest.TestCase):
    """The tool that decided this split is committed and still runs.

    The central surface's measurement was done by hand and thrown away, so this
    surface had to rebuild it before it could ask the same question. Keeping the
    tool is what makes the next surface's answer comparable to this one instead
    of to a number in a document.
    """

    TOOL = REPO_ROOT / 'scripts' / 'measure_contract_decomposition_axis.py'

    def test_the_tool_exists_and_parses(self):
        self.assertTrue(self.TOOL.is_file())
        ast.parse(self.TOOL.read_text(encoding='utf-8'))

    @staticmethod
    def _surface_table_names() -> set[str]:
        """Merged-table names, read off the two facades rather than listed."""
        names: set[str] = set()
        # ⚠️ 2026-08-31 — 헤드리스 파사드는 계약 패키지로 이사했고 central 은 여기
        #    남았다. 「같은 접두를 갖는 두 모듈」이라는 전제가 깨졌으므로 각자 적는다.
        for module_path in (
            'fcc_test_contracts.headless.api_contracts',
            # ⚠️ central 파사드는 모노레포에 남았다 — 이 레포에서는 헤드리스만 본다.
            # 'application.central_contract.api_contracts',
        ):
            module = importlib.import_module(module_path)
            names |= {
                name for name in getattr(module, '__all__', ())
                if '_API_' in name and name.isupper()
            }
        return names

    @staticmethod
    def _without_docstrings(tree: ast.AST) -> ast.AST:
        """Prose may name both surfaces; executable code may not depend on one."""
        for node in ast.walk(tree):
            body = getattr(node, 'body', None)
            if not isinstance(body, list) or not body:
                continue
            first = body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                body.pop(0)
        return tree

    def test_the_tool_derives_the_table_names_rather_than_naming_them(self):
        """Naming one surface's tables makes the tool unable to measure another.

        The docstring is exempt on purpose: it names both surfaces to say what
        the tool is for, and forbidding that would push the explanation out of
        the file. What is forbidden is a table name reaching the LOGIC — which
        is why this reads the AST with docstrings removed instead of grepping.
        """
        targets = self._surface_table_names()
        self.assertGreaterEqual(
            len(targets), 4,
            'derived no table names — the sweep failed and would pass vacuously',
        )
        tree = self._without_docstrings(
            ast.parse(self.TOOL.read_text(encoding='utf-8'))
        )
        hits = find_string_literals_anywhere(tree, targets)
        self.assertEqual([], hits, f'surface-specific table names in tool logic: {hits}')

    def test_that_check_can_see_a_synthetic_offender(self):
        """Non-vacuity: the same predicate must fire on code that does name one."""
        targets = self._surface_table_names()
        offender = ast.parse(
            '"""Docstring naming HEADLESS_API_ROUTES is fine."""\n'
            f'TABLE = {sorted(targets)[0]!r}\n'
        )
        self.assertEqual(
            [], find_string_literals_anywhere(
                ast.parse('"""%s."""' % sorted(targets)[0]), targets),
            'a docstring mention must NOT count, or the exemption is not real',
        )
        self.assertTrue(
            find_string_literals_anywhere(self._without_docstrings(offender), targets),
            'the predicate cannot see a table name in executable code',
        )

    def test_the_tool_scores_a_proposed_grouping(self):
        sys.path.insert(0, str(REPO_ROOT / 'scripts'))
        import measure_contract_decomposition_axis as tool
        self.assertTrue(hasattr(tool, 'score_grouping'))
        self.assertTrue(hasattr(tool, 'cluster_curve'))

class TestTheMutationBatteryCanStillFire(unittest.TestCase):
    """The battery's anchors still match the tree it is aimed at.

    An anchor that stopped matching does not fail — the replacement is a no-op,
    the seal passes, and the battery reports a kill it never made. That failure
    is invisible on the axis anyone checks (the battery's own output), which is
    why it is asserted here instead.

    ⚠️ The proposition is a **disjunction**: the file holds the pre-mutation form
    **or** the post-mutation form. Asserting only the pre-mutation text makes
    this test red while the battery is mid-run — and the obvious fix for that
    (drop the assertion) is exactly how a battery with no discriminating power
    comes to look healthy. See ``.claude/rules/check-axis-blindness.md``.
    """

    @staticmethod
    def _battery():
        sys.path.insert(0, str(REPO_ROOT / 'scripts'))
        import mutation_headless_contract_axis as battery
        return battery

    def test_every_anchor_matches_before_or_after_its_mutation(self):
        battery = self._battery()
        mutations = battery.build_mutations()
        self.assertGreaterEqual(
            len(mutations), 5,
            'derived no mutations — the battery would report a clean sweep of '
            'nothing, which is the failure this test exists to see',
        )
        stale = []
        for mutation in mutations:
            for path, old, new, occurrences in mutation.sites:
                text = (REPO_ROOT / path).read_text(encoding='utf-8')
                before = text.count(old) == occurrences
                after = bool(new) and new in text
                if not (before or after):
                    stale.append(f'{mutation.defect} -> {path}')
        self.assertEqual([], stale, f'anchors that match neither form: {stale}')

    def test_the_battery_covers_every_class_this_module_seals(self):
        """One mutation per property, so a new property arrives with its probe."""
        battery = self._battery()
        axes = {mutation.axis for mutation in battery.build_mutations()}
        self.assertGreaterEqual(
            len(axes), 8,
            'the battery aims at fewer axes than this module seals — a property '
            f'with no probe is a property nothing has ever tested: {sorted(axes)}',
        )

    def test_the_battery_uses_the_shared_harness(self):
        """A battery that re-implements apply/revert loses a check, not gains one.

        The first draft of this one did exactly that and shipped without the
        NOT-APPLIED verdict and the hang timeout — the two things that tell a
        mutation which was never applied apart from one that was survived.
        """
        battery = self._battery()
        self.assertTrue(hasattr(battery, 'MUTATIONS'))
        source = (REPO_ROOT / 'scripts' / 'mutation_headless_contract_axis.py').read_text(
            encoding='utf-8')
        self.assertIn('from mutation_harness import', source)
        self.assertIn('run_battery(', source)

    def test_the_battery_derives_its_targets_instead_of_listing_them(self):
        """A frozen target list rots silently the first time the split moves."""
        source = (REPO_ROOT / 'scripts' / 'mutation_headless_contract_axis.py').read_text(
            encoding='utf-8')
        tree = TestTheMeasurementSurvivesThisWave._without_docstrings(ast.parse(source))
        module_names = {
            path.stem for path in PACKAGE_DIR.glob('surface_*.py')
        }
        hits = find_string_literals_anywhere(tree, module_names)
        self.assertEqual(
            [], hits,
            f'the battery names surface modules literally {hits} — it must pick '
            'them out of the live registry so a reshaped split moves the targets',
        )


if __name__ == '__main__':
    unittest.main()
