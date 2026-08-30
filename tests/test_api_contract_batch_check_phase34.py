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


class TestApiContractBatchCheck(unittest.TestCase):
    def _contract(self, product_line: str):
        from fcc_test_contracts.headless.api_contracts import ApiContractSnapshot, DEFAULT_PROVIDER_METADATA

        provider = dict(DEFAULT_PROVIDER_METADATA)
        provider['provider_id'] = f'fcc-{product_line}'
        provider['product_line'] = product_line
        return ApiContractSnapshot(provider=provider).to_dict()

    def _write_json(self, directory: Path, name: str, payload: dict) -> Path:
        path = directory / name
        path.write_text(json.dumps(payload), encoding='utf-8')
        return path

    def test_batch_script_returns_zero_when_all_providers_are_compatible(self):
        from scripts.check_headless_api_contracts_batch import main

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unlicensed = self._write_json(
                root, 'unlicensed.json', self._contract('unlicensed-conducted')
            )
            mmwave = self._write_json(
                root, 'mmwave.json', self._contract('mmwave')
            )
            licensed = self._write_json(
                root, 'licensed.json', self._contract('licensed-conducted')
            )

            with mock.patch('builtins.print') as mocked_print:
                exit_code = main([str(unlicensed), str(mmwave), str(licensed)])

        payload = json.loads(mocked_print.call_args.args[0])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload['compatible'])
        self.assertEqual(len(payload['providers']), 3)
        self.assertIn('warnings', payload['providers'][0])
        self.assertEqual(
            {row['provider']['product_line'] for row in payload['providers']},
            {'unlicensed-conducted', 'mmwave', 'licensed-conducted'},
        )

    def test_batch_script_returns_one_when_any_provider_is_incompatible(self):
        from scripts.check_headless_api_contracts_batch import main

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good = self._write_json(root, 'good.json', self._contract('unlicensed-conducted'))
            bad_payload = copy.deepcopy(self._contract('mmwave'))
            bad_payload['routes']['headless_status']['method'] = 'POST'
            bad = self._write_json(root, 'bad.json', bad_payload)

            with mock.patch('builtins.print') as mocked_print:
                exit_code = main([str(good), str(bad)])

        payload = json.loads(mocked_print.call_args.args[0])
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload['compatible'])
        failing = [row for row in payload['providers'] if not row['compatible']]
        self.assertEqual(len(failing), 1)
        self.assertIn('route_method_mismatch', {issue['code'] for issue in failing[0]['issues']})

    def test_batch_script_usage_error_returns_two(self):
        from scripts.check_headless_api_contracts_batch import main

        with mock.patch('builtins.print'):
            self.assertEqual(main([]), 2)

    def test_batch_script_missing_file_returns_structured_usage_error(self):
        from scripts.check_headless_api_contracts_batch import main

        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / 'missing.json'
            with mock.patch('builtins.print') as mocked_print:
                exit_code = main([str(missing)])

        payload = json.loads(mocked_print.call_args.args[0])
        self.assertEqual(exit_code, 2)
        self.assertFalse(payload['compatible'])
        self.assertEqual(payload['error']['code'], 'usage_error')
        self.assertIn('missing.json', payload['error']['path'])

    def test_batch_script_invalid_json_returns_structured_usage_error(self):
        from scripts.check_headless_api_contracts_batch import main

        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / 'bad.json'
            bad.write_text('not json', encoding='utf-8')
            with mock.patch('builtins.print') as mocked_print:
                exit_code = main([str(bad)])

        payload = json.loads(mocked_print.call_args.args[0])
        self.assertEqual(exit_code, 2)
        self.assertFalse(payload['compatible'])
        self.assertEqual(payload['error']['code'], 'usage_error')


if __name__ == '__main__':
    unittest.main()
