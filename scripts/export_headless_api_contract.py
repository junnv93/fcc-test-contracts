"""Export the shared headless API contract JSON artifact."""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact  # noqa: E402

# The record, not a directory walk: this lane delivers docs/api/ to artifacts/.
DEFAULT_OUTPUT = resolve_repo_artifact(__file__, 'docs/api/headless_api_contract.v1.json')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export the shared headless API contract JSON artifact."
    )
    parser.add_argument(
        'output',
        nargs='?',
        default=str(DEFAULT_OUTPUT),
        help='Output JSON path.',
    )
    parser.add_argument('--provider-id', default=None)
    parser.add_argument('--product-line', default=None)
    parser.add_argument('--contract-family', default=None)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    from fcc_test_contracts.headless.api_contracts import (
        DEFAULT_PROVIDER_METADATA,
        ApiContractSnapshot,
    )

    provider = dict(DEFAULT_PROVIDER_METADATA)
    for key, value in {
        'provider_id': args.provider_id,
        'product_line': args.product_line,
        'contract_family': args.contract_family,
    }.items():
        if value is not None:
            provider[key] = value

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            ApiContractSnapshot(provider=provider).to_dict(),
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
        ) + '\n',
        encoding='utf-8',
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
