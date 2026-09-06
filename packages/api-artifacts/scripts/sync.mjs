#!/usr/bin/env node
/**
 * Sync the @fcc/api-artifacts mirror from the canonical docs/ SSOT — B3 (P14).
 *
 * The shared API contract artifacts have a single canonical writer each:
 *   - docs/api/*.openapi.json          ← scripts/export_session_api_schemas.py (Python)
 *   - docs/platform/central_db_schema.v1.json  ← hand-maintained contract source
 *
 * This script is the SINGLE WRITER of the package mirror
 * (`packages/api-artifacts/artifacts/*.json`). It copies the canonical bytes
 * verbatim so the mirror stays byte-identical to docsSource. No file gains a
 * second writer: docs/ is written by its own canonical tool, the mirror only
 * by this script.
 *
 * Modes:
 *   node scripts/sync.mjs           copy docs/* -> artifacts/* (write)
 *   node scripts/sync.mjs --check   exit non-zero if any mirror byte-differs
 *                                    from its docsSource (CI drift gate)
 *
 * Byte-exact: reads/writes as raw Buffers (no decode/re-encode, no EOL
 * translation) so LF stays LF and the mirror is a literal copy.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const PKG_ROOT = resolve(dirname(__filename), '..');
// packages/api-artifacts -> packages -> repo root
const REPO_ROOT = resolve(PKG_ROOT, '..', '..');
const ARTIFACTS_DIR = resolve(PKG_ROOT, 'artifacts');

const manifest = JSON.parse(readFileSync(resolve(PKG_ROOT, 'manifest.json'), 'utf8'));
const checkMode = process.argv.includes('--check');

/**
 * Where a repository-relative path actually lives in THIS tree.
 *
 * ⚠️ This script used to join `REPO_ROOT + docsSource` and treat a miss as
 * "canonical source missing". In a delivered tree that is wrong: the extraction
 * packager RELOCATES files and writes down what it moved where, in
 * `.extraction-layout.json` at the box root. `docs/api/*.openapi.json` are
 * relocated to `fcc_test_contracts/artifacts/`, so this script reported three
 * canonical sources as missing while the repository's own Python side — which
 * asks `resolve_repo_artifact` instead of doing the arithmetic — published to
 * them and stayed green (measured 2026-09-06).
 *
 * Two consequences, and the second is the expensive one:
 *   1. the gate could not go green, so nobody could act on it;
 *   2. two REAL drifts (platform-api, central-db-schema) were hiding behind
 *      those three false "missing" lines.
 *
 * The record is a fact written by the packager, not a plan — a file that was
 * copied is a file that was recorded. Absent record (the monorepo, which never
 * relocates) means the literal path, which is what it always meant there.
 */
const LAYOUT_RECORD = resolve(REPO_ROOT, '.extraction-layout.json');
const relocations = existsSync(LAYOUT_RECORD)
  ? (JSON.parse(readFileSync(LAYOUT_RECORD, 'utf8')).paths ?? {})
  : {};

function resolveRepoArtifact(repoRelative) {
  const relocated = relocations[repoRelative] ?? repoRelative;
  return resolve(REPO_ROOT, ...relocated.split('/'));
}

if (!checkMode) {
  mkdirSync(ARTIFACTS_DIR, { recursive: true });
}

let drift = false;
let missing = false;

for (const entry of manifest.artifacts) {
  const source = resolveRepoArtifact(entry.docsSource);
  // ⚠️ 진단은 «실제로 본 자리»를 대야 한다. 이사한 트리에서 `docsSource` 는 이 트리에
  //    존재하지 않는 경로이고, 그것만 찍으면 읽는 사람이 없는 파일을 찾으러 간다.
  const shown = relative(REPO_ROOT, source);
  const dest = resolve(ARTIFACTS_DIR, entry.file);

  if (!existsSync(source)) {
    console.error(`[api-artifacts:sync] canonical source missing: ${shown} (manifest docsSource: ${entry.docsSource})`);
    missing = true;
    continue;
  }

  const sourceBytes = readFileSync(source);

  if (checkMode) {
    if (!existsSync(dest)) {
      console.error(`[api-artifacts:sync] mirror missing: artifacts/${entry.file} — run \`node scripts/sync.mjs\`.`);
      drift = true;
      continue;
    }
    const destBytes = readFileSync(dest);
    if (!sourceBytes.equals(destBytes)) {
      console.error(
        `[api-artifacts:sync] DRIFT: artifacts/${entry.file} differs from ${shown}. ` +
          'Run `node scripts/sync.mjs` to re-mirror.',
      );
      drift = true;
    } else {
      console.log(`[api-artifacts:sync:check] ${entry.name}: up to date`);
    }
    continue;
  }

  writeFileSync(dest, sourceBytes);
  console.log(`[api-artifacts:sync] ${entry.name}: mirrored artifacts/${entry.file} (${sourceBytes.length} bytes)`);
}

if (missing || drift) {
  process.exitCode = 1;
}
