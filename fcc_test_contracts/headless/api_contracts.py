"""Shared headless API contracts — compatibility facade / SSOT entry point.

These DTOs are dependency-free on purpose. They can move to a future shared
contracts package without pulling FastAPI, Pydantic, SQLite, or hardware code
with them.

**This module assembles; it declares nothing.** Each operation's route,
permission, contract entry, schemas and DTOs live together in the surface module
its path names (``surface_*.py``), and ``api_contract_surfaces`` unions those
tables. The boundary is not a matter of taste — it was measured from this
surface's own history, where the previous split (one module per KIND of table)
kept only 38% of feature commits inside a single file while this one keeps 86%,
and the median commit fell from three files to one. The measurement, its
calibration against a surface whose answer was already known, and the finer
partition it REJECTED are in ``.claude/evaluations/headless-contract-axis.md``;
re-run it with ``scripts/measure_contract_decomposition_axis.py``.

Callers are unaffected: every name below resolves exactly as before, so
``from application.headless.api_contracts import ...`` needs no edit.
"""
from __future__ import annotations

from fcc_test_contracts.headless.api_contract_constants import (
    API_COMPATIBILITY_MAJOR,
    API_CONTRACT_VERSION,
    DEFAULT_ATTEMPTS_PAGE_LIMIT,
    DEFAULT_PROVIDER_METADATA,
    HEADLESS_API_PATH_PARAMS,
    HEADLESS_API_PERMISSION_DESCRIPTIONS,
    MAX_ATTEMPTS_PAGE_LIMIT,
    MAX_PUBLISHED_PLANS_PAGE_LIMIT,
)
from fcc_test_contracts.headless.api_contract_primitives import (
    ApiContractError,
    require_object,
)
from fcc_test_contracts.headless.api_contract_snapshot import (
    ApiContractSnapshot,
)
from fcc_test_contracts.headless.api_contract_features import (
    CORE_FEATURE_IDS,
    FEATURE_IDS,
    feature_operations,
)
from fcc_test_contracts.headless.api_contract_surfaces import (
    HEADLESS_API_FEATURES,
    HEADLESS_API_OPERATIONS,
    HEADLESS_API_PERMISSIONS,
    HEADLESS_API_ROUTES,
    HEADLESS_API_SCHEMAS,
)
from fcc_test_contracts.headless.surface_jobs import (
    MeasurementJobSubmitted,
    StopMeasurementJobRequest,
    StopMeasurementJobResponse,
    SubmitMeasurementJobRequest,
)
from fcc_test_contracts.headless.surface_meta import (
    HealthCheckResponse,
)
from fcc_test_contracts.headless.surface_provider import (
    ProviderCapabilitiesResponse,
)
from fcc_test_contracts.headless.surface_reports import (
    CancelReportAutomationRequest,
    CancelReportAutomationResponse,
    CreateReportOutputDownloadRequest,
    ReportOutputDownloadGrant,
    ReportOutputMetadata,
)
from fcc_test_contracts.headless.surface_sessions import (
    ReportRequestSubmitted,
    SubmitReportRequest,
)
from fcc_test_contracts.headless.surface_test_plan import (
    AddTestPlanDraftRowRequest,
    CreateTestPlanDraftRequest,
    ListPublishedTestPlansResponse,
    ListTestPlanDraftsResponse,
    PublishedTestPlanRowView,
    PublishedTestPlanSummaryView,
    PublishedTestPlanView,
    RemoveTestPlanDraftRowResponse,
    ReplaceTestPlanDraftRowsRequest,
    ReplaceTestPlanDraftRowsResponse,
    TestPlanDraftRowView,
    TestPlanDraftSummaryView,
    TestPlanDraftView,
    TestPlanImportResponse,
    ValidateTestPlanDraftResponse,
    ValidationIssueView,
)


__all__ = [
    'API_COMPATIBILITY_MAJOR',
    'API_CONTRACT_VERSION',
    'DEFAULT_ATTEMPTS_PAGE_LIMIT',
    'MAX_ATTEMPTS_PAGE_LIMIT',
    'MAX_PUBLISHED_PLANS_PAGE_LIMIT',
    'DEFAULT_PROVIDER_METADATA',
    'CORE_FEATURE_IDS',
    'FEATURE_IDS',
    'HEADLESS_API_FEATURES',
    'HEADLESS_API_OPERATIONS',
    'HEADLESS_API_PATH_PARAMS',
    'HEADLESS_API_PERMISSIONS',
    'HEADLESS_API_PERMISSION_DESCRIPTIONS',
    'HEADLESS_API_ROUTES',
    'HEADLESS_API_SCHEMAS',
    'ApiContractError',
    'ApiContractSnapshot',
    'AddTestPlanDraftRowRequest',
    'CancelReportAutomationRequest',
    'CancelReportAutomationResponse',
    'CreateReportOutputDownloadRequest',
    'CreateTestPlanDraftRequest',
    'ReportOutputDownloadGrant',
    'HealthCheckResponse',
    'ListPublishedTestPlansResponse',
    'ListTestPlanDraftsResponse',
    'ProviderCapabilitiesResponse',
    'PublishedTestPlanRowView',
    'PublishedTestPlanSummaryView',
    'PublishedTestPlanView',
    'MeasurementJobSubmitted',
    'RemoveTestPlanDraftRowResponse',
    'ReplaceTestPlanDraftRowsRequest',
    'ReplaceTestPlanDraftRowsResponse',
    'ReportRequestSubmitted',
    'ReportOutputMetadata',
    'StopMeasurementJobRequest',
    'StopMeasurementJobResponse',
    'SubmitMeasurementJobRequest',
    'SubmitReportRequest',
    'TestPlanDraftRowView',
    'TestPlanDraftSummaryView',
    'TestPlanDraftView',
    'TestPlanImportResponse',
    'ValidateTestPlanDraftResponse',
    'ValidationIssueView',
    'feature_operations',
    # Wire guard, public so dependent lanes decode payloads without copying it.
    'require_object',
]
