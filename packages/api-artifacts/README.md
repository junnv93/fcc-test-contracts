# @fcc/api-artifacts

Repo-split-ready bundle of the shared FCC API contract artifacts (B3 / P14).

It packages the four cross-language contract artifacts so that, when the
monorepo is split (see `docs/architecture/repository_split_adr.md`), the
contract surface can be lifted into its own `fcc-test-contracts` repo and
consumed by every backend/frontend via a normal npm dependency.

## Contents

| name | file | kind | codegen | canonical source (`docsSource`) |
|------|------|------|---------|----------------------------------|
| `session-api` | `artifacts/session-api.openapi.json` | openapi | ✅ | `docs/api/session-api.openapi.json` |
| `headless-api` | `artifacts/headless-api.openapi.json` | openapi | ✅ | `docs/api/headless-api.openapi.json` |
| `platform-api` | `artifacts/platform-api.openapi.json` | openapi | ✅ | `docs/api/platform-api.openapi.json` |
| `central-db-schema` | `artifacts/central_db_schema.v1.json` | db-schema | — | `docs/platform/central_db_schema.v1.json` |

`manifest.json` is the **single artifact SSOT** — the one place that declares
which files belong to the package, their kind, whether codegen consumes them,
and the canonical `docsSource` they mirror.

## Single-writer / SSOT model

```
 docs/api/*.openapi.json            ← scripts/export_session_api_schemas.py  (Python, canonical)
 docs/platform/central_db_schema..  ← hand-maintained contract source        (canonical)
            │
            │  node scripts/sync.mjs   (the ONLY writer of the mirror)
            ▼
 packages/api-artifacts/artifacts/*.json   ← byte-identical mirror (committed, sealed)
            │
            │  import { OPENAPI_SPECS } from '@fcc/api-artifacts'
            ▼
 apps/web/scripts/codegen.mjs  → src/api/generated/*.types.ts
```

No file has two writers: `docs/` is written by its own canonical tool, the
mirror only by `scripts/sync.mjs`. The mirror is kept **byte-identical** to its
`docsSource` and is sealed by:

- `tests/test_api_artifacts_package.py` — **이 레인의 실질 게이트.** `scripts/lane_check.py`
  가 pytest 만 부르므로, 이 레포에서 실제로 도는 것은 이것 하나다. 규칙을 다시 적지 않고
  `sync.mjs` 를 실행해 종료코드로 판정한다.
- `node scripts/sync.mjs --check` — 같은 판정의 node 진입점. ⚠️ **이 레포에는 그것을
  부르는 워크플로가 없다.** 이 줄은 오래 `frontend-build.yml` 에서 돈다고 적었는데
  그런 워크플로가 이 레포에 없다 — 모노레포 문장이 배송 때 따라온 것이다.

⚠️ **정본은 이 트리에서 «옮겨져» 있다.** 추출 패키저가 `docs/api/*.openapi.json` 을
`fcc_test_contracts/artifacts/` 로 옮기고 그 사실을 루트의 `.extraction-layout.json` 에
적는다. `sync.mjs` 는 그 기록을 읽는다 — 경로를 직접 조립하던 시절에는 정본 셋을
「없다」고 보고했고, 그 **거짓 빨강 뒤에 진짜 드리프트 둘이 숨어 있었다**(2026-09-06).

## Programmatic API

```js
import { ARTIFACTS, OPENAPI_SPECS, resolveArtifact, loadArtifact, MANIFEST } from '@fcc/api-artifacts';

OPENAPI_SPECS;                       // codegen specs with absolute path + typesBasename
resolveArtifact('central-db-schema'); // absolute path
loadArtifact('platform-api');         // parsed JSON
```

`apps/web` currently consumes this package by **relative path** from
`scripts/codegen.mjs` (no install/lockfile churn). A bare-specifier
`@fcc/api-artifacts` `file:` devDependency in `apps/web/package.json` is
deferred to the repo-split milestone: it requires regenerating
`apps/web/package-lock.json` (so `npm ci` stays in sync), which is a separate
**staging gate**. Relative-path consumption already gives codegen the single
artifact SSOT without that coupling.

## Re-mirror after a contract change

```bash
# 1. regenerate canonical OpenAPI from backend SSOT
python scripts/export_session_api_schemas.py
# 2. re-mirror into the package
node packages/api-artifacts/scripts/sync.mjs
# 3. regenerate TS clients
cd apps/web && npm run codegen
```

## Publishing (staging / manual gate)

`npm publish` is intentionally **not** automated here. This package is `private`
inside the monorepo. Actual publishing belongs to the repo-split milestone
(`docs/architecture/repository_split_adr.md`), where `private` is lifted,
versioning/CI publish is added, and `docsSource` is dropped (artifacts become
self-contained). Until then this package is consumed locally only.
