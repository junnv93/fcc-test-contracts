# Headless API Contract Extraction Plan

## Candidate Shared Package

Future package name: `fcc_test_contracts`

Initial modules to extract:

| Current file | Current module | Future module |
|--------------|----------------|---------------|
| `src/application/headless/api_contracts.py` | `application.headless.api_contracts` | `fcc_test_contracts.headless.api_contracts` |
| `src/application/headless/api_contract_checker.py` | `application.headless.api_contract_checker` | `fcc_test_contracts.headless.api_contract_checker` |

Generated artifact:

- `docs/api/headless_api_contract.v1.json`

Extraction checklist SSOT:

- `docs/api/headless_contract_extraction_manifest.v1.json`

CI scripts:

- `scripts/export_headless_api_contract.py`
- `scripts/check_headless_api_contract.py`
- `scripts/check_headless_api_contracts_batch.py`

Provider registry belongs to the future `fcc-test-platform` lane, not the
contracts package. The current registry extraction target is tracked in
`docs/api/headless_contract_extraction_manifest.v1.json`.

## Boundary Rules

- Contract modules must stay dependency-free except Python stdlib. The one
  permitted exception is a distribution listed in the manifest's
  `optional_external`, and only as a lazy import inside a function guarded by
  `ImportError` with an actionable message — never at module level, so
  `pip install fcc-test-contracts` still imports without it. Today that list is
  `['jwt']`, needed by `oidc_principal_resolver` only when a deployment sets
  `auth_mode=oidc_jwt`.
- Contract modules must not import infrastructure, database, FastAPI, Pydantic, PySide6, Appium, VISA, pandas, or SQLAlchemy.
- Contract modules must not import **any other lane**, including the domain
  layer. `depends_on` for `fcc-test-contracts` is `[]` and stays `[]`.
- Every lane-owned Python file must have an `entries` row. Ownership says who
  holds a path; `entries` say where it goes, and the staging runner reads only
  the second. A file that is owned but unlisted is silently absent from the
  delivered package.
- Provider identity belongs in top-level `provider` metadata.
- Compatibility is determined by `version`, `routes`, `operations`, and `schemas`; provider metadata does not affect compatibility.
- Contract `version` follows SemVer. `compatibility_major` identifies the major compatibility lane that both backends must share.

## How "dependency-free" is proved (SPLIT-1, 2026-08-07)

Reading import statements is not a proof. Until 2026-08-07 the readiness gate
did exactly that — it parsed `api_contracts.py` and `api_contract_checker.py`
and looked for forbidden prefixes. Neither file names a provider module, so the
gate was green while `api_contracts` → `api_contract_dtos` → the Unlicensed
full-generation engine (`contracts`, `engine`, `job_service`, `limits`,
`metadata`) made the lane impossible to build alone. A transitive closure is
invisible to a two-file grep.

The gate is now an execution, and it runs against **two** trees, because the
first attempt at this proof used a tree no consumer produces:

1. `test_staged_contracts_tree_imports_with_only_itself_on_the_path` stages the
   `src/` modules the manifest *owns*, under their monorepo names.
2. `test_the_package_the_runner_actually_produces_imports_standalone` runs
   `scripts/prepare_headless_extraction_package.py`, which stages from
   `entries` and rewrites imports into `fcc_test_contracts.*` — the tree a
   provider team is actually handed — then runs the import-boundary checker
   over it and imports every module in it.

Both import in **a separate interpreter** whose `PYTHONPATH` is the staged tree
and nothing else. A separate process is required: the pytest process has the
whole repository importable, so an in-process check passes by borrowing the
tree the lane is supposed to leave behind.

Only (1) existed at first, and it was green while the runner's package failed on
seven modules — 18 of the lane's 34 files had no `entries` row, so they were
neither copied nor import-rewritten. **A proof on a tree nobody ships proves
nothing**, which is why `test_every_lane_owned_module_is_scheduled_to_move` now
forces the two lists to cover the same files.

Two more gates cover dimensions nothing measured before: a planted-leak test
asserts the probe goes red on the exact import that was there, and
`test_lane_takes_no_third_party_dependency_it_has_not_declared` scans every
lane-owned file for imports outside stdlib and this repository — the dimension
in which re-assigning ownership had quietly brought PyJWT into a package
advertised as stdlib-only.

Two rules decided where each leak went, and they are the rules to reuse:

1. **Provider vocabulary moves out.** If a contracts-lane module maps a wire
   payload into a provider or domain *type*, the mapping belongs to the lane
   that owns the type. The full-generation HTTP DTOs therefore live in
   `application/services/test_plan_generation/web_full_generation/api_dtos.py`,
   and `derived_kind` crosses the wire as an opaque token that the provider lane
   resolves to its enum. Promoting those types into the shared contract would
   freeze one provider's words into everyone's package (ADR-0010 D-8).
2. **Shared web-boundary policy is declared, not moved.** Rate-limit rules,
   health-probe paths, the trace-sampler Protocol, and OIDC principal resolution
   are read by all three surfaces and carry no measurement semantics. They were
   living in whichever directory happened to host them; the manifest now assigns
   them to the contracts lane with a `future_path`. `trace_sampler_port.py`
   stays physically in `domain/ports/` because `TestProtocolPlacement` requires
   Protocols to live there — ownership and location are separate questions.

What was **not** done: adding `shared-kernel` to `depends_on`. It would have
driven the same three baseline pairs to zero without moving one import, and
would have shipped the entire measurement domain to every new provider team.

## Backend Responsibilities

The first implementation target is `unlicensed-conducted`. The same contract
then applies to `mmwave` and later `licensed-conducted` providers. All providers
should:

- expose `GET /headless/api-contract`
- export a JSON artifact equivalent to `ApiContractSnapshot().to_dict()`
- run `scripts/check_headless_api_contract.py <provider-contract.json>` in CI
- keep internal measurement workflow, DB schema, and hardware adapters private to each backend

Before creating the new repositories, run:

```bash
python -m pytest tests/test_contracts_platform_extraction_manifest.py -q
python scripts/prepare_headless_extraction_package.py --repo fcc-test-contracts
python scripts/prepare_headless_extraction_package.py --repo fcc-test-platform
```

This guards against accidentally moving Unlicensed provider internals into
`fcc-test-contracts` or `fcc-test-platform`.

To stage a copy package for review without writing into the future repositories:

```bash
python scripts/prepare_headless_extraction_package.py --repo fcc-test-contracts --copy-to .tmp/extraction
python scripts/prepare_headless_extraction_package.py --repo fcc-test-platform --copy-to .tmp/extraction
```

Provider-specific export examples:

```bash
python scripts/export_headless_api_contract.py docs/api/headless_api_contract.v1.json \
  --provider-id fcc-unlicensed-conducted \
  --product-line unlicensed-conducted

python scripts/export_headless_api_contract.py mmwave_contract.json \
  --provider-id fcc-mmwave-headless \
  --product-line mmwave

python scripts/export_headless_api_contract.py licensed_contract.json \
  --provider-id fcc-licensed-headless \
  --product-line licensed-conducted
```
