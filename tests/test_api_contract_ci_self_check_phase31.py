import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'src'))

from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact  # noqa: E402


class TestApiContractCiSelfCheck(unittest.TestCase):
    def test_checked_in_artifact_passes_compatibility_script(self):
        from scripts.check_headless_api_contract import main

        artifact = resolve_repo_artifact(__file__, 'docs/api/headless_api_contract.v1.json')

        with mock.patch('builtins.print') as mocked_print:
            exit_code = main([str(artifact)])

        payload = json.loads(mocked_print.call_args.args[0])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload['compatible'])
        self.assertEqual(payload['issues'], [])

    def test_mutated_artifact_fails_compatibility_script(self):
        from scripts.check_headless_api_contract import main

        artifact = resolve_repo_artifact(__file__, 'docs/api/headless_api_contract.v1.json')
        mutated = copy.deepcopy(json.loads(artifact.read_text(encoding='utf-8')))
        mutated['routes']['headless_status']['path'] = '/wrong/status'

        with tempfile.TemporaryDirectory() as tmpdir:
            provider_path = Path(tmpdir) / 'provider.json'
            provider_path.write_text(json.dumps(mutated), encoding='utf-8')

            with mock.patch('builtins.print') as mocked_print:
                exit_code = main([str(provider_path)])

        payload = json.loads(mocked_print.call_args.args[0])
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload['compatible'])
        self.assertIn(
            'route_path_mismatch',
            {issue['code'] for issue in payload['issues']},
        )


if __name__ == '__main__':
    unittest.main()
