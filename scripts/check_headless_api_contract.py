"""Check a provider headless API contract JSON against the local SSOT.

Ships inside ``fcc-test-contracts`` and must run from the delivered package as
well as from the monorepo — see ``scripts/contract_cli.py`` for why that was
not true before.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract_cli import (  # noqa: E402
    build_parser,
    emit,
    emit_usage_error,
    ensure_importable,
    load_contract,
)

PROJECT_ROOT = ensure_importable(__file__)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog='check_headless_api_contract',
        description=(
            'Check one provider headless API contract JSON against the shared '
            'contract SSOT. Exits 0 when compatible, 1 when not, 2 on usage error.'
        ),
    )
    parser.add_argument(
        '--mode', choices=('full', 'live-subset'), default='full',
        help='full compares the whole surface; live-subset compares only the '
             'operations a provider has declared live',
    )
    parser.add_argument('contract', help='path to the provider contract JSON')
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        # argparse exits the process for `--help` and for a usage error. The
        # in-process callers (CI self-check, tests) expect a return code, and
        # `main([]) == 2` is an existing contract.
        return int(exc.code or 0)

    from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

    try:
        provider = load_contract(args.contract)
    except (OSError, ValueError) as exc:
        emit_usage_error('usage_error', args.contract, str(exc))
        return 2

    result = check_api_contract_compatibility(provider, mode=args.mode)
    emit(result.to_dict())
    return 0 if result.compatible else 1


if __name__ == '__main__':
    raise SystemExit(main())
