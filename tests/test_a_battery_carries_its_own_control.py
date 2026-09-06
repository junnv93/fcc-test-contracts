"""A battery must be able to say *"nothing should observe this"* — and be refused.

``run_battery`` already asks whether the unmutated tree is green before it
writes anything. That answers the question **once, before the run**, and it is
blind to anything the run itself introduces: machinery that breaks the seal
while mutating passes the baseline and then kills every mutation, and every one
of those kills is recorded as a seal doing its job.

The KC provider lane met exactly that on 2026-09-06. Two probes it had just
added behaved differently *inside* the battery environment than outside, so its
battery reported ``RED`` for every mutation — including one whose only change
was a character in a docstring. The uniformity was the signal and nothing was
positioned to read it: the control had been run by hand, once, on a day when it
happened to pass.

So the control moves into the specification. ``Mutation.expect`` (default
``'KILLED'``) lets a battery carry a mutation nothing can observe and require it
to come back ``SURVIVED``. It does not test the seal — it tests **the battery**,
and when it fails the battery says so about the whole run rather than about that
one entry.

⚠️ ``expect='SURVIVED'`` is a claim, not an excuse. A mutation the seal fails to
catch is still reported and still fails the run; what changes is only that a
deliberate no-op can now be stated, and contradicted.
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HARNESS = PROJECT_ROOT / 'scripts' / 'mutation_harness.py'

_VERDICT_LINE = re.compile(r'^ ?\d+\. ')

SUBJECT = '# a comment nothing reads\nSEALED = "bbbb"\n'

PROBE_SEAL = textwrap.dedent(
    """
    from subject import SEALED

    def test_the_sealed_value():
        assert SEALED == "bbbb"
    """
).lstrip()

BATTERY = textwrap.dedent(
    """
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, os.environ['PROBE_HARNESS_DIR'])
    from mutation_harness import Mutation, run_battery

    # The control and the genuine defect differ in ONE way: whether anything
    # can observe the change. Both apply cleanly and both parse.
    CONTROL = Mutation(
        axis='CONTROL', defect='a comment nothing reads',
        path='subject.py', old='# a comment nothing reads',
        new='# a comment nothing reads at all', occurrences=1,
        expect=os.environ['PROBE_CONTROL_EXPECT'],
    )
    GENUINE = Mutation(
        axis='probe', defect='an ordinary defect the seal catches',
        path='subject.py', old='SEALED = "bbbb"', new='SEALED = "cccc"',
        occurrences=1,
    )
    CASES = {
        'honoured': (CONTROL, GENUINE),
        # An ordinary miss: the seal genuinely fails to catch this, and the
        # default expectation applies. Nothing about the run is invalidated.
        'survivor': (
            Mutation(
                axis='probe', defect='a defect this seal does not look at',
                path='subject.py', old='# a comment nothing reads',
                new='# a comment nothing reads at all', occurrences=1,
            ),
        ),
        'contradicted': (
            # Same flag, but pointed at something the seal *does* see. The
            # claim "nothing observes this" is false and must be refused.
            Mutation(
                axis='CONTROL', defect='claims to be unobservable and is not',
                path='subject.py', old='SEALED = "bbbb"', new='SEALED = "dddd"',
                occurrences=1, expect='SURVIVED',
            ),
        ),
    }
    raise SystemExit(run_battery(seal='test_probe_seal.py',
                                 mutations=CASES[os.environ['PROBE_CASE']],
                                 repo_root=Path(__file__).parent, doc='probe'))
    """
).lstrip()


class TestAControlLivesInTheSpecification(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self._tmp.name)
        (self.tree / 'subject.py').write_text(SUBJECT, encoding='utf-8')
        (self.tree / 'test_probe_seal.py').write_text(PROBE_SEAL, encoding='utf-8')
        (self.tree / 'battery.py').write_text(BATTERY, encoding='utf-8')

    def tearDown(self):
        self._tmp.cleanup()

    def _battery(self, case: str, expect: str = 'SURVIVED'):
        env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
        env['PROBE_HARNESS_DIR'] = str(HARNESS.parent)
        env['PROBE_CASE'] = case
        env['PROBE_CONTROL_EXPECT'] = expect
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

    def _verdicts(self, result) -> list:
        return [l for l in result.stdout.splitlines() if _VERDICT_LINE.match(l)]

    def test_a_control_that_holds_does_not_fail_the_run(self):
        """Before ``expect``, a deliberate no-op could only be run by hand:
        ``SURVIVED`` always failed the battery, so no battery kept one."""
        result = self._battery('honoured')

        control, genuine = self._verdicts(result)
        self.assertIn('SURVIVED', control, result.stdout[-900:])
        self.assertIn('KILLED', genuine, result.stdout[-900:])
        self.assertEqual(result.returncode, 0, result.stdout[-900:])

    def test_the_run_says_it_carried_a_control(self):
        """A reader must be able to see that the baseline was checked *here*."""
        self.assertIn('대조군', self._battery('honoured').stdout)

    def test_a_control_that_is_killed_invalidates_the_whole_run(self):
        """The point of the mechanism.

        If something can kill a mutation nothing observes, it was underneath the
        other mutations too — so the message is about the run, not the entry.
        """
        result = self._battery('contradicted')

        self.assertNotEqual(result.returncode, 0, result.stdout[-900:])
        self.assertIn('대조군이 KILLED', result.stdout, result.stdout[-900:])
        self.assertIn('이 실행의 다른 KILLED', result.stdout, result.stdout[-900:])

    def test_an_ordinary_survival_does_not_claim_the_run_is_invalid(self):
        """The other direction, and the one that rots quietly.

        A seal that misses a defect is a statement about **that seal**. Folding
        it into the control's message prints *"every verdict in this run is
        meaningless"* next to every ordinary survival — and a warning that
        appears every time is read by nobody, which removes the reason the
        control exists.

        Measured 2026-09-06: collapsing the two branches passed the whole
        harness suite (21 tests). Nothing was positioned to notice.
        """
        result = self._battery('survivor')

        verdict = self._verdicts(result)[0]
        self.assertIn('SURVIVED', verdict, result.stdout[-900:])
        self.assertIn('봉인이 보지 못한다', result.stdout, result.stdout[-900:])
        self.assertNotIn('대조군이 KILLED', result.stdout, result.stdout[-900:])
        self.assertNotIn('배터리부터', result.stdout, result.stdout[-900:])
        self.assertNotEqual(result.returncode, 0, result.stdout[-900:])

    def test_the_invalidation_message_names_the_likelier_cause_first(self):
        """A control that comes back KILLED has two causes, not one.

        This repository met the second one first: its opening control candidate
        added a comment **line**, and a line-count ratchet observed it — the
        battery was clean and the control was wrong. A message naming only
        *"the machinery contaminated the run"* sends the reader to audit
        machinery that is fine.
        """
        stdout = self._battery('contradicted').stdout

        self.assertIn('원인이 둘', stdout, stdout[-900:])
        self.assertIn('무관측이 아니다', stdout, stdout[-900:])

    def test_the_default_expectation_is_still_a_kill(self):
        """Control by declaration only. An entry that says nothing must be
        caught, or every existing battery would have quietly become advisory.

        Asserted by *running* the same control with the default expectation
        rather than by reading the dataclass — a default nobody exercises is a
        default that can change without anything noticing.
        """
        result = self._battery('honoured', expect='KILLED')

        control = self._verdicts(result)[0]
        self.assertIn('SURVIVED', control)
        self.assertNotEqual(result.returncode, 0, result.stdout[-900:])


if __name__ == '__main__':
    unittest.main()
