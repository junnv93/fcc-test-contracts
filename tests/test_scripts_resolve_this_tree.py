"""Every entry point must publish and check THIS tree, not an installed copy.

Measured 2026-09-05: ``scripts/export_headless_api_contract.py`` omitted the
project root from ``sys.path``, so running the documented publish command
imported ``fcc_test_contracts`` from the interpreter's site-packages and wrote
**that** contract into ``artifacts/``. The installed copy still carried the
``row_identity_source`` enum removed in PR #25, so publishing reinstated a
repaired defect in the delivered artifact — and the artifact is what providers
derive from.

⚠️ **The first attempt to bound that defect was itself the same defect.** It
grepped for one literal spelling of the fix and concluded six more scripts were
broken. Running them showed otherwise — most reach the same result through
``contract_cli.ensure_importable``, a spelling no grep for the literal could
see. A check that reads for a spelling answers a different question than the
one asked, which is what this repository keeps naming and what this file exists
to stop happening a third time.

So this measures, and measuring found the count was neither one nor seven but
**two**: the publisher above and ``mutation_headless_contract_axis``, which put
``scripts/`` and a non-existent ``src/`` on the path but not the root — so the
battery mutated an installed build nobody edits. Both are repaired; this file is
what keeps them repaired.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / 'scripts'

#: Probe run inside the entry point's own process. ``run_name`` is deliberately
#: not ``__main__``: module-level ``sys.path`` setup is what we are measuring,
#: and running the CLI body would need arguments, side effects and a tmpdir.
#:
#: ⚠️ The probe MUST run with a working directory outside this tree, and the
#: first draft did not — ``python -c`` puts the cwd on ``sys.path``, so with
#: ``cwd=PROJECT_ROOT`` every script "resolved this tree" whether it asked to or
#: not. ``test_the_probe_can_actually_fail`` caught that, which is the only
#: reason it is in this file.
_PROBE = textwrap.dedent(
    '''
    import pathlib, runpy, sys
    script = pathlib.Path(sys.argv[1])
    # What CPython itself puts at sys.path[0] for ``python scripts/x.py``.
    sys.path.insert(0, str(script.parent))
    try:
        runpy.run_path(str(script), run_name='__probe__')
    except BaseException:
        pass
    try:
        import fcc_test_contracts.headless.api_contract_surfaces as module
    except Exception as error:  # pragma: no cover - reported as a failure
        print(f'IMPORT-ERROR {error}')
    else:
        print(pathlib.Path(module.__file__).resolve())
    '''
)


def _run_probe(script: Path) -> subprocess.CompletedProcess:
    """Run the probe the way an OPERATOR runs the command, not the way CI does.

    Two things have to be taken away, and each was found by the falsifiability
    test below rather than by reasoning:

    * **the working directory** — ``python -c`` puts the cwd on ``sys.path``, so
      probing from the project root reported every script as correct;
    * **``PYTHONPATH``** — ``lane_check.observe`` exports the repo root in it
      before running the suite, so inside the gate every script reaches this
      tree whatever it does. ⚠️ That is worth stating plainly: **the gate's own
      environment would have hidden the defect this file exists to catch.** The
      documented operator command (judgement §9) sets no ``PYTHONPATH``, and
      that is the environment the question is about.
    """
    env = {
        key: value for key, value in os.environ.items()
        if key not in {'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP'}
    }
    with tempfile.TemporaryDirectory() as elsewhere:
        return subprocess.run(
            [sys.executable, '-c', _PROBE, str(script)],
            cwd=elsewhere, env=env, capture_output=True, text=True,
        )


def _entry_points() -> list[Path]:
    """Runnable entry points that reach the contract package, derived not listed.

    ⚠️ Derived on purpose. A hand-kept list is where a new script goes to be
    forgotten, and a forgotten script is exactly one that can publish or check
    the wrong tree without anyone noticing.

    ⚠️ ``__main__`` is the criterion, and it is not decoration. ``contract_cli``
    names ``fcc_test_contracts`` and supplies ``ensure_importable`` to everyone
    else, but nobody RUNS it — it is imported by scripts that have already put
    the root on the path. Judging it by "mentions the package" reported it as
    broken; judging it by "is something an operator can run" does not. The
    question this file asks is about processes, so the set has to be processes.
    """
    found = []
    for path in sorted(SCRIPTS.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        if 'fcc_test_contracts' in text and "__main__" in text:
            found.append(path)
    return found


class TestEveryEntryPointResolvesThisTree(unittest.TestCase):

    def test_the_entry_point_set_is_not_empty(self):
        """Non-emptiness: a glob that matches nothing passes every assertion."""
        self.assertGreaterEqual(len(_entry_points()), 5)

    def test_each_entry_point_imports_the_package_from_this_tree(self):
        for script in _entry_points():
            with self.subTest(script.name):
                completed = _run_probe(script)
                resolved = completed.stdout.strip().splitlines()
                self.assertTrue(
                    resolved,
                    f'probe produced nothing: {completed.stderr[-500:]}',
                )
                where = resolved[-1]
                self.assertFalse(
                    where.startswith('IMPORT-ERROR'),
                    f'{script.name}: {where}',
                )
                self.assertTrue(
                    Path(where).is_relative_to(PROJECT_ROOT),
                    f'{script.name} imports fcc_test_contracts from {where}, '
                    f'outside this tree. Add the project root to sys.path '
                    f'(or call contract_cli.ensure_importable) — otherwise it '
                    f'publishes or checks an installed copy of what it is '
                    f'supposed to be reading.',
                )

    def test_the_probe_can_actually_fail(self):
        """A guard that cannot fail proves nothing about what it guards.

        Runs the probe against a script that deliberately does NOT put the
        project root on the path. If the assertion above is vacuous — because
        the probe's own ``sys.path`` already reaches this tree, say — this test
        catches it.

        ⚠️ It has caught it **twice** already: once when the probe ran with the
        project root as its working directory, and once when it inherited
        ``PYTHONPATH`` from ``lane_check``. Neither was visible by reading the
        code; both were visible the moment something asserted the guard could
        fail.
        """
        decoy = SCRIPTS / '_probe_decoy_not_a_real_entry_point.py'
        decoy.write_text('import fcc_test_contracts  # noqa\n', encoding='utf-8')
        try:
            completed = _run_probe(decoy)
            where = completed.stdout.strip().splitlines()[-1]
            self.assertFalse(
                Path(where).is_relative_to(PROJECT_ROOT),
                'the probe reaches this tree without the script asking, so the '
                'assertion above cannot fail and measures nothing',
            )
        finally:
            decoy.unlink(missing_ok=True)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
