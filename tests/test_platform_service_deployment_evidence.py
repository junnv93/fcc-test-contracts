import ast
import json
import unittest
from pathlib import Path

from fcc_test_contracts.common.provider_service_evidence import (
    REQUIRED_PROVIDER_ENV,
    is_provider_service_deployment_valid,
    provider_service_deployment_errors,
)

from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact


project_root = Path(__file__).parent.parent
MODULE_PATH = resolve_repo_artifact(__file__, 'src/application/headless/platform_service_evidence.py')
# The schema resolves the same way the module beside it already did. It did not
# until 2026-08-16, and that asymmetry was the defect: a delivered tree relocates
# both, so addressing one through the layout record and the other through a fixed
# project_root join means the pair only stays together in the monorepo.
SCHEMA_PATH = resolve_repo_artifact(
    __file__, 'docs/platform/provider_service_deployment_evidence.schema.v1.json'
)


def _valid_manifest() -> dict:
    return {
        'schema_version': 1,
        'provider_id': 'fcc-unlicensed-conducted',
        'host_id': 'lab-pc-01',
        'deployed_at': '2026-05-15T06:00:00+09:00',
        'service': {
            'service_name': 'fcc-unlicensed-headless-api',
            'service_manager': 'nssm',
            'start_mode': 'automatic',
            'command': [
                'C:/FCC_mobile_test_automation/fcc_test_env/Scripts/python.exe',
                '-m',
                'uvicorn',
                '--factory',
                'headless_api_app:create_app',
                '--host',
                '127.0.0.1',
                '--port',
                '8000',
            ],
        },
        'environment': {
            'FCC_HEADLESS_DB_PATH': 'C:/FCCData/unlicensed/headless.fcc.db',
            'FCC_HEADLESS_ARTIFACT_ROOTS': 'C:/FCCData/unlicensed/artifacts',
            'FCC_HEADLESS_REPORT_OUTPUT_DIR': 'C:/FCCData/unlicensed/reports',
            'FCC_HEADLESS_LOG_DIR': 'C:/FCCData/unlicensed/logs/headless-api',
            'FCC_HEADLESS_HEALTH_URL': 'http://127.0.0.1:8000/health',
            'FCC_HEADLESS_AUTH_TOKEN': '<redacted>',
        },
        'health_check': {
            'url': 'http://127.0.0.1:8000/health',
            'status_code': 200,
            'checked_at': '2026-05-15T06:03:00+09:00',
        },
        'log_collection': {
            'enabled': True,
            'log_dir': 'C:/FCCData/unlicensed/logs/headless-api',
            'collector': 'company-log-agent',
            'retention_days': 30,
        },
        'monitoring_alert': {
            'enabled': True,
            'health_url': 'http://127.0.0.1:8000/health',
            'alert_channel': 'Teams',
            'alert_target': 'fcc-lab-ops',
            'interval_seconds': 60,
        },
        'backup_scope': {
            'database_path': 'C:/FCCData/unlicensed/headless.fcc.db',
            'artifact_roots': ['C:/FCCData/unlicensed/artifacts'],
            'report_output_dir': 'C:/FCCData/unlicensed/reports',
        },
    }


class TestPlatformServiceDeploymentEvidence(unittest.TestCase):
    def test_valid_deployment_manifest_passes(self):
        manifest = _valid_manifest()

        self.assertTrue(is_provider_service_deployment_valid(manifest))
        self.assertEqual(provider_service_deployment_errors(manifest), [])

    def test_requires_provider_env_values(self):
        manifest = _valid_manifest()
        manifest['environment']['FCC_HEADLESS_ARTIFACT_ROOTS'] = ''

        issues = provider_service_deployment_errors(manifest)

        self.assertIn('missing_required_env', {issue.code for issue in issues})
        self.assertIn(
            'environment.FCC_HEADLESS_ARTIFACT_ROOTS',
            {issue.path for issue in issues},
        )

    def test_rejects_service_command_without_headless_factory(self):
        manifest = _valid_manifest()
        manifest['service']['command'] = ['python', '-m', 'uvicorn', 'other:app']

        issues = provider_service_deployment_errors(manifest)
        codes = {issue.code for issue in issues}

        self.assertIn('missing_factory_flag', codes)
        self.assertIn('missing_headless_app_factory', codes)

    def test_rejects_failed_health_check_and_disabled_ops(self):
        manifest = _valid_manifest()
        manifest['health_check']['status_code'] = 503
        manifest['log_collection']['enabled'] = False
        manifest['monitoring_alert']['enabled'] = False

        issues = provider_service_deployment_errors(manifest)
        codes = {issue.code for issue in issues}

        self.assertIn('health_check_failed', codes)
        self.assertIn('log_collection_disabled', codes)
        self.assertIn('monitoring_disabled', codes)

    def test_rejects_unredacted_secret_like_env_values(self):
        manifest = _valid_manifest()
        manifest['environment']['FCC_HEADLESS_AUTH_TOKEN'] = 'plain-secret-value'

        issues = provider_service_deployment_errors(manifest)

        self.assertIn('secret_value_not_redacted', {issue.code for issue in issues})
        self.assertIn('environment.FCC_HEADLESS_AUTH_TOKEN', {issue.path for issue in issues})

    def test_requires_backup_scope_for_db_artifacts_and_reports(self):
        manifest = _valid_manifest()
        manifest['backup_scope']['artifact_roots'] = []
        manifest['backup_scope']['report_output_dir'] = ''

        issues = provider_service_deployment_errors(manifest)
        codes = {issue.code for issue in issues}

        self.assertIn('empty_artifact_roots', codes)
        self.assertIn('missing_required_field', codes)

    def test_schema_document_matches_validator_contract(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))

        # owner_repository is deliberately not asserted here. It is a lane
        # declaration, and the lane a document belongs to is the extraction
        # manifest's answer — TestDocumentsAgreeWithTheManifestAboutTheirOwner
        # holds document and manifest together for all of them. A literal here
        # would be a third copy of that one fact.
        self.assertIn('service', schema['required_top_level'])
        self.assertEqual(schema['required_provider_environment'], list(REQUIRED_PROVIDER_ENV))
        self.assertIn('secret_redaction_rule', schema)
        self.assertIn('does not install Windows services', schema['notes'])

    def test_module_import_boundary_excludes_runtime_dependencies(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding='utf-8'))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        forbidden_prefixes = (
            'application.reporting',
            'reporting',
            'infrastructure',
            'fastapi',
            'sqlalchemy',
            'pandas',
            'openpyxl',
            'sqlite3',
            'subprocess',
            'shutil',
            'os',
        )
        self.assertFalse([
            module for module in imports
            if module == 'infrastructure' or module.startswith(forbidden_prefixes)
        ])


if __name__ == '__main__':
    unittest.main()
