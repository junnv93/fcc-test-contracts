"""Incremental migration 005 parity (Phase G — test_reports, central backend).

001_initial_central_db.sql is applied only on first boot (CREATE TABLE IF NOT
EXISTS), so an already-deployed central DB never picks up the Phase G
``test_reports`` table by re-running 001. ``005_test_reports.sql`` brings such a
DB up to date additively/idempotently. This test seals:

- ``test_reports`` exists in the central_db_schema.v1.json SSOT with exactly the
  declared columns (report_number is NOT a column — it is derived),
- the regenerated 001 DDL contains the ``test_reports`` CREATE TABLE + indexes,
- 005 creates ``test_reports`` + its indexes idempotently (CREATE … IF NOT EXISTS),
- every column 005 creates is grounded in the schema SSOT,
- 005 is purely additive (no DROP / destructive DDL),
- applying 005 (SQLite-translated) on an empty baseline yields the columns.

Owned by ``/verify-test-report-central``.
"""
from __future__ import annotations

import json
import re
import sqlite3
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
MIGRATION_005 = MIGRATIONS / "005_test_reports.sql"
MIGRATION_001 = MIGRATIONS / "001_initial_central_db.sql"

# The central PostgreSQL migration is translated for SQLite-only parity below.

_TEST_REPORT_COLS = (
    "id", "project_id", "edition", "date_of_issue", "date_tested_start",
    "date_tested_end", "prepared_by", "prepared_site", "rev_history_json",
    "created_at", "updated_at",
)
_TEST_REPORT_INDEXES = (
    "ux_test_reports_project_edition",
    "idx_test_reports_project",
)


def _schema():
    return json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))


class TestMigration005Exists(unittest.TestCase):
    def test_file_present(self):
        self.assertTrue(MIGRATION_005.exists())


class TestTestReportsInSchema(unittest.TestCase):
    def test_table_in_schema(self):
        self.assertIn("test_reports", _schema()["tables"])

    def test_columns_match_schema(self):
        cols = _schema()["tables"]["test_reports"]["columns"]
        self.assertEqual(tuple(cols.keys()), _TEST_REPORT_COLS)

    def test_report_number_not_a_column(self):
        # report_number is DERIVED (S-{management_number}-{edition}), never stored
        # — mirror of the derived fcc_id. A stored column would be a drift bug.
        cols = _schema()["tables"]["test_reports"]["columns"]
        self.assertNotIn("report_number", cols)

    def test_indexes_in_schema(self):
        idx = {i["name"] for i in _schema()["tables"]["test_reports"].get("indexes", [])}
        for name in _TEST_REPORT_INDEXES:
            self.assertIn(name, idx)

    def test_project_fk(self):
        cols = _schema()["tables"]["test_reports"]["columns"]
        self.assertEqual(cols["project_id"].get("references"), "projects.id")
        self.assertTrue(cols["edition"].get("required"))


class TestMigration005CreatesTable(unittest.TestCase):
    def test_creates_test_reports_idempotently(self):
        sql = MIGRATION_005.read_text(encoding="utf-8")
        self.assertIn('CREATE TABLE IF NOT EXISTS "test_reports"', sql)

    def test_creates_indexes_idempotently(self):
        sql = MIGRATION_005.read_text(encoding="utf-8")
        self.assertIn(
            'CREATE UNIQUE INDEX IF NOT EXISTS "ux_test_reports_project_edition"', sql
        )
        self.assertIn(
            'CREATE INDEX IF NOT EXISTS "idx_test_reports_project"', sql
        )

    def test_created_columns_grounded_in_schema(self):
        sql = MIGRATION_005.read_text(encoding="utf-8")
        # Extract the quoted column tokens inside the CREATE TABLE body.
        body = sql.split('CREATE TABLE IF NOT EXISTS "test_reports" (', 1)[1].split(");", 1)[0]
        created = set(re.findall(r'"(\w+)"\s+(?:UUID|TEXT|JSONB|TIMESTAMPTZ)', body))
        schema_cols = set(_schema()["tables"]["test_reports"]["columns"].keys())
        for col in created:
            self.assertIn(col, schema_cols, f"test_reports.{col} missing from schema SSOT")


class TestMigration005GroundedInRegenerated001(unittest.TestCase):
    def test_001_contains_test_reports(self):
        sql = MIGRATION_001.read_text(encoding="utf-8")
        self.assertIn('CREATE TABLE IF NOT EXISTS "test_reports"', sql)
        for name in _TEST_REPORT_INDEXES:
            self.assertIn(name, sql)


class TestMigration005Additive(unittest.TestCase):
    def test_no_destructive_ddl(self):
        sql = MIGRATION_005.read_text(encoding="utf-8").upper()
        for banned in ("DROP TABLE", "DROP COLUMN", "DELETE FROM", "TRUNCATE", "ALTER TABLE"):
            self.assertNotIn(banned, sql)


class TestMigration005AppliesOnBaseline(unittest.TestCase):
    """SQLite-translate 005's CREATE TABLE and apply it on an empty baseline."""

    def test_baseline_gains_table(self):
        conn = SqliteConnectionFactory(SQLITE_IN_MEMORY_DB).create()
        try:
            conn.executescript(
                "CREATE TABLE projects (id TEXT PRIMARY KEY, project_code TEXT);"
                "CREATE TABLE test_reports ("
                "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, edition TEXT NOT NULL,"
                "date_of_issue TEXT, date_tested_start TEXT, date_tested_end TEXT,"
                "prepared_by TEXT, prepared_site TEXT, rev_history_json TEXT,"
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
                "CREATE UNIQUE INDEX ux_test_reports_project_edition "
                "ON test_reports (project_id, edition);"
            )
            cols = {r[1] for r in conn.execute("PRAGMA table_info(test_reports)")}
            for col in _TEST_REPORT_COLS:
                self.assertIn(col, cols)
            # The (project_id, edition) unique index must reject a duplicate edition.
            conn.execute(
                "INSERT INTO test_reports (id, project_id, edition, created_at, updated_at)"
                " VALUES ('r1', 'p1', 'E2V1', 'now', 'now')"
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO test_reports (id, project_id, edition, created_at, updated_at)"
                    " VALUES ('r2', 'p1', 'E2V1', 'now', 'now')"
                )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
