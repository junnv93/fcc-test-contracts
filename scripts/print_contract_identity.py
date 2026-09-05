"""Print the identity of the SSOT contract — the value a provider must match.

A provider's conformance evidence names the contract it was checked against by
**digest**, never by the ``version`` string (measured 2026-09-04: ``1.0.0`` was
the value for both the 39-operation and the 40-operation contract, so the
version cannot distinguish them). This entry point is how a provider reads that
digest out of the package it received, rather than reimplementing the canonical
form and discovering the difference later.

A provider that serves only part of the contract names the scope it serves,
and the digest is taken over that scope. Both sides reduce with the same
function, so the comparison stays arithmetic — see §6.7 of the judgement.

Usage::

    python3 scripts/print_contract_identity.py            # the SSOT this package ships
    python3 scripts/print_contract_identity.py <path>     # any contract document
    python3 scripts/print_contract_identity.py --features core,measurement-jobs
    python3 scripts/print_contract_identity.py --features -   # read ids on stdin

⚠️ Required features are in scope whether you name them or not, so
``--features ''`` is the smallest legal declaration, not an empty one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
# The sibling entry points live next to this one and are not an importable
# package in the delivered box — see ``scripts/contract_cli.py``.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract_cli import read_declared_features  # noqa: E402
from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact  # noqa: E402
from fcc_test_contracts.headless.contract_identity import (  # noqa: E402
    FeatureScopeError,
    contract_identity,
    feature_scoped_identity,
)

DEFAULT_CONTRACT = resolve_repo_artifact(__file__, 'docs/api/headless_api_contract.v1.json')


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    declared: list[str] | None = None
    if '--features' in args:
        index = args.index('--features')
        if index + 1 >= len(args):
            print(json.dumps({
                'error': {'code': 'features_missing_value'},
            }, indent=2, sort_keys=True), file=sys.stderr)
            return 2
        # ⚠️ One parser for the declaration, shared with the checker CLI: a
        # provider pastes the same list into both commands, and two spellings
        # of "split on commas" is how the digest and the check would come to
        # disagree about a scope neither of them mis-stated.
        declared = read_declared_features(args[index + 1])
        del args[index:index + 2]
    path = Path(args[0]) if args else DEFAULT_CONTRACT
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        print(json.dumps({
            'error': {'code': 'contract_not_found', 'path': str(path)},
        }, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    document = json.loads(path.read_text(encoding='utf-8'))
    if declared is None:
        identity = contract_identity(document)
    else:
        try:
            identity = feature_scoped_identity(document, declared)
        except FeatureScopeError as error:
            print(json.dumps({
                'error': {
                    'code': 'unknown_declared_feature',
                    'message': str(error),
                    'declarable': sorted(document.get('features') or {}),
                },
            }, indent=2, sort_keys=True), file=sys.stderr)
            return 2
    print(json.dumps(identity, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
