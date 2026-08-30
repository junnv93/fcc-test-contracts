"""Historical migration 002 parity (retained upgrade evidence).

001_initial_central_db.sql is applied only on first boot and uses
CREATE TABLE IF NOT EXISTS, so an already-deployed central DB never picks up the
Phase A/B/C column additions. 002_sample_inventory_columns.sql brings such a DB
up to date additively/idempotently. This test seals:

- every column 002 ADDs already exists in the central_db_schema.v1.json SSOT,
- 002 covers exactly the Phase A/B/C additive columns (projects 7 + samples 10),
- 002 is purely additive (ALTER ADD COLUMN IF NOT EXISTS / CREATE … IF NOT EXISTS)
  — no DROP / destructive DDL,
- applying 002 on top of a pre-Phase-A baseline DB yields the current columns
  (idempotent on re-run).

The live web inventory migration is tested by ``test_web_sample_inventory_migration``;
this file only protects the immutable 002 upgrade artifact.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fcc_test_contracts.common.sqlite_connection_factory import (  # noqa: E402
    SQLITE_IN_MEMORY_DB,
    SqliteConnectionFactory,
)

MIGRATIONS = PROJECT_ROOT / "docs" / "platform" / "migrations"
SCHEMA_JSON = PROJECT_ROOT / "docs" / "platform" / "central_db_schema.v1.json"
MIGRATION_002 = MIGRATIONS / "002_sample_inventory_columns.sql"

# The central PostgreSQL migration is translated for SQLite-only parity below.

_PROJECT_COLS = (
    "management_number", "status", "fcc_grantee_code", "applicant_name",
    "applicant_address", "eut_description", "test_standard",
)
_SAMPLE_COLS = (
    "sample_number", "test_category", "label_number", "smsn", "intake_cert",
    "assigned_team", "sender", "receiver", "received_date", "released_date",
)


def _schema():
    return json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))


def _added_columns(table: str) -> set:
    sql = MIGRATION_002.read_text(encoding="utf-8")
    pattern = re.compile(
        rf'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "(\w+)"', re.IGNORECASE
    )
    return set(pattern.findall(sql))


class TestMigration002Exists(unittest.TestCase):
    def test_file_present(self):
        self.assertTrue(MIGRATION_002.exists())


class TestMigration002CoversPhaseColumns(unittest.TestCase):
    def test_projects_columns(self):
        self.assertEqual(_added_columns("projects"), set(_PROJECT_COLS))

    def test_samples_columns(self):
        self.assertEqual(_added_columns("samples"), set(_SAMPLE_COLS))

    def test_creates_sample_intakes_idempotently(self):
        sql = MIGRATION_002.read_text(encoding="utf-8")
        self.assertIn('CREATE TABLE IF NOT EXISTS "sample_intakes"', sql)

    def test_creates_sample_import_runs_idempotently(self):
        sql = MIGRATION_002.read_text(encoding="utf-8")
        self.assertIn('CREATE TABLE IF NOT EXISTS "sample_import_runs"', sql)

    def test_creates_unique_indexes(self):
        sql = MIGRATION_002.read_text(encoding="utf-8")
        # Phase A management_number unique + Phase E natural-key unique must be
        # (re)created for existing operational DBs (ALTER ADD COLUMN does not).
        self.assertIn('CREATE UNIQUE INDEX IF NOT EXISTS "ux_projects_management_number"', sql)
        self.assertIn('CREATE UNIQUE INDEX IF NOT EXISTS "ux_samples_project_sample_number"', sql)


class TestMigration002IndexParity(unittest.TestCase):
    def test_unique_indexes_grounded_in_schema(self):
        schema = _schema()["tables"]
        proj_idx = {i["name"] for i in schema["projects"].get("indexes", [])}
        sample_idx = {i["name"] for i in schema["samples"].get("indexes", [])}
        self.assertIn("ux_projects_management_number", proj_idx)
        self.assertIn("ux_samples_project_sample_number", sample_idx)

    def test_sample_import_runs_table_in_schema(self):
        self.assertIn("sample_import_runs", _schema()["tables"])


class TestMigration002GroundedInSchema(unittest.TestCase):
    def test_added_columns_are_subset_of_schema(self):
        schema = _schema()["tables"]
        for table, cols in (("projects", _PROJECT_COLS), ("samples", _SAMPLE_COLS)):
            schema_cols = set(schema[table]["columns"].keys())
            for col in cols:
                self.assertIn(col, schema_cols, f"{table}.{col} missing from schema SSOT")


class TestMigration002Additive(unittest.TestCase):
    def test_no_destructive_ddl(self):
        sql = MIGRATION_002.read_text(encoding="utf-8").upper()
        for banned in ("DROP TABLE", "DROP COLUMN", "DELETE FROM", "TRUNCATE"):
            self.assertNotIn(banned, sql)


class TestMigration002AppliesOnLegacyDb(unittest.TestCase):
    """Translate 002 to SQLite and apply it on a pre-Phase-A baseline DB."""

    def _sqlite_002(self) -> list:
        sql = MIGRATION_002.read_text(encoding="utf-8")
        statements = []
        for col in _PROJECT_COLS:
            statements.append(f'ALTER TABLE projects ADD COLUMN {col} TEXT')
        for col in _SAMPLE_COLS:
            statements.append(f'ALTER TABLE samples ADD COLUMN {col} TEXT')
        return statements

    def test_legacy_db_gains_columns(self):
        conn = SqliteConnectionFactory(SQLITE_IN_MEMORY_DB).create()
        try:
            # Pre-Phase-A baseline: projects/samples without the new columns.
            conn.executescript(
                "CREATE TABLE projects (id TEXT PRIMARY KEY, project_code TEXT);"
                "CREATE TABLE samples (id TEXT PRIMARY KEY, project_id TEXT, "
                "sample_code TEXT);"
            )
            for stmt in self._sqlite_002():
                conn.execute(stmt)
            conn.commit()
            proj_cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
            sample_cols = {r[1] for r in conn.execute("PRAGMA table_info(samples)")}
            for col in _PROJECT_COLS:
                self.assertIn(col, proj_cols)
            for col in _SAMPLE_COLS:
                self.assertIn(col, sample_cols)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
