import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))
sys.path.insert(0, str(project_root))


class TestApiContractCompatibilityChecker(unittest.TestCase):
    def _contract(self):
        from fcc_test_contracts.headless.api_contracts import ApiContractSnapshot

        return ApiContractSnapshot().to_dict()

    def test_matching_contract_is_compatible(self):
        from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

        result = check_api_contract_compatibility(self._contract())

        self.assertTrue(result.compatible)
        self.assertEqual(result.issues, [])

    def test_same_major_version_difference_is_warning_not_incompatible(self):
        from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

        provider = self._contract()
        provider['version'] = '1.1.0'
        provider['compatibility_major'] = 1

        result = check_api_contract_compatibility(provider)

        self.assertTrue(result.compatible)
        self.assertEqual(result.issues, [])
        self.assertEqual(result.warnings[0].code, 'version_difference')

    def test_provider_metadata_does_not_affect_compatibility(self):
        from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

        provider = self._contract()
        provider['provider'] = {
            'provider_id': 'fcc-mmwave-headless',
            'product_line': 'mmwave',
            'contract_family': 'fcc-conducted-headless',
        }

        result = check_api_contract_compatibility(provider)

        self.assertTrue(result.compatible)

    def test_route_path_drift_is_reported(self):
        from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

        provider = copy.deepcopy(self._contract())
        provider['routes']['submit_measurement_job']['path'] = '/jobs'

        result = check_api_contract_compatibility(provider)

        self.assertFalse(result.compatible)
        self.assertEqual(result.issues[0].code, 'route_path_mismatch')
        self.assertEqual(result.issues[0].path, 'routes.submit_measurement_job.path')

    def test_missing_schema_is_reported(self):
        from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

        provider = copy.deepcopy(self._contract())
        provider['schemas'].pop('SubmitMeasurementJobRequest')

        result = check_api_contract_compatibility(provider)

        self.assertFalse(result.compatible)
        self.assertIn('missing_schema', {issue.code for issue in result.issues})

    def test_live_subset_allows_missing_unimplemented_surface_as_warning(self):
        from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

        provider = copy.deepcopy(self._contract())
        provider['routes'].pop('submit_report_request')
        provider['operations'].pop('submit_report_request')
        provider['schemas'].pop('SubmitReportRequest')

        result = check_api_contract_compatibility(provider, mode='live-subset')

        self.assertTrue(result.compatible)
        self.assertEqual(result.issues, [])
        self.assertIn('missing_route', {warning.code for warning in result.warnings})
        self.assertIn('missing_operation', {warning.code for warning in result.warnings})
        self.assertIn('missing_schema', {warning.code for warning in result.warnings})

    def test_live_subset_still_reports_declared_route_drift(self):
        from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

        provider = copy.deepcopy(self._contract())
        provider['routes']['submit_measurement_job']['path'] = '/jobs'

        result = check_api_contract_compatibility(provider, mode='live-subset')

        self.assertFalse(result.compatible)
        self.assertIn('route_path_mismatch', {issue.code for issue in result.issues})

    def test_operation_response_drift_is_reported(self):
        from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

        provider = copy.deepcopy(self._contract())
        provider['operations']['headless_status']['response'] = 'OtherStatus'

        result = check_api_contract_compatibility(provider)

        self.assertFalse(result.compatible)
        self.assertIn('operation_response_mismatch', {issue.code for issue in result.issues})

    def test_operation_permission_drift_is_reported(self):
        from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

        provider = copy.deepcopy(self._contract())
        provider['operations']['submit_measurement_job']['permission'] = 'headless:read'

        result = check_api_contract_compatibility(provider)

        self.assertFalse(result.compatible)
        self.assertIn('operation_permission_mismatch', {issue.code for issue in result.issues})

    def test_incompatible_major_version_is_reported(self):
        from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

        provider = self._contract()
        provider['compatibility_major'] = 999

        result = check_api_contract_compatibility(provider)

        self.assertFalse(result.compatible)
        self.assertIn('compatibility_major_mismatch', {issue.code for issue in result.issues})

    def test_script_returns_zero_for_compatible_contract(self):
        from scripts.check_headless_api_contract import main

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'provider.json'
            path.write_text(json.dumps(self._contract()), encoding='utf-8')
            with mock.patch('builtins.print') as mocked_print:
                exit_code = main([str(path)])

        self.assertEqual(exit_code, 0)
        payload = json.loads(mocked_print.call_args.args[0])
        self.assertTrue(payload['compatible'])

    def test_script_returns_one_for_incompatible_contract(self):
        from scripts.check_headless_api_contract import main

        provider = self._contract()
        provider['version'] = '2.0.0'
        provider['compatibility_major'] = 2
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'provider.json'
            path.write_text(json.dumps(provider), encoding='utf-8')
            with mock.patch('builtins.print') as mocked_print:
                exit_code = main([str(path)])

        self.assertEqual(exit_code, 1)
        payload = json.loads(mocked_print.call_args.args[0])
        self.assertFalse(payload['compatible'])
        self.assertEqual(payload['issues'][0]['code'], 'compatibility_major_mismatch')
        self.assertEqual(payload['warnings'][0]['code'], 'version_difference')

    def test_script_live_subset_returns_zero_for_missing_unimplemented_surface(self):
        from scripts.check_headless_api_contract import main

        provider = copy.deepcopy(self._contract())
        provider['routes'].pop('submit_report_request')
        provider['operations'].pop('submit_report_request')
        provider['schemas'].pop('SubmitReportRequest')
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'provider.json'
            path.write_text(json.dumps(provider), encoding='utf-8')
            with mock.patch('builtins.print') as mocked_print:
                exit_code = main(['--mode', 'live-subset', str(path)])

        self.assertEqual(exit_code, 0)
        payload = json.loads(mocked_print.call_args.args[0])
        self.assertTrue(payload['compatible'])
        self.assertIn('missing_operation', {warning['code'] for warning in payload['warnings']})

    def test_script_usage_error_returns_two(self):
        from scripts.check_headless_api_contract import main

        with mock.patch('builtins.print'):
            self.assertEqual(main([]), 2)


if __name__ == '__main__':
    unittest.main()
