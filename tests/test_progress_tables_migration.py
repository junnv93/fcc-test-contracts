"""P6-B.2 — central progress tables schema + migration parity seal.

The two Phase 6 progress tables (standard_time_catalog, published_plan_expectation)
are central-PG-only (no local SQLite ORM). 001_initial_central_db.sql is
regenerated from central_db_schema.v1.json and only applied on first boot;
004_progress_tables.sql brings already-deployed DBs up additively/idempotently.
This test seals:

- both tables exist in the schema SSOT with their full column set;
- 004 CREATEs exactly those tables, purely additively (CREATE … IF NOT EXISTS,
  no DROP / ALTER of existing objects);
- every table/column/index 004 references exists in the schema SSOT;
- the F1 provider-scoped join index is present;
- 004 applies idempotently on a SQLite shim (re-run safe);
- the progress tables carry NO forbidden (provider-private) columns.
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
MIGRATION_004 = MIGRATIONS / "004_progress_tables.sql"

_PROGRESS_TABLES = ("standard_time_catalog", "published_plan_expectation")

_CATALOG_COLS = {
    "id", "provider_id", "test_type_canonical", "planned_minutes",
    "version", "source", "updated_at", "updated_by",
}
_EXPECTATION_COLS = {
    "id", "project_id", "provider_id", "plan_id", "condition_hash",
    "coverage_technology", "raw_test_type", "test_type_canonical",
    "progress_bucket_id", "progress_area", "planned_minutes_snapshot",
    "catalog_version", "pricing_status", "created_at",
    # P6L-3: read-side latest-wins window key (additive, migration 006).
    "plan_published_at",
}

MIGRATION_006 = MIGRATIONS / "006_progress_plan_published_at.sql"


def _schema():
    return json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))


def _migration_sql():
    return MIGRATION_004.read_text(encoding="utf-8")


class TestSchemaHasProgressTables(unittest.TestCase):
    def setUp(self):
        self.tables = _schema()["tables"]

    def test_both_tables_present(self):
        for name in _PROGRESS_TABLES:
            self.assertIn(name, self.tables, f"{name} missing from schema SSOT")

    def test_catalog_columns(self):
        cols = set(self.tables["standard_time_catalog"]["columns"])
        self.assertEqual(cols, _CATALOG_COLS)

    def test_expectation_columns(self):
        cols = set(self.tables["published_plan_expectation"]["columns"])
        self.assertEqual(cols, _EXPECTATION_COLS)

    def test_planned_minutes_is_numeric(self):
        cat = self.tables["standard_time_catalog"]["columns"]
        self.assertEqual(cat["planned_minutes"]["type"], "numeric")
        self.assertTrue(cat["planned_minutes"]["required"])
        exp = self.tables["published_plan_expectation"]["columns"]
        self.assertEqual(exp["planned_minutes_snapshot"]["type"], "numeric")
        # snapshot is nullable — unpriced conditions carry no minutes
        self.assertFalse(exp["planned_minutes_snapshot"]["required"])

    def test_f1_join_index_present(self):
        idx = {
            i["name"]: i
            for i in self.tables["published_plan_expectation"].get("indexes", [])
        }
        self.assertIn("idx_published_plan_expectation_join", idx)
        self.assertEqual(
            idx["idx_published_plan_expectation_join"]["columns"],
            ["project_id", "provider_id", "condition_hash"],
        )

    def test_natural_key_unique(self):
        idx = {
            i["name"]: i
            for i in self.tables["published_plan_expectation"].get("indexes", [])
        }
        nk = idx["ux_published_plan_expectation_project_provider_plan_condition"]
        self.assertTrue(nk.get("unique"))
        self.assertEqual(
            nk["columns"],
            ["project_id", "provider_id", "plan_id", "condition_hash"],
        )

    def test_measurement_attempts_progress_join_index_present(self):
        idx = {
            i["name"]: i
            for i in self.tables["measurement_attempts"].get("indexes", [])
        }
        self.assertEqual(
            idx["idx_measurement_attempts_progress_join"]["columns"],
            ["project_id", "provider_id", "condition_hash", "is_latest"],
        )

    def test_no_forbidden_provider_columns(self):
        forbidden = set(_schema()["forbidden_platform_columns"])
        for name in _PROGRESS_TABLES:
            cols = set(self.tables[name]["columns"])
            self.assertFalse(forbidden & cols, f"{name} has provider-private column")


class TestMigration004(unittest.TestCase):
    def test_creates_exactly_the_progress_tables(self):
        sql = _migration_sql()
        created = set(
            re.findall(r'CREATE TABLE IF NOT EXISTS "(\w+)"', sql, re.IGNORECASE)
        )
        self.assertEqual(created, set(_PROGRESS_TABLES))

    def test_purely_additive_no_destructive_ddl(self):
        sql = _migration_sql().upper()
        for forbidden in ("DROP TABLE", "DROP COLUMN", "ALTER TABLE", "DELETE FROM", "TRUNCATE"):
            self.assertNotIn(forbidden, sql, f"004 contains destructive {forbidden}")

    def test_indexes_reference_real_columns(self):
        schema = _schema()["tables"]
        sql = _migration_sql()
        for table, cols in re.findall(
            r'INDEX IF NOT EXISTS "\w+" ON "(\w+)" \(([^)]+)\)', sql
        ):
            self.assertIn(table, schema)
            real = set(schema[table]["columns"])
            for col in re.findall(r'"(\w+)"', cols):
                self.assertIn(col, real, f"index col {col} not in {table}")

    def test_idempotent_apply_on_sqlite_shim(self):
        # SQLite shim: translate the PG-only bits so we can apply twice.
        sql = _migration_sql()
        shim = (
            sql.replace("UUID", "TEXT")
            .replace("NUMERIC", "REAL")
            .replace("TIMESTAMPTZ", "TEXT")
        )
        conn = SqliteConnectionFactory(SQLITE_IN_MEMORY_DB).create()
        try:
            # minimal parent tables so the REFERENCES + the additive
            # measurement_attempts progress-join index resolve under FK-on
            conn.executescript(
                'CREATE TABLE "providers" ("id" TEXT PRIMARY KEY);'
                'CREATE TABLE "projects" ("id" TEXT PRIMARY KEY);'
                'CREATE TABLE "measurement_attempts" ("id" TEXT PRIMARY KEY, '
                '"project_id" TEXT, "provider_id" TEXT, "condition_hash" TEXT, '
                '"is_latest" INTEGER);'
            )
            conn.executescript(shim)
            conn.executescript(shim)  # re-run: IF NOT EXISTS → no error
            names = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for t in _PROGRESS_TABLES:
                self.assertIn(t, names)
        finally:
            conn.close()


class TestMigration006PlanPublishedAt(unittest.TestCase):
    """P6L-3 read-side latest-wins window key (plan_published_at, additive)."""

    def _sql(self):
        return MIGRATION_006.read_text(encoding="utf-8")

    def test_column_in_schema_ssot(self):
        cols = _schema()["tables"]["published_plan_expectation"]["columns"]
        self.assertIn("plan_published_at", cols)
        # nullable — pre-P6L-3 rows + NULL-publish plans sort oldest in the window
        self.assertFalse(cols["plan_published_at"]["required"])

    def test_adds_only_the_window_column_idempotently(self):
        sql = self._sql()
        self.assertIn("published_plan_expectation", sql)
        self.assertRegex(sql, r"ADD COLUMN IF NOT EXISTS\s+\"plan_published_at\"")
        # additive only — no destructive DDL on the existing table
        upper = sql.upper()
        for forbidden in ("DROP TABLE", "DROP COLUMN", "DELETE FROM", "TRUNCATE"):
            self.assertNotIn(forbidden, upper, f"006 contains destructive {forbidden}")

    def test_idempotent_apply_on_sqlite_shim(self):
        # SQLite lacks ADD COLUMN IF NOT EXISTS, so shim it to plain ADD COLUMN and
        # apply once on a table seeded WITHOUT the column (proves the ALTER targets a
        # real, additive column). Re-running PG's IF NOT EXISTS is a no-op by spec.
        shim = self._sql().replace(
            'ADD COLUMN IF NOT EXISTS "plan_published_at" TIMESTAMPTZ',
            'ADD COLUMN "plan_published_at" TEXT',
        )
        conn = SqliteConnectionFactory(SQLITE_IN_MEMORY_DB).create()
        try:
            conn.execute(
                'CREATE TABLE "published_plan_expectation" '
                '("id" TEXT PRIMARY KEY, "created_at" TEXT)'
            )
            conn.executescript(shim)
            cols = {
                r[1]
                for r in conn.execute(
                    'PRAGMA table_info("published_plan_expectation")'
                )
            }
            self.assertIn("plan_published_at", cols)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
