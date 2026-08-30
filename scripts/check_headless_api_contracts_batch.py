"""Check multiple provider headless API contract JSON files.

Ships inside ``fcc-test-contracts`` and must run from the delivered package as
well as from the monorepo — see ``scripts/contract_cli.py``.
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
        prog='check_headless_api_contracts_batch',
        description=(
            'Check several provider headless API contract JSON files against the '
            'shared contract SSOT. Exits 0 when all are compatible, 1 when any is '
            'not, 2 on usage error.'
        ),
    )
    parser.add_argument('contracts', nargs='+', help='paths to provider contract JSON files')
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

    providers: list[dict] = []
    for raw_path in args.contracts:
        try:
            contract = load_contract(raw_path)
        except (OSError, ValueError) as exc:
            emit_usage_error('usage_error', str(raw_path), str(exc), providers=providers)
            return 2
        result = check_api_contract_compatibility(contract)
        providers.append({
            'path': str(raw_path),
            'provider': contract.get('provider', {}),
            **result.to_dict(),
        })

    payload = {
        'compatible': all(provider['compatible'] for provider in providers),
        'providers': providers,
    }
    emit(payload)
    return 0 if payload['compatible'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
