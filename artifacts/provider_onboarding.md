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
