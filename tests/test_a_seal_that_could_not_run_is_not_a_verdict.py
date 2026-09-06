"""A mutation the seal could not run is not a mutation the seal caught.

``scripts/mutation_harness.py`` already refuses two shapes of this, and its
header says why: *"a mutation that never applied and a mutation that survived
print the same thing."* It checks that the original text was there, that the
write changed the file, and — since 2026-08-27, after one mutation orphaned an
``except`` and took 33 tests down while being tallied ``KILLED`` — that the
result still **parses**.

Parsing is not running. A mutation that renames the symbol the seal imports
parses perfectly, and then ``pytest`` exits **2** having collected nothing and
run no test. The harness read every non-zero exit as *"the seal went red"*, so
that verdict was ``KILLED`` — the battery reporting that a seal caught a defect
it was never shown.

Measured 2026-09-06 on the harness as it stood, with a one-mutation battery
whose only change was ``def sealed():`` → ``def seaIed():``::

     1. KILLED   [probe] 봉인이 import 하는 이름을 없앤다
    1/1 KILLED · 0 SURVIVED · 0 NOT-APPLIED · 0 HUNG

    $ pytest -q -x --tb=no test_probe_seal.py ; echo $?
    2

``pytest`` distinguishes these already — ``1`` is *tests ran and failed*, while
``2``/``3``/``4``/``5`` are *the run did not happen* (``5`` being **collected
nothing**, which one typo in a seal path produces). The harness now reads that
distinction instead of flattening it.

⚠️ The KC provider lane measured the same class independently and in a worse
shape: a hardcoded interpreter name resolved to a stub that returned a constant
non-zero code, so a whole battery reported ``1/1 red`` without ``pytest``
running once. Two lanes, two causes, one conflation — which is why this file
asserts the *verdict vocabulary* rather than any single cause.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

#: A battery's per-mutation verdict line. ``run_battery`` prints it as
#: ``f'{index:2}. {label} [{axis}] {defect}'`` — at most one leading space —
#: while its end-of-run summaries indent the same text by three more. Selecting
#: on the marker alone catches both, which is how the first draft of these
#: assertions counted one mutation twice.
_VERDICT_LINE = re.compile(r'^ ?\d+\. ')


def _verdict_lines(stdout: str) -> list:
    return [line for line in stdout.splitlines() if _VERDICT_LINE.match(line)]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HARNESS = PROJECT_ROOT / 'scripts' / 'mutation_harness.py'
if str(HARNESS.parent) not in sys.path:
    sys.path.insert(0, str(HARNESS.parent))

from mutation_harness import verdict_for  # noqa: E402

SUBJECT = 'SEALED = "bbbb"\n\n\ndef sealed():\n    return SEALED\n'

PROBE_SEAL = textwrap.dedent(
    """
    from subject import sealed

    def test_the_sealed_value():
        assert sealed() == "bbbb"
    """
).lstrip()

BATTERY = textwrap.dedent(
    """
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, os.environ['PROBE_HARNESS_DIR'])
    from mutation_harness import Mutation, run_battery

    # ⚠️ Chosen so the two cases differ in ONE way — whether the seal can run.
    # Both parse, both change the file, both are length-preserving.
    CASES = {
        # Renames the symbol the seal imports: pytest exits 2, collecting nothing.
        'unrunnable': Mutation(
            axis='probe', defect='the seal cannot even import its subject',
            path='subject.py', old='def sealed():', new='def seaIed():',
            occurrences=1),
        # An ordinary defect: the seal runs and fails. This is the control —
        # without it a harness that answered NO-RUN to everything would pass.
        'genuine': Mutation(
            axis='probe', defect='an ordinary defect the seal does catch',
            path='subject.py', old='SEALED = "bbbb"', new='SEALED = "cccc"',
            occurrences=1),
    }
    raise SystemExit(run_battery(seal='test_probe_seal.py',
                                 mutations=(CASES[os.environ['PROBE_CASE']],),
                                 repo_root=Path(__file__).parent, doc='probe'))
    """
).lstrip()


class TestTheVerdictVocabularyKeepsThemApart(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self._tmp.name)
        (self.tree / 'subject.py').write_text(SUBJECT, encoding='utf-8')
        (self.tree / 'test_probe_seal.py').write_text(PROBE_SEAL, encoding='utf-8')
        (self.tree / 'battery.py').write_text(BATTERY, encoding='utf-8')

    def tearDown(self):
        self._tmp.cleanup()

    def _battery(self, case: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
        env['PROBE_HARNESS_DIR'] = str(HARNESS.parent)
        env['PROBE_CASE'] = case
        result = subprocess.run(
            [sys.executable, str(self.tree / 'battery.py')],
            cwd=str(self.tree), capture_output=True, text=True,
            timeout=600, env=env,
        )
        self.assertIn(
            'baseline OK', result.stdout,
            f'the probe battery never started:\n{result.stdout[-800:]}\n'
            f'{result.stderr[-800:]}',
        )
        return result

    def _verdict_line(self, result: subprocess.CompletedProcess) -> str:
        """The one numbered verdict line this single-mutation battery printed."""
        lines = _verdict_lines(result.stdout)
        self.assertEqual(len(lines), 1, result.stdout[-900:])
        return lines[0]

    def test_a_mutation_the_seal_cannot_run_is_not_killed(self):
        """The assertion that was red before 2026-09-06."""
        result = self._battery('unrunnable')

        # ⚠️ The verdict line, not the tally string — see the note in
        # test_the_battery_distinguished_the_two_mutations for why.
        verdict = self._verdict_line(result)
        self.assertIn('NO-RUN', verdict, result.stdout[-900:])
        self.assertNotIn('KILLED', verdict, result.stdout[-900:])

    def test_the_refusal_names_what_actually_happened(self):
        """A verdict a reader cannot act on is a verdict they will ignore."""
        result = self._battery('unrunnable')

        self.assertIn('pytest exit 2', result.stdout, result.stdout[-900:])

    def test_no_run_is_a_battery_failure_not_a_pass(self):
        """`NOT-APPLIED` is already a failure for the same reason: it did not ask."""
        self.assertNotEqual(self._battery('unrunnable').returncode, 0)

    def test_a_mutation_the_seal_does_run_is_still_killed(self):
        """The control. Without it, answering NO-RUN to everything would pass.

        Same tree, same seal, same battery — the single difference is whether
        the mutated module can be imported.
        """
        result = self._battery('genuine')

        verdict = self._verdict_line(result)
        self.assertIn('KILLED', verdict, result.stdout[-900:])
        self.assertNotIn('NO-RUN', verdict, result.stdout[-900:])
        self.assertEqual(result.returncode, 0, result.stdout[-900:])


class TestOnlyOneCodeIsEverEvidence(unittest.TestCase):
    """``verdict_for`` sealed across its whole domain, not only where a probe reaches.

    The class below produces real situations and feeds back whatever ``pytest``
    returned — which is the right way to learn *which* code a situation makes,
    and it necessarily leaves the rest of the domain untouched. Measured
    2026-09-06: those probes exercise ``0``, ``1``, ``2``, ``4`` and ``5``, so
    ``3`` (internal error) and everything above ``5`` never reach the classifier
    at all. A second exception added there would be seen by nothing.

    That matters because the second exception is the failure this whole axis is
    about: the original defect *was* ``returncode != 0`` meaning ``fail``, and
    the repair is one narrow exception. Narrow exceptions grow. The KC provider
    lane's environment already produces codes this repository never will — a
    stubbed interpreter answering ``49``, a shell answering ``9009`` — and the
    rule that keeps both lanes honest is not a list of codes but a sentence:
    **only ``1`` is evidence that a test ran.**

    ⚠️ This asserts the *rule*, never an attribution. Which situation yields
    which number is the class below's question, and it answers it by
    measurement, because a written-down attribution is exactly what went stale:
    two lanes independently wrote that a mistyped seal path exits ``5`` — it is
    ``4`` — and no check contradicted either of them, since both classify as
    ``NO-RUN`` and nothing downstream behaves differently. A statement that
    changes no behaviour has no natural gate.
    """

    def test_zero_is_the_only_pass(self):
        self.assertEqual(verdict_for(0), 'pass')

    def test_one_is_the_only_evidence_that_a_test_ran_and_failed(self):
        self.assertEqual(verdict_for(1), 'fail')

    def test_every_other_code_says_the_run_did_not_happen(self):
        """Including the ones this repository cannot produce, and 128+N signals."""
        for code in [*range(2, 16), 49, 130, 137, 9009]:
            with self.subTest(returncode=code):
                self.assertEqual(
                    verdict_for(code), 'no-run',
                    f'exit {code} is read as evidence about the seal — only 1 is',
                )


class TestTheExitCodeTableIsMeasuredNotRecited(unittest.TestCase):
    """Each situation is *produced*, and the code ``pytest`` returns is read back.

    A table of exit codes written into a docstring is a second opinion next to
    the tool that owns them, and it rots without contradicting anything. This
    one already did: the first draft attributed *a typo in a seal path* to exit
    ``5``. Measured, that is ``4`` — ``5`` is ``-k`` matching nothing. Both are
    ``NO-RUN``, so no verdict would ever have disagreed with the wrong sentence,
    and the next reader would have gone looking for a collection that never
    happened.

    So nothing here asserts a number. Each case builds the situation, runs
    ``pytest`` exactly as :func:`run_battery` does, and requires
    :func:`verdict_for` to classify whatever came back. If ``pytest`` renumbers
    its codes, this goes red — which is the only place that should have to
    change.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self._tmp.name)
        (self.tree / 'test_passes.py').write_text(
            'def test_ok():\n    assert True\n', encoding='utf-8')
        (self.tree / 'test_fails.py').write_text(
            'def test_bad():\n    assert False\n', encoding='utf-8')
        (self.tree / 'test_broken_import.py').write_text(
            'import no_such_module_at_all\n\n'
            'def test_x():\n    assert True\n', encoding='utf-8')

    def tearDown(self):
        self._tmp.cleanup()

    def _pytest(self, *targets: str) -> int:
        """The same invocation ``run_battery`` uses, so this measures that path."""
        env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
        return subprocess.run(
            [sys.executable, '-m', 'pytest', *targets,
             '-q', '-x', '--tb=no', '-p', 'no:randomly'],
            cwd=str(self.tree), capture_output=True, text=True,
            timeout=600, env=env,
        ).returncode

    def test_tests_that_ran_and_passed(self):
        self.assertEqual(verdict_for(self._pytest('test_passes.py')), 'pass')

    def test_tests_that_ran_and_failed_are_the_only_evidence_of_a_kill(self):
        """The control. Everything else here is NO-RUN, so without this the
        classifier could answer ``'no-run'`` to every non-zero code and pass."""
        self.assertEqual(verdict_for(self._pytest('test_fails.py')), 'fail')

    def test_a_mutation_that_breaks_an_import(self):
        """The shape that was tallied ``KILLED`` before 2026-09-06."""
        self.assertEqual(
            verdict_for(self._pytest('test_broken_import.py')), 'no-run')

    def test_a_seal_path_that_does_not_exist(self):
        """One typo in a runner's ``SEAL`` constant."""
        self.assertEqual(
            verdict_for(self._pytest('test_no_such_file.py')), 'no-run')

    def test_a_seal_node_id_that_does_not_exist(self):
        """The file is right and the node name is not — a rename leaves this."""
        self.assertEqual(
            verdict_for(self._pytest('test_passes.py::test_renamed_away')),
            'no-run',
        )

    def test_a_selection_that_matches_nothing(self):
        """Collected nothing. A suite that runs no test satisfies every
        *"no new failures"* claim for free — this repository has met that
        shape elsewhere and refuses it here too."""
        self.assertEqual(
            verdict_for(self._pytest('test_passes.py', '-k', 'zzzz_matches_nothing')),
            'no-run',
        )


if __name__ == '__main__':
    unittest.main()
