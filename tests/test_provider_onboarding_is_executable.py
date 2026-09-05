"""The onboarding procedure must be *runnable*, in the box that is handed over.

Prose that has never been run is a guess about software, and it is discovered to
be wrong on a joining team's first day — the worst possible audience. This file
runs it.

## Why the gate is here and not where it used to be

There was already such a gate. It lived in the monorepo
(``tests/test_provider_onboarding_package.py``), it staged this lane out of the
monorepo with the extraction packager, and it ran the document from the staged
tree. It has been dead since 2026-08-31: the retirement commit ``91d0febe``
deleted ``packaging/fcc-test-contracts/**`` and ``src/application/common/**``
from the monorepo, so the packager now answers ``missing_source`` for 70 of the
79 entries this lane declares and every test in the module dies in ``setUp``.
That is not a defect to repair — the monorepo cannot stage this box any more,
by construction, because this box left it.

Measured 2026-09-05, and what the silence cost is legible: while the gate was
dead the document's paths went stale everywhere except the section written
after it died. ``§1`` told a joining team to run
``scripts/check_headless_api_contract.py artifacts/mmwave_….json`` and that
command exits **2** — the artifacts moved into the package on 2026-09-04 so a
wheel could carry them. The first command in the procedure did not work, and
nothing said so.

So the gate moves to the lane that owns both halves. There is nothing to stage:
**this repository is the delivered box.** What is staged instead is the box as
a recipient receives it — the tracked files only, with no working-tree
leftovers and no ``.git`` — so a command that only works because of something
untracked fails here rather than on their first day.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fcc_test_contracts.headless import api_contract_checker  # noqa: E402

ONBOARDING_DOC = (
    PROJECT_ROOT / 'fcc_test_contracts' / 'artifacts' / 'provider_onboarding.md'
)
EVIDENCE_SCHEMA = (
    PROJECT_ROOT / 'fcc_test_contracts' / 'artifacts'
    / 'provider_contract_conformance_evidence.schema.v2.json'
)
EXAMPLE_CONTRACT = (
    'fcc_test_contracts/artifacts/mmwave_headless_api_contract.example.json'
)

#: ```console blocks that follow one of these markers are executed verbatim.
#: Deriving the command list from the document is the point: a command that
#: stops working turns the document red instead of quietly misleading a reader.
_COMMAND_BLOCK = re.compile(
    r'<!-- onboarding-commands: (?P<name>[a-z-]+) -->\s*```console\n(?P<body>.*?)```',
    re.DOTALL,
)

#: The evidence skeleton §7.2 prints. Named by its heading rather than by
#: position so inserting a section above it does not silently select another
#: block — and the ```json fence means the assertion below reads the same
#: bytes a provider copies.
_EVIDENCE_SKELETON = re.compile(
    r'### 7\.2 Emit the evidence.*?```json\n(?P<body>.*?)```', re.DOTALL,
)


def _parse_command_blocks(text: str) -> dict[str, list[tuple[str, int]]]:
    """``{marker: [(command, expected_exit), ...]}`` as the document declares them."""
    blocks: dict[str, list[tuple[str, int]]] = {}
    for match in _COMMAND_BLOCK.finditer(text):
        commands: list[tuple[str, int]] = []
        pending: str | None = None
        for line in match.group('body').splitlines():
            if line.startswith('$ '):
                if pending is not None:
                    commands.append((pending, 0))
                pending = line[2:].strip()
            elif line.strip().startswith('# exit:') and pending is not None:
                commands.append((pending, int(line.split(':', 1)[1].strip())))
                pending = None
        if pending is not None:
            commands.append((pending, 0))
        blocks[match.group('name')] = commands
    return blocks


def _delivered_box(target: Path) -> Path:
    """The box as a recipient receives it: tracked files, no ``.git``.

    ``git ls-files`` rather than a copied directory, and rather than running in
    place. Running in place would let an untracked working-tree file answer for
    a delivered one — the class of pass that means nothing — and would write
    ``my_contract.json`` into the checkout. Copying the whole directory would
    carry ``.git`` and every build artifact, which a provider never receives.

    Derived, not listed: a new artifact is delivered because it is tracked, so
    nothing here needs updating when the box grows.
    """
    listing = subprocess.run(
        ['git', 'ls-files', '-z'], cwd=str(PROJECT_ROOT),
        capture_output=True, text=True, timeout=120, check=True,
    )
    tracked = [name for name in listing.stdout.split('\0') if name]
    assert tracked, 'git ls-files returned nothing — this is not a checkout'
    for name in tracked:
        source = PROJECT_ROOT / name
        if not source.is_file():          # a submodule or a deleted-but-tracked path
            continue
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return target


class _RunsInTheDeliveredBox(unittest.TestCase):
    """Shared fixture: one staged box for every command this file runs."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.box = _delivered_box(Path(cls._tmp.name) / 'fcc-test-contracts')
        # §3 checks a contract the reader authors in §2, and §2 tells them to
        # copy the example. The fixture does exactly what the document says
        # rather than inventing a contract the document never mentions.
        shutil.copy(cls.box / EXAMPLE_CONTRACT, cls.box / 'my_contract.json')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_documented(self, command: str) -> subprocess.CompletedProcess:
        """Run one ``$ …`` line from the document, in the box.

        ``shlex`` rather than ``str.split``: §7.0 runs ``python3 -c "…"`` and
        §7.2 passes ``--features ''``, and a whitespace split turns the first
        into a dozen arguments and the second into two literal quote
        characters. A gate that mangles what it claims to execute is measuring
        its own parser.

        ``sys.executable`` replaces the leading ``python3`` so the suite tests
        the interpreter it is running under — the alternative is a gate that
        goes green against whichever Python happens to be first on ``PATH``.

        ``PYTHONPATH`` is stripped: with this repository on it, every command
        would pass by importing the checkout instead of the box, which is the
        one thing this file exists to refuse.
        """
        self.assertTrue(
            command.startswith('python3 '),
            'only python entry points are executed here; a shell command in a '
            'verified block would run unreviewed',
        )
        env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
        return subprocess.run(
            [sys.executable, *shlex.split(command)[1:]],
            cwd=str(self.box), capture_output=True, text=True,
            timeout=600, env=env,
        )


class TestTheOnboardingDocumentIsExecutable(_RunsInTheDeliveredBox):
    """Every declared command is run, in the box, with its declared exit code."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.blocks = _parse_command_blocks(ONBOARDING_DOC.read_text(encoding='utf-8'))

    def test_the_document_declares_commands_to_run(self):
        """Guard against a silent no-op: a renamed marker would empty the suite.

        Asserted as a set rather than a count — *"five blocks"* stays true when
        one is renamed and another disappears, and a suite that runs zero
        commands reports exactly what a suite that runs them all reports.
        """
        self.assertEqual(
            set(self.blocks),
            {'package', 'authored', 'features', 'identity', 'evidence'},
        )
        for name, commands in self.blocks.items():
            with self.subTest(block=name):
                self.assertGreater(len(commands), 0)

    def test_every_declared_command_behaves_as_documented(self):
        for name, commands in self.blocks.items():
            for command, expected_exit in commands:
                with self.subTest(block=name, command=command):
                    result = self.run_documented(command)
                    self.assertEqual(
                        result.returncode, expected_exit,
                        f'{command}\n{result.stdout[-800:]}\n{result.stderr[-800:]}',
                    )
                    self.assertNotIn('Traceback', result.stderr)

    def test_the_evidence_block_actually_runs_the_conformance_mode(self):
        """Non-vacuous control for the block that unblocks registration.

        Every command above could exit 0 while checking nothing in particular.
        This asserts the ``evidence`` block is the one that carries the mode the
        centre demands — the coupling this file was written to hold.
        """
        commands = [command for command, _ in self.blocks['evidence']]
        self.assertTrue(commands)
        for command in commands:
            self.assertIn('--mode declared-features', command)

    def test_the_first_command_prints_a_compatible_verdict(self):
        """§1 promises `"compatible": true`; a bare exit code cannot say that."""
        command, expected_exit = self.blocks['package'][1]
        self.assertEqual(expected_exit, 0)

        result = self.run_documented(command)

        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertTrue(json.loads(result.stdout)['compatible'])


class TestTheDocumentAndTheToolNameTheSameMode(_RunsInTheDeliveredBox):
    """``declared-features`` is written in four places; they must be one value.

    The library constant, the checker CLI's ``--mode`` choices, the evidence
    schema's ``evidence wrong-mode`` failure and the §7.2 skeleton a provider
    copies. Nothing joined them, and the axis was measured broken on
    2026-09-05: §7.2 demanded ``checker.mode = "declared-features"``, the
    central gate refused every other value, and the CLI the document points at
    accepted only ``full`` and ``live-subset``. A provider could produce the
    digest and could not produce the result — four steps of a five-step
    handover.
    """

    def test_the_skeleton_names_the_mode_the_library_implements(self):
        skeleton = _EVIDENCE_SKELETON.search(
            ONBOARDING_DOC.read_text(encoding='utf-8')
        )
        self.assertIsNotNone(skeleton, '§7.2 no longer prints an evidence skeleton')
        evidence = json.loads(skeleton.group('body'))

        self.assertEqual(
            evidence['checker']['mode'],
            api_contract_checker._DECLARED_FEATURES_MODE,
        )

    def test_the_schema_refuses_every_other_mode_by_that_same_name(self):
        schema = json.loads(EVIDENCE_SCHEMA.read_text(encoding='utf-8'))
        wrong_mode = [
            name for name in schema['failure_names']
            if name.startswith('evidence wrong-mode')
        ]

        self.assertEqual(len(wrong_mode), 1, schema['failure_names'])
        self.assertIn(
            repr(api_contract_checker._DECLARED_FEATURES_MODE).replace('"', "'"),
            wrong_mode[0],
        )

    def test_the_shipped_cli_accepts_it(self):
        """The gap that blocked registration: the value existed everywhere but here."""
        result = self.run_documented(
            'python3 scripts/check_headless_api_contract.py --help'
        )

        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertIn(api_contract_checker._DECLARED_FEATURES_MODE, result.stdout)

    def test_the_mode_and_the_declaration_cannot_be_separated_at_the_cli(self):
        """Both halves of the refusal, so neither arm can rot into a no-op."""
        for command in (
            f'python3 scripts/check_headless_api_contract.py '
            f'--mode declared-features {EXAMPLE_CONTRACT}',
            f'python3 scripts/check_headless_api_contract.py '
            f'--mode full --features core {EXAMPLE_CONTRACT}',
        ):
            with self.subTest(command=command):
                result = self.run_documented(command)

                self.assertEqual(result.returncode, 2, result.stdout[-800:])
                self.assertEqual(
                    json.loads(result.stdout)['error']['code'],
                    'features_mode_mismatch',
                )

    def test_an_undeclarable_feature_is_a_result_not_a_usage_error(self):
        """Exit 1, because §7.3 records it as `evidence unscoped` — a red result."""
        result = self.run_documented(
            f'python3 scripts/check_headless_api_contract.py '
            f'--mode declared-features --features no-such-feature {EXAMPLE_CONTRACT}'
        )

        self.assertEqual(result.returncode, 1, result.stdout[-800:])
        payload = json.loads(result.stdout)
        self.assertFalse(payload['compatible'])
        self.assertEqual(
            [issue['code'] for issue in payload['issues']],
            ['unknown_declared_feature'],
        )

    def test_the_two_entry_points_read_one_declaration_format(self):
        """A provider pastes the same list into both commands.

        Spelled twice, the two parsers drift and the disagreement surfaces as a
        digest mismatch blamed on the contract. This runs both on the same
        awkward string — spaces, a trailing separator, a blank token — and
        requires them to agree about the scope it names.
        """
        declaration = ' measurement-jobs , , report-automation,'

        identity = self.run_documented(
            f'python3 scripts/print_contract_identity.py --features {shlex.quote(declaration)}'
        )
        check = self.run_documented(
            f'python3 scripts/check_headless_api_contract.py --mode declared-features '
            f'--features {shlex.quote(declaration)} {EXAMPLE_CONTRACT}'
        )

        self.assertEqual(identity.returncode, 0, identity.stderr[-800:])
        self.assertEqual(check.returncode, 0, check.stdout[-800:])
        self.assertEqual(
            json.loads(identity.stdout)['features'],
            ['core', 'measurement-jobs', 'report-automation'],
        )


if __name__ == '__main__':
    unittest.main()
