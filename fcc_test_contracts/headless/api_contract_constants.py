"""Headless contract surface — api contract constants."""
from __future__ import annotations



API_CONTRACT_VERSION = '1.0.0'


API_COMPATIBILITY_MAJOR = 1


# OOXML spreadsheet media type. Declared here so the contract table and the route
# read the SAME string — a download whose OpenAPI says ``octet-stream`` while the
# wire says xlsx is a contract that lies, and nothing catches it because the two
# sides each spelled their own literal (that is exactly what happened to
# ``export_test_plan_draft`` between 2026-06-24 and 2026-08-11).
XLSX_MEDIA_TYPE = (
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
)


# Default HTTP page cap for the attempt-history read (FE-P4 review C-1 +
# FE-P4-PAGE keyset). A single session can accumulate tens of thousands of
# attempts; the API caps the page so a request cannot materialize the whole
# table. Contract SSOT — the route imports this (no duplicated literal).
# Internal (non-HTTP) callers pass limit=None for the uncapped read.
DEFAULT_ATTEMPTS_PAGE_LIMIT = 500


# Hard upper bound clamped at the HTTP boundary (P2, 2026-05-29) so a malicious
# or mistaken ``?limit=`` cannot force an oversized page (memory pressure /
# unbounded materialization). Route clamps to [1, MAX]; OpenAPI documents it.
MAX_ATTEMPTS_PAGE_LIMIT = 2000


# Hard upper bound for the published-plan list page (G2, 2026-06-16). The route
# leaves ``?limit`` optional (omitted = all publications for the project, ordered
# newest-first — publications-per-project is bounded), but clamps a supplied
# ``?limit`` to [1, MAX] so a mistaken/abusive value cannot force an oversized
# materialization. Contract SSOT — the route imports this (no duplicated literal).
MAX_PUBLISHED_PLANS_PAGE_LIMIT = 1000


DEFAULT_PROVIDER_METADATA = {
    'provider_id': 'fcc-unlicensed-conducted',
    'product_line': 'unlicensed-conducted',
    'contract_family': 'fcc-conducted-headless',
}


# Permission token → human-readable description (FE-P1 SSOT, 2026-05-25).
# Co-located with HEADLESS_API_PERMISSIONS so adding a new permission forces a
# description entry — invariant ``test_permission_descriptions_cover_every_token``
# fails the build if any used permission lacks an explanation.
HEADLESS_API_PERMISSION_DESCRIPTIONS: dict[str, str] = {
    'public': 'No authorization required — health/contract discovery endpoints.',
    'headless:read': 'Read headless status, jobs, results, artifacts.',
    'headless:control': 'Submit/stop measurement jobs (write surface).',
    'report_automation:read': 'Read report-automation queue stats + request/outputs.',
    'report_automation:control': 'Submit/cancel report-automation requests.',
    'test_plan:read': 'Read/validate test-plan drafts (non-mutating).',
    'test_plan:author': 'Create drafts, add/remove draft rows, import a test-plan from an Excel workbook (draft authoring write surface).',
}


# Path parameter → JSON Schema SSOT (FE-P1, 2026-05-25). Every ``{name}`` token
# appearing in ``HEADLESS_API_ROUTES`` MUST have an entry here. The OpenAPI
# builder consults this table instead of an ``endswith('_id')`` heuristic so a
# future non-integer path param cannot silently get the wrong type. Schema
# fragments are JSON-Schema 2020-12 compatible (OpenAPI 3.1 component reuse).
HEADLESS_API_PATH_PARAMS: dict[str, dict] = {
    'job_id': {'type': 'integer', 'minimum': 1},
    'session_id': {'type': 'integer', 'minimum': 1},
    'request_id': {'type': 'integer', 'minimum': 1},
    # Test-plan draft path params (IMPL-1, 2026-06-03). project_id/draft_id are
    # opaque strings (not the integer DB ids the other routes use); draft_row_id
    # is the stable AUTOINCREMENT handle (test_plan_draft_rows.id).
    'project_id': {'type': 'string', 'minLength': 1},
    'draft_id': {'type': 'string', 'minLength': 1},
    'draft_row_id': {'type': 'integer', 'minimum': 1},
    'generation_job_id': {'type': 'string', 'minLength': 1},
}
