import sys
import unittest
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

from fcc_test_contracts.headless.api_contracts import HEADLESS_API_OPERATIONS  # noqa: E402


class TestApiAccessPolicy(unittest.TestCase):
    def test_all_operations_declare_explicit_permissions(self):
        from fcc_test_contracts.headless.api_contracts import (
            HEADLESS_API_OPERATIONS,
            HEADLESS_API_PERMISSIONS,
        )

        self.assertEqual(set(HEADLESS_API_OPERATIONS), set(HEADLESS_API_PERMISSIONS))
        for operation, contract in HEADLESS_API_OPERATIONS.items():
            self.assertEqual(contract['permission'], HEADLESS_API_PERMISSIONS[operation])
            self.assertTrue(contract['permission'])

    def test_public_operations_are_explicit_and_anonymous_allowed(self):
        from fcc_test_contracts.common.access_policy import (
            API_PERMISSION_PUBLIC,
            ApiPrincipal,
            ApiAccessPolicy,
        )
        from fcc_test_contracts.headless.api_contracts import (
            HEADLESS_API_OPERATIONS,
            HEADLESS_API_PERMISSIONS,
        )

        public_operations = {
            operation
            for operation, permission in HEADLESS_API_PERMISSIONS.items()
            if permission == API_PERMISSION_PUBLIC
        }

        # ``stream_report_output_download`` (FE-P6) is a presigned-token download
        # endpoint: public at the RBAC layer (no header auth) but gated by a signed
        # ``token`` query param, NOT anonymous-unprotected. The grant that issues the
        # token (``create_report_output_download``) stays permission-protected.
        self.assertEqual(
            public_operations,
            {'health_check', 'headless_api_contract', 'stream_report_output_download'},
        )
        # security invariant: the public download route is token-gated, and its grant
        # issuer is protected — public route ≠ unprotected data.
        stream_op = HEADLESS_API_OPERATIONS['stream_report_output_download']
        query_param_names = {p['name'] for p in stream_op.get('query_params', [])}
        self.assertIn('token', query_param_names)
        self.assertEqual(
            HEADLESS_API_PERMISSIONS['create_report_output_download'],
            'report_automation:read',
        )

        policy = ApiAccessPolicy(operations=HEADLESS_API_OPERATIONS)
        for operation in public_operations:
            decision = policy.authorize(operation, ApiPrincipal.anonymous())
            self.assertTrue(decision.allowed, decision.to_dict())

    def test_allowed_when_principal_has_required_permission(self):
        from fcc_test_contracts.common.access_policy import ApiPrincipal, ApiAccessPolicy

        principal = ApiPrincipal.from_permissions('operator', ['headless:control'])

        decision = ApiAccessPolicy(operations=HEADLESS_API_OPERATIONS).authorize('submit_measurement_job', principal)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.required_permission, 'headless:control')
        self.assertEqual(decision.subject, 'operator')

    def test_denied_when_permission_missing(self):
        from fcc_test_contracts.common.access_policy import ApiPrincipal, ApiAccessPolicy

        principal = ApiPrincipal.from_permissions('viewer', ['headless:read'])

        decision = ApiAccessPolicy(operations=HEADLESS_API_OPERATIONS).authorize('stop_measurement_job', principal)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, 'missing_permission')
        self.assertEqual(decision.required_permission, 'headless:control')

    def test_admin_and_wildcard_permissions_allow_protected_operations(self):
        from fcc_test_contracts.common.access_policy import ApiPrincipal, ApiAccessPolicy

        policy = ApiAccessPolicy(operations=HEADLESS_API_OPERATIONS)
        admin = ApiPrincipal.from_permissions('admin', ['admin'])
        wildcard = ApiPrincipal.from_permissions('platform', ['*'])

        self.assertTrue(
            policy.authorize('cancel_report_automation_request', admin).allowed
        )
        self.assertTrue(
            policy.authorize('cancel_report_automation_request', wildcard).allowed
        )

    def test_unknown_operation_is_denied(self):
        from fcc_test_contracts.common.access_policy import ApiPrincipal, ApiAccessPolicy

        decision = ApiAccessPolicy(operations=HEADLESS_API_OPERATIONS).authorize(
            'unknown_operation',
            ApiPrincipal.from_permissions('operator', ['*']),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, 'unknown_operation')

    def test_missing_permission_contract_is_denied(self):
        from fcc_test_contracts.common.access_policy import ApiPrincipal, ApiAccessPolicy

        policy = ApiAccessPolicy({
            'broken': {'request': None, 'response': 'HealthCheckResponse'},
        })

        decision = policy.authorize('broken', ApiPrincipal.anonymous())

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, 'missing_permission_contract')


if __name__ == '__main__':
    unittest.main()
