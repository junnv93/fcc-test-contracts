"""Repository-relative artifacts resolve to wherever *this* tree keeps them.

``discover_tree_artifact`` (sealed next door) answers a depth question: *how far
up is the tree I am part of*. It does not answer the other half, and the other
half is what a delivered package actually changes — the extraction packager
moves ``docs/platform/migrations/001_x.sql`` to ``migrations/001_x.sql`` and
``src/application/platform/rbac_role_catalog.py`` to
``fcc_test_platform/application/rbac_role_catalog.py``. Measured 2026-08-15 on
the delivered trees, addressing artifacts by their monorepo path accounted for
363 failure reasons — the largest class in which the file is *present in the
box*, and invisible to the boundary axis and the dependency-resolution axis
alike, because **a path is not an import**. Files genuinely absent were a
larger raw class (433) and a different problem: mostly tests that should not
have travelled, plus artifacts a sibling lane owns.

The repair is not a table someone maintains. The packager already knows the
mapping — it just performed it — so it writes down what it did, and this
resolver reads that. The absence of that record is what makes a monorepo
checkout answer exactly as it did before.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

project_root = Path(__file__).resolve().parents[1]
for _path in (project_root, project_root / 'src'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fcc_test_contracts.common.tree_artifacts import (  # noqa: E402
    LAYOUT_RECORD_NAME,
    RelocationAmbiguity,
    resolve_repo_artifact,
)


def _tree(root: Path, paths: dict[str, str] | None) -> Path:
    """A tree shaped like a delivered box, with or without a layout record."""
    (root / 'tests').mkdir(parents=True, exist_ok=True)
    (root / 'tests' / 'test_probe.py').write_text('', encoding='utf-8')
    if paths is not None:
        (root / LAYOUT_RECORD_NAME).write_text(
            json.dumps({'schema': 1, 'repository': 'probe', 'paths': paths}),
            encoding='utf-8',
        )
    return root / 'tests' / 'test_probe.py'


class TestTheRequestMustNameSomething(unittest.TestCase):
    def test_an_empty_path_is_refused_rather_than_returning_the_root(self):
        """Resolving 'the tree root itself' is not this function's question.

        Accepting it silently would answer with the root for a caller that
        forgot its argument, which is the shape ``discover_tree_artifact``
        already refuses next door for the same reason.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            anchor = _tree(Path(tmpdir), {'src/a.py': 'pkg/a.py'})
            for empty in ('', '/', '//'):
                with self.subTest(value=empty):
                    with self.assertRaises(ValueError):
                        resolve_repo_artifact(anchor, empty)


class TestADeliveredTreeAnswersFromWhatThePackagerDid(unittest.TestCase):
    def test_an_exactly_recorded_file_resolves_to_its_delivered_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            anchor = _tree(root, {
                'docs/platform/migrations/001_initial_central_db.sql':
                    'migrations/001_initial_central_db.sql',
            })
            self.assertEqual(
                resolve_repo_artifact(
                    anchor, 'docs/platform/migrations/001_initial_central_db.sql'
                ),
                root / 'migrations' / '001_initial_central_db.sql',
            )

    def test_a_directory_move_is_derived_from_the_files_beneath_it(self):
        """No directory is declared twice — the files already say where they went."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            anchor = _tree(root, {
                'src/application/platform/a.py': 'fcc_test_platform/application/a.py',
                'src/application/platform/b.py': 'fcc_test_platform/application/b.py',
            })
            self.assertEqual(
                resolve_repo_artifact(anchor, 'src/application/platform'),
                root / 'fcc_test_platform' / 'application',
            )

    def test_files_that_land_at_the_tree_root_resolve_to_the_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            anchor = _tree(root, {'src/x.py': 'x.py', 'src/y.py': 'y.py'})
            self.assertEqual(resolve_repo_artifact(anchor, 'src'), root)

    def test_a_renamed_file_gives_no_directory_evidence(self):
        """A rename says nothing about where the directory went, and must not.

        ``src/application/headless/platform_ingestion.py`` is delivered as
        ``fcc_test_platform/provider_ingestion.py``. Reading a directory move
        out of that would claim ``src/application/headless`` became
        ``fcc_test_platform``, which is true for this file and false for its
        neighbours.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            anchor = _tree(root, {
                'src/application/headless/platform_ingestion.py':
                    'fcc_test_platform/provider_ingestion.py',
            })
            self.assertEqual(
                resolve_repo_artifact(anchor, 'src/application/headless'),
                root / 'src' / 'application' / 'headless',
            )
            # The rename itself is still addressable, by its exact path.
            self.assertEqual(
                resolve_repo_artifact(
                    anchor, 'src/application/headless/platform_ingestion.py'
                ),
                root / 'fcc_test_platform' / 'provider_ingestion.py',
            )

    def test_a_split_directory_raises_and_names_both_destinations(self):
        """Choosing would be a guess, and a guessing resolver is the old silence.

        This is not hypothetical: the platform box keeps
        ``docs/platform/central_db_schema.v1.json`` where it was and moves
        ``docs/platform/migrations/`` to the tree root, so ``docs/platform``
        genuinely has two answers.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            anchor = _tree(root, {
                'docs/platform/central_db_schema.v1.json':
                    'docs/platform/central_db_schema.v1.json',
                'docs/platform/migrations/001_x.sql': 'migrations/001_x.sql',
            })
            with self.assertRaises(RelocationAmbiguity) as caught:
                resolve_repo_artifact(anchor, 'docs/platform')
        message = str(caught.exception)
        self.assertIn('docs/platform', message)
        # The migrations landed at the tree root, which renders as the empty
        # string unless the message names it — and a reader who is told a path
        # went to '' has been told nothing.
        self.assertIn('<tree root>', message)
        self.assertNotIn("''", message)

    def test_an_unrecorded_path_resolves_to_itself_rather_than_being_invented(self):
        """"Not in the box" must stay reportable as the path the caller asked for."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            anchor = _tree(root, {'src/a.py': 'pkg/a.py'})
            self.assertEqual(
                resolve_repo_artifact(anchor, 'docs/api/nothing-here.json'),
                root / 'docs' / 'api' / 'nothing-here.json',
            )

    def test_the_nearest_record_wins_when_a_box_sits_inside_another_tree(self):
        """Staging puts several boxes side by side under one directory.

        Walking past a box to an outer marker would answer for the wrong tree —
        the delivered-depth failure this module's sibling exists to prevent,
        reproduced one level out.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            outer = Path(tmpdir)
            (outer / LAYOUT_RECORD_NAME).write_text(
                json.dumps({'schema': 1, 'repository': 'outer',
                            'paths': {'src/a.py': 'WRONG/a.py'}}),
                encoding='utf-8',
            )
            box = outer / 'fcc-test-platform'
            anchor = _tree(box, {'src/a.py': 'pkg/a.py'})
            self.assertEqual(
                resolve_repo_artifact(anchor, 'src/a.py'), box / 'pkg' / 'a.py',
            )


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
