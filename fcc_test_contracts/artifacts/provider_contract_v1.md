# Provider Contract v1 Draft

Status: Draft for Unlicensed-first, mmWave/Provider expansion

## Purpose

This document defines the shared web-platform contract boundary for independent
test providers. Unlicensed is the first implementation target. mmWave and
licensed providers will attach to the same platform contract after the
Unlicensed slice establishes the working pattern. Each provider keeps its
internal measurement and report logic private, but exposes the same
platform-facing concepts.

## Ownership

| Concern | Owner |
| --- | --- |
| Contract DTOs, route names, compatibility checker | `fcc-test-contracts` |
| Central DB, web backend, frontend shell, auth/RBAC | `fcc-test-platform` |
| Unlicensed measurement/report internals | `fcc-unlicensed-headless` |
| mmWave measurement/report internals | `fcc-mmwave-headless` |
| Licensed measurement/report internals | `fcc-licensed-headless` |

## Provider Identity

Every provider exposes metadata:

```json
{
  "provider_id": "fcc-unlicensed-conducted",
  "product_line": "unlicensed-conducted",
  "contract_family": "fcc-conducted-headless"
}
```

mmWave uses:

```json
{
  "provider_id": "fcc-mmwave-headless",
  "product_line": "mmwave",
  "contract_family": "fcc-conducted-headless"
}
```

Licensed uses:

```json
{
  "provider_id": "fcc-licensed-headless",
  "product_line": "licensed-conducted",
  "contract_family": "fcc-conducted-headless"
}
```

`contract_family` stays shared while both providers use the same job/result
envelope. If mmWave or licensed later needs incompatible semantics, create a
new major contract lane instead of adding provider-specific branches to
platform code.

## Required Routes

| Operation | Method | Path | Purpose |
| --- | --- | --- | --- |
| `headless_api_contract` | `GET` | `/headless/api-contract` | Return machine-readable provider contract |
| `provider_capabilities` | `GET` | `/headless/capabilities` | List supported tests, report types, artifact types, and runtime limits |
| `submit_measurement_job` | `POST` | `/headless/jobs` | Start provider-owned measurement job |
| `list_measurement_jobs` | `GET` | `/headless/jobs` | List recent jobs visible to platform |
| `get_measurement_job` | `GET` | `/headless/jobs/{job_id}` | Read job state |
| `stop_measurement_job` | `POST` | `/headless/jobs/{job_id}/stop` | Request cancellation |
| `list_session_results` | `GET` | `/headless/sessions/{session_id}/results` | Return provider-normalized result envelope |
| `list_session_artifacts` | `GET` | `/headless/sessions/{session_id}/artifacts` | Return artifact metadata |
| `submit_report_request` | `POST` | `/headless/sessions/{session_id}/reports` | Generate provider-owned report output |
| `get_report_request` | `GET` | `/headless/reports/{request_id}` | Read report generation state |
| `list_report_outputs` | `GET` | `/headless/reports/{request_id}/outputs` | Return report output file metadata for platform download handoff |

The published target contract is the full family contract. A provider may expose
a **live subset** from `GET /headless/api-contract` while it is being onboarded:
declared operations must match this document exactly, but unimplemented
operations should be omitted from the live contract or reported as explicit
`unsupported`. Do not advertise routes that return fake success.

Use the compatibility checker in full mode for target contract examples and in
live-subset mode for an actual provider runtime:

```powershell
python scripts/check_headless_api_contract.py path/to/full-target-contract.json
python scripts/check_headless_api_contract.py --mode live-subset path/to/live-api-contract.json
```

## Shared DTOs

### ProviderCapability

```json
{
  "provider_id": "fcc-unlicensed-conducted",
  "product_line": "unlicensed-conducted",
  "supported_job_types": ["measurement", "report_generation"],
  "supported_technologies": ["BT", "BLE", "DTS", "UNII"],
  "supported_artifact_types": ["plot_png", "screenshot_png", "trace_csv"],
  "supports_cancel": true,
  "supports_offline_queue": true
}
```

mmWave and licensed providers supply their own `supported_technologies` and
capabilities without changing the platform schema.

### MeasurementJobRequest

```json
{
  "requested_by": "web",
  "provider_id": "fcc-unlicensed-conducted",
  "project_id": "project-uuid",
  "model_id": "model-uuid",
  "sample_id": "sample-uuid",
  "test_plan_ref": {
    "kind": "db_session",
    "id": "session-or-plan-id"
  },
  "selection": {
    "technologies": ["DTS", "UNII"],
    "tests": ["OBW", "Power"]
  },
  "idempotency_key": "web-job-uuid"
}
```

### MeasurementResultEnvelope

```json
{
  "provider_id": "fcc-unlicensed-conducted",
  "session_id": "session-uuid",
  "result_id": "result-uuid",
  "test_name": "OBW",
  "technology": "DTS",
  "condition": {
    "band": "5GHz",
    "bandwidth": "20MHz",
    "channel": "36",
    "antenna": "ANT1"
  },
  "result": {
    "result1": "22.0",
    "result2": "",
    "margin": "",
    "unit": "MHz"
  },
  "verdict": "Pass",
  "measured_at": "2026-05-14T00:00:00Z"
}
```

The platform treats `condition` and `result` as provider-owned JSON, while
common columns such as `provider_id`, `session_id`, `test_name`, `technology`,
`verdict`, and timestamps are indexed for cross-provider browsing.

### MeasurementJobSnapshot Lease Fields

`assigned_worker_id` is worker attribution, not only current active ownership.
When a worker has claimed or executed a job, providers should preserve the value
on terminal snapshots so operators can see which worker handled the job. Clear it
only when a job is explicitly requeued into an unassigned active state.

`lease_expires_at` is a wall-clock ISO timestamp. Providers must not serialize a
monotonic deadline or elapsed-seconds value into this field. If a provider only
has monotonic timing, omit `lease_expires_at` from its live subset or expose the
monotonic value as a provider-specific additional property.

### ArtifactMetadata

```json
{
  "provider_id": "fcc-unlicensed-conducted",
  "session_id": "session-uuid",
  "result_id": "result-uuid",
  "artifact_type": "plot_png",
  "relative_path": "project_123/session_456/result_00017/plot_png/output_power_ant1_ch36.png",
  "original_filename": "output_power_ant1_ch36.png",
  "sha256": "hex",
  "byte_size": 12345,
  "storage_backend": "filesystem",
  "created_at": "2026-05-14T00:00:00Z"
}
```

The file server/object store owns binary content. The DB owns metadata and
resolution roots are environment configuration.

Provider APIs return relative artifact paths. Absolute artifact roots may exist
inside provider configuration or runtime wiring, but they must not leak into
platform-facing artifact metadata or report output metadata.

### ReportRequest

```json
{
  "provider_id": "fcc-unlicensed-conducted",
  "session_id": "session-uuid",
  "report_types": ["DTS", "UNII"],
  "output_formats": ["docx", "pdf", "xlsx"],
  "artifact_roots": ["//server/FCCArtifacts"],
  "idempotency_key": "report-request-uuid"
}
```

`output_dir` may be omitted by the caller when the provider runtime is
configured with `FCC_HEADLESS_REPORT_OUTPUT_DIR`. Artifact lookup roots should
come from environment/runtime configuration such as `FCC_HEADLESS_ARTIFACT_ROOTS`
or from the request's `artifact_roots`; the platform must not hardcode company
file-server paths in route handlers.

### ReportOutputMetadata

```json
{
  "request_id": 101,
  "file_name": "dts.docx",
  "path": "//server/FCCReports/unlicensed/session_456/dts.docx",
  "relative_path": "session_456/dts.docx",
  "exists": true,
  "byte_size": 234567,
  "storage_backend": "filesystem"
}
```

The provider API returns metadata only. It must not stream report bytes through
the contract DTO and must not store DOCX/PDF bytes in the DB. A future platform
can use this metadata to proxy a download, issue a signed URL, or open a
company file-server path according to the deployed storage policy.

Missing files remain visible with `exists=false` and `byte_size=null` so the
operator can distinguish "report request completed but file missing" from "no
report was generated".

## Central DB Mapping

The platform DB planning SSOT is
`docs/platform/central_db_schema.v1.json`. It defines common tables and
provider JSON payload boundaries:

```text
providers
projects
models
samples
test_sessions
jobs
measurement_results
artifacts
report_runs
diagnostics
users
permissions
```

The `measurement_results` table should include:

```text
provider_code
session_id
test_name
technology
condition_json
result_json
verdict
measured_at
```

This avoids forcing Unlicensed, mmWave, and licensed providers to share
measurement internals.

## Collaboration Rules

- Platform code may depend on this contract only.
- Platform code must not import Unlicensed, mmWave, or licensed provider modules.
- Providers must not copy DTO definitions; they should consume
  `fcc-test-contracts` once extracted.
- Provider-specific UI should be driven by capability metadata where possible.
- New shared fields require contract review by both provider owners.

## Initial Implementation Backlog

1. Add missing routes and schemas to the current `ApiContractSnapshot`.
2. Export Unlicensed, mmWave, and licensed example contract artifacts.
3. Keep `headless_provider_registry.json` as the temporary provider registry
   until moved to `fcc-test-platform`.
4. Add compatibility tests that validate both provider artifacts.
5. Draft central DB migration for common platform tables.
6. Build a platform MVP that can list providers, submit a job, show session
   results, browse artifacts, and download reports.

## UI Descriptor (WEB-PROVIDER-UI-0, 2026-05-29)

Provider-aware web UI is **schema-driven**: each provider publishes a UI
descriptor and the shared platform renders it generically. Rules:

1. **Provider owns the descriptor.** The descriptor (provider id / display name,
   feature matrix, test plan / equipment / reference / correction table schemas)
   is served by the provider at `GET /headless/ui-descriptor`
   (operationId `provider_ui_descriptor`, permission `headless:read`). The
   Unlicensed descriptor is built from the `Col.*` / `DUTY_SHEETS` Excel SSOT —
   no new column / technology / equipment string literals.
2. **Platform is a schema-driven renderer.** The platform exposes a read-only
   proxy `GET /platform/providers/{provider_id}/ui-descriptor`
   (permission `platform:read`) served from a provider registry. The platform
   **never imports provider internals** (`measurements` / `workflows` / the
   provider descriptor builder); the composition root is the single wiring
   point. The shared descriptor *contract schema* lives in a neutral location
   (`application/common/provider_ui_descriptor_schema.py`) consumed by both
   surfaces — so the platform contract never cross-imports the provider module.
3. **apps/web consumes the platform client only.** The descriptor viewer uses
   `platform-client` (never `headless-client`) and hardcodes no provider
   technology / equipment / Excel-column literal — every label is descriptor
   runtime data.
4. **Custom provider UI = extension slot only.** When a provider genuinely needs
   non-generic UI (e.g. an mmWave beam-sweep visualizer), it is mounted as a
   sandboxed platform extension; the central DB contract is never broken.
5. 🔴 **`features` here is the DISPLAY axis, not the conformance axis.** The
   `ProviderFeature[]` array answers *"what should the screen show as ready?"*
   and its `feature_id` values are the provider's own — measured 2026-09-05, the
   Unlicensed descriptor declares `test_plan_edit` / `equipment_config` /
   `reference_tables` / `correction_tables` / `job_submission`, three of which
   name descriptor sub-tables and no headless operation at all. Conformance is
   judged on a **different** vocabulary that lives in the contract document
   (`features`, with each operation naming its own) and travels in the
   conformance evidence — see «Conformance features» below. ⚠️ Do not enum-lock
   one to the other and do not copy one into the other: rule D-7 of ADR-0010
   already forbids the descriptor from reaching into the typed contract, and one
   name over two axes is the defect this contract removed from `job_id` on the
   same day.
6. **Blueprint is a non-SSOT mockup.** `web_excel_replacement_ui_blueprint_2026-05-29.html`
   (and its BT/BLE/DTS/UNII tokens, column headers, row counts / metrics) is a
   design reference only — the runtime SSOT is the descriptor + `Col.*`.

Row edit / save / publish are **deferred** to `WEB-PROVIDER-UI-0.5` (stable
row-identity + authoritative store ADR): `condition_hash` currently includes
`row_order`, so row insert/delete/reorder would orphan existing
attempt/coverage/claim identity. No row CRUD/publish until that ADR lands.


## Conformance features (2026-09-05)

The contract document carries a top-level `features` block, and every entry in
`operations` names the feature it belongs to. Together they partition all 40
operations, disjointly and totally — checked at import, not by convention.

```
features.<id>.required   true ⇒ core: in scope whether a provider declares it or not
operations.<id>.feature  the single feature that operation is part of
```

A provider declares the features it serves in its **conformance evidence**
(`provider_contract_conformance_evidence.schema.v2.json`), and is judged against
that scope in full: every operation of every in-scope feature, plus the
dependency closure derived from the route path parameters. Both sides reduce the
document with `contract_identity.feature_scoped_document`, so the comparison
stays a digest equality and the centre never receives a provider artifact.

⚠️ **Core is deliberately small — five operations.** The test for widening it is
*"without this, what can the centre not ask?"*, never *"this is important."*

```
health_check · headless_api_contract · headless_status
             · provider_capabilities · provider_ui_descriptor
```

⚠️ **A feature is a grouping, not a promise that it works.** `headless_status`
answers the runtime question; conformance answers the surface question. A
provider can serve every measurement-job operation with no worker consuming the
queue (measured 2026-09-04), and the evidence is green because the evidence is
about the surface.


## Path identifiers must be opaque (2026-09-05)

Every `{name}` a route takes is declared in `HEADLESS_API_PATH_PARAMS`, and
`path_identifier_policy` refuses a **new** numeric one at import time. The rule
is not this project's invention:

* [OWASP API Security Top 10 2023 — API1:2023 BOLA][owasp]: *"Prefer the use of
  random and unpredictable values as GUIDs for records' IDs."*
* [Zalando RESTful API Guidelines][zalando] rule 174: *"IDs must be opaque
  strings and not numbers. IDs are unique within some documented context, are
  stable and don't change for a given object once assigned."* Rule 144 adds the
  second reason — sequential ids *"may reveal critical, confidential business
  information, like order volume, to non-privileged clients."*

⚠️ **Three identifiers are still integers and are named rather than excused** —
`session_id`, `request_id`, `draft_row_id`. They live in
`INTEGER_IDENTIFIER_GRANDFATHER`, each with the reason it has not moved, and the
list is a **ratchet**: it may shrink and never grow. Migrating three live
surfaces inside the commit that repaired a fourth would have been three
unannounced wire breaks riding along with one decided change.

[owasp]: https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/
[zalando]: https://opensource.zalando.com/restful-api-guidelines/
