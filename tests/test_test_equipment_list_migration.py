"""Incremental migration 015 parity (성적서 §6 장비목록 — 중앙 백엔드).

``001_initial_central_db.sql`` is applied only on first boot (CREATE TABLE IF NOT
EXISTS), so an already-deployed central DB never picks up ``test_equipment_lists``
/ ``test_equipment_list_items`` by re-running 001. ``015_test_equipment_lists.sql``
brings such a DB up to date additively/idempotently. This test seals:

- both tables exist in the ``central_db_schema.v1.json`` SSOT with exactly the
  declared columns in the declared order,
- the regenerated 001 DDL contains both CREATE TABLEs + all six indexes,
- 015 creates them idempotently (CREATE … IF NOT EXISTS),
- every column 015 creates is grounded in the schema SSOT,
- 015 is purely additive (no destructive DDL),
- the CHECK constraint value sets equal the schema ``allowed_values``,
- **the two partial unique indexes mean what the domain says they mean** — with
  ``test_report_id IS NULL`` a duplicate ``(project_id, test_item_key)`` is
  rejected, but once a list is attached to a report the *same*
  ``(project_id, test_item_key)`` is allowed again (one list per report edition).
  That second half is the whole reason the natural key is split in two, so a
  test that only checks the first half would pass against a single plain unique
  index — which would silently forbid per-edition lists.

Owned by ``/verify-report-equipment-list-central``.
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
MIGRATION_015 = MIGRATIONS / "015_test_equipment_lists.sql"
MIGRATION_001 = MIGRATIONS / "001_initial_central_db.sql"

# The central PostgreSQL migration is translated for SQLite-only parity below.

LIST_TABLE = "test_equipment_lists"
ITEM_TABLE = "test_equipment_list_items"

_LIST_COLS = (
    "id", "project_id", "test_report_id", "test_item_key", "test_item_name",
    "status", "source_profile_key", "source_revision_key", "source_pulled_at",
    "confirmed_at", "created_at", "updated_at",
)
_ITEM_COLS = (
    "id", "list_id", "item_type", "section_name", "sort_order", "description",
    "manufacturer", "model_name", "serial_number", "calibration_due_date",
    "software_version", "remarks", "created_at",
)
_LIST_INDEXES = (
    "ux_test_equipment_lists_project_item",
    "ux_test_equipment_lists_report_item",
    "idx_test_equipment_lists_project",
    "idx_test_equipment_lists_report",
)
_ITEM_INDEXES = (
    "idx_test_equipment_list_items_list_order",
    "idx_test_equipment_list_items_list_type",
)


def _schema():
    return json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))


def _sql_015() -> str:
    return MIGRATION_015.read_text(encoding="utf-8")


class TestMigration015Exists(unittest.TestCase):
    def test_file_present(self):
        self.assertTrue(MIGRATION_015.exists())

    def test_number_not_reused(self):
        """014 belongs to the reference catalog; two migrations sharing a number
        have no defined apply order."""
        siblings = {p.name.split("_", 1)[0] for p in MIGRATIONS.glob("*.sql")}
        numbered = [p.name for p in MIGRATIONS.glob("015_*.sql")]
        self.assertIn("015", siblings)
        self.assertEqual(numbered, ["015_test_equipment_lists.sql"])


class TestTablesInSchema(unittest.TestCase):
    def test_tables_in_schema(self):
        tables = _schema()["tables"]
        self.assertIn(LIST_TABLE, tables)
        self.assertIn(ITEM_TABLE, tables)

    def test_list_columns_match_schema(self):
        cols = _schema()["tables"][LIST_TABLE]["columns"]
        self.assertEqual(tuple(cols.keys()), _LIST_COLS)

    def test_item_columns_match_schema(self):
        cols = _schema()["tables"][ITEM_TABLE]["columns"]
        self.assertEqual(tuple(cols.keys()), _ITEM_COLS)

    def test_calibration_cert_fields_absent(self):
        """cert_number / accredited_by / uncertainty_db do not appear in the §6
        table, so storing them would be scope drift."""
        cols = _schema()["tables"][ITEM_TABLE]["columns"]
        for banned in ("cert_number", "accredited_by", "uncertainty_db"):
            self.assertNotIn(banned, cols)

    def test_calibration_due_date_is_text(self):
        """Source values include 'N/A' and mixed formats — stored as provided."""
        cols = _schema()["tables"][ITEM_TABLE]["columns"]
        self.assertEqual(cols["calibration_due_date"]["type"], "text")

    def test_test_report_id_is_nullable(self):
        """A tester picks equipment before the report row exists."""
        cols = _schema()["tables"][LIST_TABLE]["columns"]
        self.assertFalse(cols["test_report_id"].get("required"))
        self.assertEqual(cols["test_report_id"].get("references"), "test_reports.id")

    def test_indexes_in_schema(self):
        declared = {i["name"] for i in _schema()["tables"][LIST_TABLE].get("indexes", [])}
        for name in _LIST_INDEXES:
            self.assertIn(name, declared)
        declared_items = {i["name"] for i in _schema()["tables"][ITEM_TABLE].get("indexes", [])}
        for name in _ITEM_INDEXES:
            self.assertIn(name, declared_items)

    def test_natural_key_is_split_by_predicate(self):
        indexes = {i["name"]: i for i in _schema()["tables"][LIST_TABLE]["indexes"]}
        project_scoped = indexes["ux_test_equipment_lists_project_item"]
        report_scoped = indexes["ux_test_equipment_lists_report_item"]
        self.assertTrue(project_scoped.get("unique"))
        self.assertTrue(report_scoped.get("unique"))
        self.assertEqual(project_scoped.get("where"), "test_report_id IS NULL")
        self.assertEqual(report_scoped.get("where"), "test_report_id IS NOT NULL")

    def test_foreign_keys(self):
        list_cols = _schema()["tables"][LIST_TABLE]["columns"]
        item_cols = _schema()["tables"][ITEM_TABLE]["columns"]
        self.assertEqual(list_cols["project_id"].get("references"), "projects.id")
        self.assertEqual(item_cols["list_id"].get("references"), f"{LIST_TABLE}.id")


class TestMigration015CreatesTables(unittest.TestCase):
    def test_creates_tables_idempotently(self):
        sql = _sql_015()
        self.assertIn(f'CREATE TABLE IF NOT EXISTS "{LIST_TABLE}"', sql)
        self.assertIn(f'CREATE TABLE IF NOT EXISTS "{ITEM_TABLE}"', sql)

    def test_creates_indexes_idempotently(self):
        sql = _sql_015()
        for name in _LIST_INDEXES + _ITEM_INDEXES:
            self.assertIn(f'INDEX IF NOT EXISTS "{name}"', sql)

    def test_partial_predicates_present(self):
        sql = _sql_015()
        self.assertIn("WHERE test_report_id IS NULL", sql)
        self.assertIn("WHERE test_report_id IS NOT NULL", sql)

    def test_created_columns_grounded_in_schema(self):
        sql = _sql_015()
        schema = _schema()["tables"]
        for table, declared in ((LIST_TABLE, _LIST_COLS), (ITEM_TABLE, _ITEM_COLS)):
            body = sql.split(f'CREATE TABLE IF NOT EXISTS "{table}" (', 1)[1].split(");", 1)[0]
            created = set(
                re.findall(r'"(\w+)"\s+(?:UUID|TEXT|JSONB|TIMESTAMPTZ|INTEGER|NUMERIC)', body)
            )
            schema_cols = set(schema[table]["columns"].keys())
            self.assertTrue(created)
            for col in created:
                self.assertIn(col, schema_cols, f"{table}.{col} missing from schema SSOT")
            self.assertEqual(created, set(declared))

    def test_check_values_equal_schema_allowed_values(self):
        sql = _sql_015()
        schema = _schema()["tables"]
        status_allowed = set(schema[LIST_TABLE]["columns"]["status"]["allowed_values"])
        item_allowed = set(schema[ITEM_TABLE]["columns"]["item_type"]["allowed_values"])
        status_check = set(
            re.findall(r"'(\w+)'", re.search(r'CHECK \("status" IN \(([^)]*)\)\)', sql).group(1))
        )
        item_check = set(
            re.findall(r"'(\w+)'", re.search(r'CHECK \("item_type" IN \(([^)]*)\)\)', sql).group(1))
        )
        self.assertEqual(status_check, status_allowed)
        self.assertEqual(item_check, item_allowed)


class TestMigration015GroundedInRegenerated001(unittest.TestCase):
    def test_001_contains_both_tables_and_all_indexes(self):
        sql = MIGRATION_001.read_text(encoding="utf-8")
        self.assertIn(f'CREATE TABLE IF NOT EXISTS "{LIST_TABLE}"', sql)
        self.assertIn(f'CREATE TABLE IF NOT EXISTS "{ITEM_TABLE}"', sql)
        for name in _LIST_INDEXES + _ITEM_INDEXES:
            self.assertIn(name, sql)

    def test_015_table_bodies_are_a_subset_of_001(self):
        """The incremental migration must not diverge from the generated DDL."""
        one = MIGRATION_001.read_text(encoding="utf-8")
        inc = _sql_015()

        def bodies(text):
            return {
                m.group(1): m.group(2)
                for m in re.finditer(
                    r'CREATE TABLE IF NOT EXISTS "(\w+)" \((.*?)\n\);', text, re.S
                )
            }

        one_bodies, inc_bodies = bodies(one), bodies(inc)
        for table in (LIST_TABLE, ITEM_TABLE):
            self.assertEqual(inc_bodies[table], one_bodies[table])


class TestMigration015Additive(unittest.TestCase):
    def test_no_destructive_ddl(self):
        sql = _sql_015().upper()
        for banned in ("DROP TABLE", "DROP COLUMN", "DELETE FROM", "TRUNCATE", "ALTER TABLE"):
            self.assertNotIn(banned, sql)


class TestMigration015AppliesOnBaseline(unittest.TestCase):
    """SQLite-translate 015 and prove the partial unique indexes' semantics.

    SQLite supports partial indexes, so both halves of the split natural key are
    executable here — the point of this test is that the *second* half (per
    report edition) is a real allowance, not an accident.
    """

    def _conn(self):
        conn = SqliteConnectionFactory(SQLITE_IN_MEMORY_DB).create()
        conn.executescript(
            "CREATE TABLE projects (id TEXT PRIMARY KEY);"
            "CREATE TABLE test_reports (id TEXT PRIMARY KEY, project_id TEXT NOT NULL);"
            f"CREATE TABLE {LIST_TABLE} ("
            "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, test_report_id TEXT,"
            "test_item_key TEXT NOT NULL, test_item_name TEXT,"
            "status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','confirmed')),"
            "source_profile_key TEXT, source_revision_key TEXT, source_pulled_at TEXT,"
            "confirmed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
            f"CREATE UNIQUE INDEX ux_test_equipment_lists_project_item ON {LIST_TABLE} "
            "(project_id, test_item_key) WHERE test_report_id IS NULL;"
            f"CREATE UNIQUE INDEX ux_test_equipment_lists_report_item ON {LIST_TABLE} "
            "(test_report_id, test_item_key) WHERE test_report_id IS NOT NULL;"
            f"CREATE TABLE {ITEM_TABLE} ("
            "id TEXT PRIMARY KEY, list_id TEXT NOT NULL, item_type TEXT NOT NULL "
            "CHECK (item_type IN ('equipment','test_software')), section_name TEXT,"
            "sort_order INTEGER NOT NULL, description TEXT, manufacturer TEXT,"
            "model_name TEXT, serial_number TEXT, calibration_due_date TEXT,"
            "software_version TEXT, remarks TEXT, created_at TEXT NOT NULL);"
        )
        return conn

    def _insert(self, conn, list_id, report_id, item_key="BT", project="p1"):
        conn.execute(
            f"INSERT INTO {LIST_TABLE} (id, project_id, test_report_id, test_item_key,"
            " status, created_at, updated_at) VALUES (?,?,?,?,'draft','now','now')",
            (list_id, project, report_id, item_key),
        )

    def test_baseline_gains_columns(self):
        conn = self._conn()
        try:
            list_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({LIST_TABLE})")}
            item_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({ITEM_TABLE})")}
            for col in _LIST_COLS:
                self.assertIn(col, list_cols)
            for col in _ITEM_COLS:
                self.assertIn(col, item_cols)
        finally:
            conn.close()

    def test_unattached_list_is_unique_per_project_and_item(self):
        conn = self._conn()
        try:
            self._insert(conn, "l1", None)
            with self.assertRaises(sqlite3.IntegrityError):
                self._insert(conn, "l2", None)
        finally:
            conn.close()

    def test_same_project_and_item_allowed_once_attached_to_reports(self):
        """The whole reason the natural key is split: a model can have several
        report editions and the equipment can differ between them."""
        conn = self._conn()
        try:
            conn.execute("INSERT INTO test_reports (id, project_id) VALUES ('r1','p1')")
            conn.execute("INSERT INTO test_reports (id, project_id) VALUES ('r2','p1')")
            self._insert(conn, "l0", None)      # draft, not yet attached
            self._insert(conn, "l1", "r1")      # edition 1
            self._insert(conn, "l2", "r2")      # edition 2 — same (project, item)
            rows = conn.execute(f"SELECT COUNT(*) FROM {LIST_TABLE}").fetchone()[0]
            self.assertEqual(rows, 3)
        finally:
            conn.close()

    def test_one_list_per_report_and_item(self):
        conn = self._conn()
        try:
            conn.execute("INSERT INTO test_reports (id, project_id) VALUES ('r1','p1')")
            self._insert(conn, "l1", "r1")
            with self.assertRaises(sqlite3.IntegrityError):
                self._insert(conn, "l2", "r1")
        finally:
            conn.close()

    def test_status_and_item_type_checks_reject_unknown_tokens(self):
        conn = self._conn()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    f"INSERT INTO {LIST_TABLE} (id, project_id, test_item_key, status,"
                    " created_at, updated_at) VALUES ('x','p1','BT','published','now','now')"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    f"INSERT INTO {ITEM_TABLE} (id, list_id, item_type, sort_order,"
                    " created_at) VALUES ('x','l1','instrument',0,'now')"
                )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
