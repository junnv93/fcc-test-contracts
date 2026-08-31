"""The registry check must actually RUN in the tree that owns its inputs.

⚠️ **This file exists because the previous arrangement failed silently.** The
checker lived in ``fcc-test-platform`` while the artifacts and the batch checker
it calls lived here, and in the delivered platform box it died at its first
import. Both boxes reported green the whole time, because **nothing executed the
entry point** -- the only thing that named the hazard was a sentence in the
script's own docstring.

So these tests do not read source. They **run the thing**.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / 'scripts' / 'check_headless_provider_registry.py'
ARTIFACTS = REPO_ROOT / 'artifacts'

#: The artifacts this tree publishes, as a registry would name them.
PUBLISHED = (
    ('fcc-unlicensed-conducted', 'unlicensed-conducted',
     'artifacts/headless_api_contract.v1.json'),
    ('fcc-mmwave-headless', 'mmwave',
     'artifacts/mmwave_headless_api_contract.example.json'),
    ('fcc-licensed-headless', 'licensed-conducted',
     'artifacts/licensed_headless_api_contract.example.json'),
)


def _registry(providers) -> dict:
    return {
        'registry_version': 1,
        'providers': [
            {
                'provider_id': pid,
                'product_line': line,
                'contract_family': 'fcc-conducted-headless',
                'contract_artifact': artifact,
            }
            for pid, line, artifact in providers
        ],
    }


def _run(document: dict, tmp: Path) -> subprocess.CompletedProcess:
    path = tmp / 'registry.json'
    path.write_text(json.dumps(document, indent=2), encoding='utf-8')
    env = {'PYTHONPATH': str(REPO_ROOT)}
    import os
    merged = dict(os.environ)
    merged.update(env)
    return subprocess.run(
        [sys.executable, str(CHECKER), str(path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), env=merged,
    )


class TestTheCheckerRunsInThisTree(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_the_entry_point_imports_and_exits_zero(self) -> None:
        """⚠️ The defect this replaces was an ImportError, not a wrong answer."""
        result = _run(_registry(PUBLISHED), self.tmp)
        self.assertEqual(
            0, result.returncode,
            f'checker did not run.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}',
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload['compatible'], payload)
        self.assertEqual(len(PUBLISHED), len(payload['providers']))

    def test_every_named_artifact_resolves_against_this_tree(self) -> None:
        """``contract_artifact`` is lane-relative to the tree that publishes it."""
        for _, _, artifact in PUBLISHED:
            self.assertTrue(
                (REPO_ROOT / artifact).is_file(),
                f'{artifact} is not in this tree — the registry names what we publish',
            )

    # -- non-vacuity: the checks above must be able to fail ------------------

    def test_a_missing_artifact_is_refused(self) -> None:
        """Without this, a green run proves nothing about resolution."""
        result = _run(
            _registry((('x-provider', 'x-line', 'artifacts/does_not_exist.json'),)),
            self.tmp,
        )
        self.assertEqual(2, result.returncode, result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload['compatible'])
        self.assertEqual('registry_usage_error', payload['error']['code'])

    def test_an_identity_mismatch_is_refused(self) -> None:
        """The registry and the artifact must agree on who the provider is."""
        result = _run(
            _registry((('wrong-id', 'unlicensed-conducted',
                        'artifacts/headless_api_contract.v1.json'),)),
            self.tmp,
        )
        self.assertEqual(2, result.returncode, result.stdout)
        payload = json.loads(result.stdout)
        self.assertIn('provider_id mismatch', payload['error']['message'])

    def test_an_incompatible_artifact_is_refused(self) -> None:
        """A contract that drops operations must not pass as compatible."""
        contract = json.loads(
            (ARTIFACTS / 'headless_api_contract.v1.json').read_text(encoding='utf-8'))
        kept = sorted(contract['operations'])[:5]
        contract['operations'] = {k: contract['operations'][k] for k in kept}
        maimed = self.tmp / 'maimed.json'
        maimed.write_text(json.dumps(contract, indent=2), encoding='utf-8')

        document = _registry((
            ('fcc-unlicensed-conducted', 'unlicensed-conducted', str(maimed)),
        ))
        result = _run(document, self.tmp)
        self.assertEqual(1, result.returncode, result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload['compatible'])

    def test_no_registry_path_is_a_usage_error_not_a_pass(self) -> None:
        """⚠️ The registry is platform-owned; there is no default in this tree."""
        import os
        merged = dict(os.environ)
        merged['PYTHONPATH'] = str(REPO_ROOT)
        result = subprocess.run(
            [sys.executable, str(CHECKER)],
            capture_output=True, text=True, cwd=str(REPO_ROOT), env=merged,
        )
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertFalse(json.loads(result.stdout)['compatible'])


if __name__ == '__main__':
    unittest.main()
