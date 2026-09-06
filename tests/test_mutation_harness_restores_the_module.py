"""The mutation battery must hand back the tree it borrowed.

``scripts/mutation_harness.py`` is this repository's instrument for the
question *"what does this seal actually catch?"*, and its own header states the
rule that makes the answer trustworthy: **a mutation that never applied and a
mutation that survived print the same thing.** Everything it checks is
therefore about the *source* — the original text occurs the expected number of
times, the write changed the file, the result still parses.

None of that reaches the layer the seal actually executes. CPython validates a
``.pyc`` against ``(source mtime truncated to whole seconds, source size)``, so
a write that lands in the same second as the previous one and keeps the size
unchanged leaves bytecode compiled from the mutation looking valid. Both
conditions are ordinary rather than exotic:

* the same second is every battery whose seal runs in under a second;
* the same size is every **length-preserving** mutation — the recommended
  shape, because it is the one least likely to change behaviour by accident.

Measured 2026-09-06 against the harness as it stood: a two-mutation battery
reported both verdicts **correctly**, ``git status`` came back clean, the
source was byte-identical to its original — and running the seal in that tree
afterwards **failed**, because the module answered with the mutated constant.
The verdicts were right and the tree was poisoned, which is the worse of the
two outcomes: nothing in the battery's output says so, and the next person to
run anything there debugs a defect that is not in the source they are reading.

So this file runs a real battery, on a real temporary tree, and asks the
question the harness could not ask about itself.
"""
from __future__ import annotations

import json
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

#: The subject module. ``SEALED`` is asserted by the probe seal and ``UNSEALED``
#: is not, so the battery has one mutation it must kill and one it must let
#: through — a battery that answered the same for both would prove nothing.
SUBJECT = 'UNSEALED = "aaaa"\nSEALED = "bbbb"\n'

PROBE_SEAL = textwrap.dedent(
    """
    from subject import SEALED

    def test_the_sealed_value():
        assert SEALED == "bbbb"
    """
).lstrip()

BATTERY = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    import os
    # ⚠️ Passed by environment, not argv: `run_battery` owns sys.argv and
    # argparse rejects anything it did not declare.
    sys.path.insert(0, os.environ['PROBE_HARNESS_DIR'])
    from mutation_harness import Mutation, run_battery

    HERE = Path(__file__).parent
    # ⚠️ Both mutations are length-preserving. That is the recommended shape
    # AND the trap's second condition — they are the same thing.
    MUTATIONS = (
        Mutation(axis='probe', defect='outside the seal (must SURVIVE)',
                 path='subject.py', old='UNSEALED = "aaaa"',
                 new='UNSEALED = "zzzz"', occurrences=1),
        Mutation(axis='probe', defect='inside the seal (must be KILLED)',
                 path='subject.py', old='SEALED = "bbbb"',
                 new='SEALED = "cccc"', occurrences=1),
    )
    raise SystemExit(run_battery(seal='test_probe_seal.py', mutations=MUTATIONS,
                                 repo_root=HERE, doc='probe'))
    """
).lstrip()


class TestTheBatteryHandsBackTheTreeItBorrowed(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self._tmp.name)
        (self.tree / 'subject.py').write_text(SUBJECT, encoding='utf-8')
        (self.tree / 'test_probe_seal.py').write_text(PROBE_SEAL, encoding='utf-8')
        (self.tree / 'battery.py').write_text(BATTERY, encoding='utf-8')
        # A bare environment: PYTHONPATH from this checkout would put a second
        # copy of everything on the probe's path.
        self.env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
        self.env['PYTHONDONTWRITEBYTECODE'] = ''    # the trap needs .pyc to exist
        self.env['PROBE_HARNESS_DIR'] = str(HARNESS.parent)
        self.battery = self._run_battery()

    def tearDown(self):
        self._tmp.cleanup()

    def _run_battery(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.tree / 'battery.py')],
            cwd=str(self.tree), capture_output=True, text=True,
            timeout=600, env=self.env,
        )

    def _subject_value(self, name: str) -> str:
        """What a *fresh interpreter* reads out of the tree — not what the file says."""
        probe = subprocess.run(
            [sys.executable, '-c',
             f'import json, subject; print(json.dumps(subject.{name}))'],
            cwd=str(self.tree), capture_output=True, text=True,
            timeout=120, env=self.env,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr[-800:])
        return json.loads(probe.stdout)

    def test_the_battery_distinguished_the_two_mutations(self):
        """Non-vacuity. A battery that could not run proves nothing below.

        ⚠️ Asserted on the **per-mutation verdict lines**, not on the tally
        string. The first draft read ``'1/2 KILLED'`` and broke the day the
        tally grew a control column — for a reason that has nothing to do with
        what this test is about. A summary line is a rendering; the verdicts
        are the fact.
        """
        verdicts = _verdict_lines(self.battery.stdout)
        self.assertEqual(len(verdicts), 2, self.battery.stdout[-900:])
        self.assertTrue(any('SURVIVED' in line for line in verdicts), verdicts)
        self.assertTrue(any('KILLED' in line for line in verdicts), verdicts)
        self.assertNotIn('NOT-APPLIED [', self.battery.stdout)

    def test_the_source_comes_back(self):
        """The half the harness already checked — kept so a regression is legible."""
        self.assertEqual(
            (self.tree / 'subject.py').read_text(encoding='utf-8'), SUBJECT,
        )

    def test_the_module_comes_back_too(self):
        """The half it could not: what the next process actually executes.

        This is the assertion that was red before 2026-09-06. The source above
        is byte-identical either way, so nothing short of importing in a fresh
        interpreter can tell the two states apart.
        """
        self.assertEqual(self._subject_value('SEALED'), 'bbbb')
        self.assertEqual(self._subject_value('UNSEALED'), 'aaaa')

    def test_the_seal_the_battery_borrowed_is_green_afterwards(self):
        """The shape a person actually meets: the next run in that tree."""
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', '-q', 'test_probe_seal.py'],
            cwd=str(self.tree), capture_output=True, text=True,
            timeout=600, env=self.env,
        )

        self.assertEqual(
            result.returncode, 0,
            'the battery left a tree whose seal fails while its source is '
            f'unchanged:\n{result.stdout[-1200:]}',
        )


if __name__ == '__main__':
    unittest.main()
