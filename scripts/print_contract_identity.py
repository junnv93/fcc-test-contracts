"""Print the identity of the SSOT contract — the value a provider must match.

A provider's conformance evidence names the contract it was checked against by
**digest**, never by the ``version`` string (measured 2026-09-04: ``1.0.0`` was
the value for both the 39-operation and the 40-operation contract, so the
version cannot distinguish them). This entry point is how a provider reads that
digest out of the package it received, rather than reimplementing the canonical
form and discovering the difference later.

Usage::

    python3 scripts/print_contract_identity.py            # the SSOT this package ships
    python3 scripts/print_contract_identity.py <path>     # any contract document
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact  # noqa: E402
from fcc_test_contracts.headless.contract_identity import contract_identity  # noqa: E402

DEFAULT_CONTRACT = resolve_repo_artifact(__file__, 'docs/api/headless_api_contract.v1.json')


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else DEFAULT_CONTRACT
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        print(json.dumps({
            'error': {'code': 'contract_not_found', 'path': str(path)},
        }, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    document = json.loads(path.read_text(encoding='utf-8'))
    print(json.dumps(contract_identity(document), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
