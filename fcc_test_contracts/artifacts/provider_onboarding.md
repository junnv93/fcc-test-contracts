# Provider onboarding — run these commands

This file ships **inside** `fcc-test-contracts`. If you are reading it from the
package you received, everything below is runnable from the directory this file
sits in (`artifacts/provider_onboarding.md` → run from the package root).

> **Why this is commands and not prose.** Under ADR-0018 D-5 the provider
> repositories stay private, so there is no reference implementation to copy.
> What you receive is the contract artifacts plus this procedure, and that is
> the whole channel. A procedure that cannot be executed is not a channel.

Every `$` line below is executed by
`tests/test_provider_onboarding_package.py` against a freshly staged package.
If a command here stops working, that test goes red — the document cannot drift
away from the software.

---

## 0. What you received

```
fcc-test-contracts/
  fcc_test_contracts/      the importable package (contract DTOs, checker, web primitives)
  artifacts/               OpenAPI + AsyncAPI documents, the contract SSOT, example contracts
  packages/api-artifacts/  the same artifacts as an npm package, for your frontend
  scripts/                 entry points you run — including the compatibility checker
```

## 1. Prove the package runs before you write anything

<!-- onboarding-commands: package -->
```console
$ python3 scripts/check_headless_api_contract.py --help
# exit: 0
$ python3 scripts/check_headless_api_contract.py artifacts/mmwave_headless_api_contract.example.json
# exit: 0
$ python3 scripts/check_headless_api_contracts_batch.py artifacts/mmwave_headless_api_contract.example.json artifacts/licensed_headless_api_contract.example.json
# exit: 0
```

The second command prints `"compatible": true`. That is the round trip: a
provider contract that is not yours, checked by the checker you received,
against the SSOT you received. If it fails, stop — the package is wrong, not
your contract.

**The checker is the only oracle.** It exits `0` when compatible, `1` when not,
and `2` on a usage error. Do not read the JSON for a `compatible` string and
decide for yourself; wire the exit code into your CI.

## 2. Start from an example, not from the schema

```console
$ cp artifacts/mmwave_headless_api_contract.example.json my_contract.json
```

Then edit `provider.id`, `provider.display_name`, and the operations your
headless actually serves. `artifacts/headless_api_contract.v1.json` is the SSOT
your contract is compared against — read it, do not copy it: it describes every
operation, and you declare the subset you serve.

## 3. Check your own contract

<!-- onboarding-commands: authored -->
```console
$ python3 scripts/check_headless_api_contract.py my_contract.json
# exit: 0
$ python3 scripts/check_headless_api_contract.py --mode live-subset my_contract.json
# exit: 0
```

`--mode full` compares the whole surface. `--mode live-subset` compares only the
operations you have declared live, which is what you want while you are still
building: it lets you go green on the part you serve without pretending to serve
the rest.

## 4. Consume the artifacts from your frontend

```console
$ cd packages/api-artifacts && npm pack --dry-run
```

`manifest.json` in that package is the single artifact SSOT — it declares which
files belong, their kind, and whether codegen consumes them. Generate your
client types from `artifacts/*.openapi.json`; do not hand-write them, and do not
re-derive server-computed values on the client.

## 5. What you build, and what you never receive

You build a headless service that serves the operations you declared. The
platform is shared; **your measurement code is not shared and you will not
receive anyone else's.** ADR-0010 D-9 lists the pieces; in your own repository
they are:

| # | You own | Verified by |
|---|---------|-------------|
| O-1 | capability taxonomy + matrix builder | your golden tests |
| O-2 | deterministic test-plan generator | your snapshot tests |
| O-3 | test-plan validation | your contract tests |
| O-4 | Excel (or other) import/export adapter | your round-trip tests |
| O-5 | row-identity field set — decides history join keys | hash determinism test |
| O-6 | frontend grid components for your rows | your frontend tests |
| O-6b | UI descriptor: display labels, feature readiness, rendering metadata | descriptor schema test |
| O-7 | **your contract JSON** — the operations you serve | §3 above, in your CI |
| O-8 | RBAC scopes, provider-prefixed | platform-side registration |
| O-9 | report template + cell mapping | your end-to-end report test |

O-7 is the one that gates the others: the platform cannot render your rows
until your contract declares them.

### ⚠️ O-5 — `condition_hash` is **yours**, and the centre never recomputes it

Measured 2026-09-04 across the central lane: nothing in `fcc-test-platform` or
`fcc-test-contracts` computes `condition_hash`. It appears in five contract
schemas (`MeasurementAttemptEnvelope`, `PublishedTestPlanRowView`,
`TestPlanGenerationRowView`, `TestPlanGenerationSampleRow`, `ValidationIssueView`)
as a field the centre **carries**, never as one it derives.

That is the contract, stated here because the schemas do not say it: **the
producer of this value is the provider, and recomputing it centrally would be a
migration, not an implementation detail.** A provider whose row identity includes
non-ASCII values (a temperature step named in Korean, say) must be free to choose
its own serialisation — and a central recomputation using different JSON encoding
options would silently break every history join that value was holding together.

If you are that provider: pin the encoding decision inside the hashed value
itself (a scheme tag such as `…-condition-v1`) so that changing it is visibly a
migration rather than a silent divergence.

## 6. Open questions you should know about before you plan

- **Node-to-central runtime.** Standing up a chamber node needs the outbox,
  heartbeat sender, and node packaging. That code is not measurement knowledge
  and every provider needs it, so the operator decided on **2026-08-10** that it
  becomes **its own shared lane** rather than staying private to one provider.
  It is **not in this package yet** — the lane exists as a decision, not as a
  delivery. Plan for it as *supplied later*, not as *write it yourself*.
- **This package is `private` on npm.** You receive it as a tarball or a git
  ref, not from a registry. `npm pack` above produces exactly what you would be
  handed.

## 7. Report the result — what the centre receives

§5 assigns you **O-7: your contract JSON, verified by §3, in your CI.** This
section says what happens to that verification once it passes.

**You never send your contract artifact.** Operator ruling 2026-08-31 (option
「나」): the artifact stays with its publisher and the centre receives only the
result. You send a **conformance evidence document**, shaped by
`artifacts/provider_contract_conformance_evidence.schema.v2.json`.

⚠️ **You are not required to serve the whole contract.** Until 2026-09-05 you
were: the only judgement available was *"serves all 40 operations"*, so a
provider building the surface in stages was `compatible=false` for reasons that
had nothing to do with conformance. You now declare **which features you
serve**, and you are judged against that — in full. §7.0 says how to choose the
declaration; the rest of §7 assumes you have.

### 7.0 Declare what you serve

The contract groups its operations into **features**, and the group is in the
contract document itself — read it, do not invent ids:

<!-- onboarding-commands: features -->
```console
$ python3 -c "import json,sys; d=json.load(open('fcc_test_contracts/artifacts/headless_api_contract.v1.json')); print('\n'.join(sorted(d['features'])))"
# exit: 0
```

Each operation names its feature (`operations.<name>.feature`), so the grouping
and the surface cannot disagree. Features marked `"required": true` are **core**:
they are in scope whether you declare them or not, because without them the
centre cannot even ask what you support.

Three rules decide whether your declaration is legal, and only the third has
teeth on its own:

| | |
|---|---|
| ① core is served | required features are in scope, always |
| ② declaration and surface agree | declare a feature and you serve every one of its operations; serve one and you declare it |
| ③ the **dependency closure** holds | for every operation you serve, every id its path needs must be mintable by something you also serve |

⚠️ **①② compare you with yourself.** A provider that declares nothing and serves
nothing satisfies both. ③ is what closes that, and it is derived from the
contract rather than listed: a route with `{x}` consumes `x`, and an operation
produces `x` when its response declares `x` at top level under a write method
without taking `x` from its own path. So serving `publish_test_plan_draft`
obliges you to serve `create_test_plan_draft` **or** `import_test_plan` — either
one; the closure asks whether a draft can exist, not which door made it.

⚠️ Three identifiers are exempt and one is a known defect on our side:
`project_id` comes from the centre (no provider mints projects), `session_id`
appears when a measurement runs (no operation creates one), and `job_id` has no
derivable producer because our measurement axis spells it three ways —
registered debt, and it means the closure is silent there. Nothing you do
about that.

⚠️ **This declaration is NOT `ProviderUiDescriptor.features`, and you must not
copy one into the other.** That field is the display-readiness channel and its
ids are yours to choose; ADR-0010 D-7 keeps the two apart on purpose. Measured
2026-09-05: the reference provider declares `equipment_config` /
`reference_tables` / `correction_tables` there, none of which is a headless
operation at all.

### 7.1 Read the identity of the contract you checked against

<!-- onboarding-commands: identity -->
```console
$ python3 scripts/print_contract_identity.py
# exit: 0
$ python3 scripts/print_contract_identity.py --features measurement-jobs
# exit: 0
```

⚠️ **Pass `--features` with your declaration from §7.0.** Without it you get the
whole-contract digest, which you can only match by serving all 40. With it, both
sides reduce the document to the same scope before hashing, so the comparison
stays arithmetic. Declaring every non-required feature reproduces the
whole-contract digest exactly — the scope is a conservative extension, not a
second regime.

⚠️ **Paste the output; do not retype it.** A digest hand-carried between two
lanes on 2026-09-05 arrived two characters short.

⚠️ **`scripts/` travels with the box, not inside the wheel.** If you pinned this
lane with `pip install git+…` you did not receive that file (measured
2026-09-04 by a provider: the v0.1.12 `RECORD` has no `^scripts/` entry). The
same value is importable, and that path reaches every consumer:

```python
from fcc_test_contracts.common.tree_artifacts import resolve_dependency_artifact
from fcc_test_contracts.headless.contract_identity import contract_identity
import json

ssot = resolve_dependency_artifact('fcc_test_contracts/artifacts/headless_api_contract.v1.json')
document = json.loads(ssot.read_text(encoding='utf-8'))
identity = feature_scoped_identity(document, ['measurement-jobs'])   # your §7.0 list
```

(import it as `from fcc_test_contracts.headless.contract_identity import
feature_scoped_identity`; `contract_identity` remains for the whole-contract
value.)

⚠️ Reach the artifact through `resolve_dependency_artifact`, not through
`importlib.resources.files(...)`: this lane's packages are PEP 420 namespace
packages, and `files()` on one returns a `MultiplexedPath` that raises
`NotADirectoryError` when you join a directory onto it. (Measured 2026-09-04 —
by the author of this section, one command after writing it.)

Both paths print `{algorithm, digest, operations, features}`. ⚠️ **The `digest` is what
your evidence must name — not the `version` string.** Measured 2026-09-04: `version`
was `1.0.0` for both the 39-operation contract and the 40-operation contract
that replaced it, so a result keyed to the version cannot say which one it
checked. The digest moves when the contract moves; the version did not.

### 7.2 Emit the evidence

```json
{
  "schema_version": 2,
  "provider_id": "<your registry provider_id>",
  "declared_features": ["<from 7.0>", "..."],
  "contract_identity": { "algorithm": "sha256", "digest": "<from 7.1>", "operations": 21, "features": ["core", "..."] },
  "subject":           { "algorithm": "sha256", "digest": "<same scope, YOUR derived artifact>" },
  "checker":           { "package": "fcc-test-contracts", "version": "<the version you ran>", "mode": "declared-features" },
  "result":            { "compatible": true, "issues": [] },
  "produced_at": "<ISO-8601>",
  "produced_by": { "repository": "<your repo>", "commit": "<sha>" }
}
```

⚠️ `checker.mode` must be `declared-features`. **Not `live-subset`** — that mode
was rejected as a conformance basis precisely because nobody had defined which
subset is legal, and sending it here re-admits the rejection. `full` is still
correct if you declare every feature.

`subject.digest` is the identity of the artifact **you derived from your own
implementation** — the same command in §7.1 accepts a path, so run it on your
artifact.

⚠️ **When you are conformant, `subject.digest` equals `contract_identity.digest`.**
That is not a coincidence and not a shortcut: the compatibility checker strips
the `provider` block from both sides before comparing, so two conformant
contracts in the same family are the same document on the axis that matters.
**That equality is what lets the centre verify you without ever holding your
artifact** — which is the whole reason option 「나」 is implementable.

### 7.3 What the centre does with it — and what makes it red

Verification is **derived, not scheduled**. The central gate recomputes the SSOT
digest **over your declared features** on every run and compares it to your
`contract_identity.digest`. There is no expiry field and no cron: when the
contract changes — or when you change what you declare — every outstanding
evidence document becomes stale on the next gate run, automatically.

Three named failures, so the cause is legible from the failure alone:

| | |
|---|---|
| **evidence missing** | you are registered and no document arrived |
| **evidence stale** | your `contract_identity.digest` is not the current SSOT digest |
| **evidence non-conformant** | `subject.digest` disagrees with `contract_identity.digest`, or `result.compatible` is not `true` |
| **evidence unscoped** | `declared_features` is absent, or names a feature the contract does not declare |
| **evidence wrong-mode** | `checker.mode` is not `declared-features` |

⚠️ **Fail closed.** A registered provider with no evidence is not *unknown*, it
is *non-conformant*. Absence and pass must never share a value.

### 7.4 What this does not cover — read this before you rely on it

**Forgery.** An unsigned evidence document can be hand-written with the correct
digest and a flattering declaration, and nothing here detects it. This channel
closes **absence**, **staleness** and **undeclared scope** only.

**That a declared feature works.** Conformance judges the *surface*. Measured
2026-09-04: a provider served all four measurement-job operations with no worker
consuming the queue, so every submitted job stayed `queued` forever. That is a
runtime fact `headless_status` answers, and an offline artifact cannot carry
it — do not read a green evidence document as *"this feature functions."* Signing waits on an answer about key custody that does not
exist yet; when it does, a signature block joins the schema's
`required_top_level` and this subsection shrinks.

Saying so is part of the design. A channel that looked stronger than it is would
be the same defect it was built to end.
