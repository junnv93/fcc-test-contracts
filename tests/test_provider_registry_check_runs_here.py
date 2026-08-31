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
import unittest.mock
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
        """The registry and the artifact must agree on who the provider is.

        ⚠️ The name used here is deliberately WELL FORMED — a malformed one is
        stopped by the naming rule first and would never reach this check, so it
        would prove nothing about identity.
        """
        result = _run(
            _registry((('kc-unlicensed-headless', 'kc-unlicensed-conducted',
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


class TestTheNamingRuleIsEnforcedForNewProviders(unittest.TestCase):
    """⚠️ Nothing enforced these names, and the three that exist all disagree.

    The rule (operator, 2026-08-31) is ``<scheme>-<kind>-headless`` paired with
    ``<scheme>-<kind>-<method>``, agreeing on the first token. A ratchet, not a
    rewrite: renaming a live provider is a data migration, not a rename, because
    measurement rows hang off ``provider_id``.
    """

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _kc(self, provider_id: str, product_line: str) -> subprocess.CompletedProcess:
        """KC's own artifact does not exist yet, so borrow the SSOT's identity.

        The naming axis runs before compatibility, so an identity mismatch on the
        artifact is not what we are measuring here -- we assert the *naming*
        message specifically.
        """
        return _run(_registry(((provider_id, product_line,
                                'artifacts/headless_api_contract.v1.json'),)), self.tmp)

    def test_the_settled_kc_identity_passes_the_naming_rule(self) -> None:
        """It must not trip on naming — whatever else it trips on."""
        result = self._kc('kc-unlicensed-headless', 'kc-unlicensed-conducted')
        self.assertNotIn('does not match', result.stdout)
        self.assertNotIn('disagree on the certification scheme', result.stdout)

    def test_a_capital_letter_is_refused(self) -> None:
        """These strings are unique DB columns and must match byte-for-byte."""
        result = self._kc('kc-Unlicensed-headless', 'kc-unlicensed-conducted')
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn('does not match', json.loads(result.stdout)['error']['message'])

    def test_a_missing_headless_suffix_is_refused(self) -> None:
        result = self._kc('kc-unlicensed-conducted', 'kc-unlicensed-conducted')
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn('does not match', json.loads(result.stdout)['error']['message'])

    def test_a_scheme_disagreement_is_refused(self) -> None:
        """⚠️ The two fields naming different schemes is the silent one."""
        result = self._kc('kc-unlicensed-headless', 'fcc-unlicensed-conducted')
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn(
            'disagree on the certification scheme',
            json.loads(result.stdout)['error']['message'],
        )

    def test_the_grandfathered_three_still_pass(self) -> None:
        """The ratchet must not break what is already deployed."""
        result = _run(_registry(PUBLISHED), self.tmp)
        self.assertEqual(0, result.returncode, result.stdout)

    def test_the_grandfathered_set_is_exactly_the_three_that_predate_the_rule(self) -> None:
        """⚠️ Growth here is how a ratchet becomes an escape hatch."""
        from fcc_test_contracts.headless.provider_registry import NAMING_GRANDFATHERED
        self.assertEqual(
            {'fcc-unlicensed-conducted', 'fcc-mmwave-headless', 'fcc-licensed-headless'},
            set(NAMING_GRANDFATHERED),
            'a fourth provider does not get in here — the direction is to shrink',
        )

    def test_every_grandfathered_name_really_would_fail_the_rule(self) -> None:
        """Non-vacuity: a name that would pass anyway does not need grandfathering.

        ⚠️ Without this, the set could quietly accumulate names that comply, and
        then it stops being a record of debt and becomes a list nobody reads.
        """
        from fcc_test_contracts.headless import provider_registry as reg

        published = {pid: line for pid, line, _ in PUBLISHED}

        class _Entry:
            def __init__(self, provider_id: str, product_line: str) -> None:
                self.provider_id = provider_id
                self.product_line = product_line

        class _Registry:
            def __init__(self, entries) -> None:
                self.providers = tuple(entries)

        for provider_id in reg.NAMING_GRANDFATHERED:
            self.assertIn(
                provider_id, published,
                'a grandfathered name that is not registered is dead weight',
            )
            document = _Registry([_Entry(provider_id, published[provider_id])])
            with unittest.mock.patch.object(reg, 'NAMING_GRANDFATHERED', frozenset()):
                with self.assertRaises(
                    reg.ProviderRegistryError,
                    msg=f'{provider_id} passes the rule — remove it from the set',
                ):
                    reg.validate_registry_naming(document)


if __name__ == '__main__':
    unittest.main()
