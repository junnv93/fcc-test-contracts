import ast
import sys
import unittest
from pathlib import Path

project_root = Path(__file__).parent.parent
src_root = project_root / 'src'
sys.path.insert(0, str(src_root))

from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact  # noqa: E402


CONTRACT_MODULE_FILES = [
    resolve_repo_artifact(__file__, 'src/application/headless/api_contracts.py'),
    resolve_repo_artifact(__file__, 'src/application/headless/api_contract_checker.py'),
]

FORBIDDEN_IMPORT_PREFIXES = (
    'infrastructure',
    'database',
    'sqlalchemy',
    'fastapi',
    'pydantic',
    'PySide6',
    'appium',
    'pyvisa',
    'pandas',
)


class TestApiContractExtractionReadiness(unittest.TestCase):
    """Direct-import screening for the two headline contract modules.

    Deliberately narrow, and now explicitly so. This reads the import statements
    of two files; it cannot see a transitive closure, which is how
    ``api_contracts`` → ``api_contract_dtos`` → the Unlicensed generation engine
    stayed green here for months (SPLIT-1, 2026-08-07). The closure is covered
    by ``tests/test_extraction_import_boundaries.py``
    ``::TestContractsLaneImportsStandalone``, which stages the whole lane and
    imports it in a separate interpreter. Keep both: this one names the third
    party bans, that one proves the lane stands up.
    """

    def test_candidate_contract_modules_do_not_import_runtime_dependencies(self):
        for path in CONTRACT_MODULE_FILES:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)

            for imported in imports:
                self.assertFalse(
                    imported.startswith(FORBIDDEN_IMPORT_PREFIXES),
                    f"{path.name} imports forbidden dependency {imported}",
                )

    def test_public_contract_exports_import_without_infrastructure_modules(self):
        existing_infra_modules = {
            name for name in sys.modules
            if name.startswith('infrastructure')
        }

        import fcc_test_contracts.headless.api_contracts as contracts
        import fcc_test_contracts.headless.api_contract_checker as checker

        for name in contracts.__all__:
            self.assertTrue(hasattr(contracts, name), name)
        for name in checker.__all__:
            self.assertTrue(hasattr(checker, name), name)

        loaded_infra_modules = [
            name for name in sys.modules
            if name.startswith('infrastructure') and name not in existing_infra_modules
        ]
        self.assertEqual(loaded_infra_modules, [])

    def test_extraction_plan_lists_candidate_modules_and_backend_responsibilities(self):
        plan = (
            resolve_repo_artifact(__file__, 'docs/api/headless_api_contract_extraction.md')
        ).read_text(encoding='utf-8')

        self.assertIn('application.headless.api_contracts', plan)
        self.assertIn('application.headless.api_contract_checker', plan)
        self.assertIn('src/application/headless/api_contracts.py', plan)
        self.assertIn('src/application/headless/api_contract_checker.py', plan)
        self.assertIn('unlicensed-conducted', plan)
        self.assertIn('mmwave', plan)
        self.assertIn('licensed-conducted', plan)
        self.assertIn('GET /headless/api-contract', plan)


if __name__ == '__main__':
    unittest.main()
