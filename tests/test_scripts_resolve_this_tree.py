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

⚠️ **And the axis is what the script CONTRIBUTES to ``sys.path``, not where the
import happens to resolve.** The first draft asked the second question and CI
disproved it: CI installs with ``pip install -e``, so the package resolves
*inside the tree* no matter what the script does, and the assertion was vacuous
there. Resolution is a property of the environment; putting the root on the path
is a property of the script. Only the second is the same question in every
environment — which is the whole point of asking it.
"""
from __future__ import annotations

import json
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
    import json, pathlib, runpy, sys
    script = pathlib.Path(sys.argv[1])
    root = pathlib.Path(sys.argv[2]).resolve()
    # ⚠️ Take the tree OFF the path first, however it got there — an editable
    # install writes a ``.pth`` naming the project root, and a script guarded by
    # ``if str(root) not in sys.path`` would then skip its own insert and look
    # path-blind. What is being asked is whether the SCRIPT supplies the root,
    # so nothing else may supply it first.
    sys.path[:] = [p for p in sys.path if p and pathlib.Path(p).resolve() != root]
    # What CPython itself puts at sys.path[0] for ``python scripts/x.py``.
    sys.path.insert(0, str(script.parent))
    before = list(sys.path)
    try:
        runpy.run_path(str(script), run_name='__probe__')
    except BaseException:
        pass
    added = [entry for entry in sys.path if entry not in before]
    print('PROBE ' + json.dumps(added))
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

    The probe itself takes one more thing away — the project root, wherever it
    sits on ``sys.path`` — because CI installs with ``pip install -e`` and the
    resulting ``.pth`` names that root. Left in place, a script guarded by
    ``if str(root) not in sys.path`` skips its own insert and reads as
    path-blind. **Three environments, three different ways to make this check
    vacuous, and all three were found by the falsifiability test rather than by
    reading.**
    """
    env = {
        key: value for key, value in os.environ.items()
        if key not in {'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP'}
    }
    with tempfile.TemporaryDirectory() as elsewhere:
        return subprocess.run(
            [sys.executable, '-c', _PROBE, str(script), str(PROJECT_ROOT)],
            cwd=elsewhere, env=env, capture_output=True, text=True,
        )


def _puts_root_on_path(script: Path) -> bool:
    """Did running ``script`` add this tree to ``sys.path``?"""
    completed = _run_probe(script)
    for line in completed.stdout.splitlines():
        if line.startswith('PROBE '):
            added = json.loads(line[len('PROBE '):])
            return any(
                Path(entry).resolve() == PROJECT_ROOT for entry in added
            )
    raise AssertionError(
        f'probe produced no verdict for {script.name}: '
        f'{completed.stderr[-500:]}'
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

    def test_each_entry_point_puts_this_tree_on_the_path(self):
        for script in _entry_points():
            with self.subTest(script.name):
                self.assertTrue(
                    _puts_root_on_path(script),
                    f'{script.name} never puts {PROJECT_ROOT} on sys.path, so '
                    f'which fcc_test_contracts it reads depends on how the '
                    f'package happens to be installed. Insert the project root '
                    f'(or call contract_cli.ensure_importable) — otherwise it '
                    f'publishes or checks an installed copy of what it is '
                    f'supposed to be reading. Measured 2026-09-05: that is how '
                    f'a repaired defect came back in a delivered artifact.',
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
        decoy.write_text(
            "import fcc_test_contracts  # noqa\n"
            "if __name__ == '__main__':  # entry-point shaped, path-blind\n"
            "    pass\n",
            encoding='utf-8',
        )
        try:
            self.assertFalse(
                _puts_root_on_path(decoy),
                'a script that touches sys.path not at all still satisfies the '
                'assertion above, so that assertion measures nothing',
            )
        finally:
            decoy.unlink(missing_ok=True)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
