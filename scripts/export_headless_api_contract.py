"""Export the shared headless API contract JSON artifact."""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# ⚠️ THIS repository is the SSOT this script publishes, so it must come before
# anything pip installed. Measured 2026-09-05: without this line the script
# imported ``fcc_test_contracts`` from the interpreter's site-packages and wrote
# THAT contract into ``artifacts/``. The installed copy still carried the
# ``row_identity_source`` enum removed in PR #25, so running the publish command
# exactly as §9 of the judgement documents it silently reinstated a repaired
# defect in the delivered artifact — and the artifact is what providers derive
# from. A publisher that reads an installed copy of what it is publishing is the
# same shape as a seal that compares two copies of one document.
#
# ⚠️ Its sibling ``export_headless_openapi.py`` already had this line; this one
# did not, which is why one publisher was correct and the other was not.
#
# Every entry point under ``scripts/`` was then checked BY RUNNING IT, and the
# answer was neither "only this one" nor the "six more" an earlier draft of this
# comment claimed. It was **two**: this file and
# ``mutation_headless_contract_axis.py``, which put ``scripts/`` and a
# non-existent ``src/`` on the path but not the root. The rest reach the same
# result through ``contract_cli.ensure_importable`` — the same job under a
# different spelling, which is exactly what a grep for one literal cannot see.
# ⚠️ That wrong count was itself this file's defect class: a check that reads
# for a spelling answers a different question than the one asked.
# ``tests/test_scripts_resolve_this_tree.py`` measures it now.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SRC_ROOT = PROJECT_ROOT / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(1, str(SRC_ROOT))

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
