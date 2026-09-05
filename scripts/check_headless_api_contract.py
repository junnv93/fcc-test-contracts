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
    read_declared_features,
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
        '--mode', choices=('full', 'live-subset', 'declared-features'), default='full',
        help='full compares the whole surface; live-subset compares only the '
             'operations a provider has declared live; declared-features '
             'compares the whole of the features --features names, and is the '
             'only mode the conformance evidence channel accepts',
    )
    parser.add_argument(
        '--features', metavar='IDS', default=None,
        help="feature ids this provider serves, comma- or newline-separated "
             "('-' reads them on stdin). Required by --mode declared-features "
             "and meaningless in every other mode. '' is the smallest legal "
             "declaration, not an empty one: required features are in scope "
             "whether you name them or not",
    )
    parser.add_argument('contract', help='path to the provider contract JSON')
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        # argparse exits the process for `--help` and for a usage error. The
        # in-process callers (CI self-check, tests) expect a return code, and
        # `main([]) == 2` is an existing contract.
        return int(exc.code or 0)

    # ⚠️ The flags are judged before the file is read. A declaration passed in
    # the wrong mode is a fault in the command, not in the contract, and
    # reporting it as one keeps `2` meaning *you asked wrongly* rather than
    # *your contract is bad*. The library raises ValueError on the same
    # mismatch; catching it here would report the fault after the work and as
    # a traceback.
    if (args.mode == 'declared-features') != (args.features is not None):
        emit_usage_error(
            'features_mode_mismatch', args.contract,
            "--features is required by --mode declared-features and is "
            "meaningless in any other mode",
        )
        return 2

    from fcc_test_contracts.headless.api_contract_checker import check_api_contract_compatibility

    declared = None if args.features is None else read_declared_features(args.features)

    try:
        provider = load_contract(args.contract)
    except (OSError, ValueError) as exc:
        emit_usage_error('usage_error', args.contract, str(exc))
        return 2

    # ⚠️ A feature id the contract does not declare comes back as an *issue*
    # (`unknown_declared_feature`, exit 1), not as a usage error. That is the
    # library's judgement and it is the right one for this channel: §7.3 of the
    # onboarding document names an unscoped declaration `evidence unscoped` — a
    # red result the centre records, not a mistyped command line.
    result = check_api_contract_compatibility(
        provider, mode=args.mode, declared_features=declared,
    )
    emit(result.to_dict())
    return 0 if result.compatible else 1


if __name__ == '__main__':
    raise SystemExit(main())
