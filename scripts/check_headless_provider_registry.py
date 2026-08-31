"""Check every provider named by a registry document against the contract SSOT.

⚠️ **This script moved here from ``fcc-test-platform`` (2026-08-31), and the
move is the fix.** It needs three things -- the registry document, the contract
artifacts, and the batch compatibility checker -- and after the split only the
first was platform-owned. In the delivered platform box it died at its first
import (``ModuleNotFoundError: No module named 'contract_cli'``), and even past
that the artifacts it names were not in that tree. ⚠️ Its old docstring said
*"this file spans two repositories"* and **nothing ever turned that into a red
test**, so it stayed broken while both boxes reported green.

The boundary that survives the move: **format is a contract question, content is
a platform one.** *Which* providers are registered is the platform's operating
fact and stays in its tree; the document is handed to this script by path.

Usage::

    python3 scripts/check_headless_provider_registry.py <registry.json>

``contract_artifact`` entries resolve against **this** tree (``artifacts/``),
because that is where the artifacts live. ⚠️ **That is true only while every
registered provider's artifact is one we publish.** A provider in its own
repository publishes its own artifact, and this resolution has no answer for
that -- see ``docs/OPEN-QUESTIONS.md``. Do not paper over it by copying a
foreign artifact in here; a copy diverges and the divergence is silent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract_cli as _contract_cli  # noqa: E402


PROJECT_ROOT = _contract_cli.ensure_importable(__file__)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(json.dumps({
            'compatible': False,
            'error': {
                'code': 'registry_usage_error',
                'path': '',
                'message': (
                    'a registry path is required — the registry document is '
                    'platform-owned and does not live in this tree'
                ),
            },
            'providers': [],
        }, sort_keys=True, indent=2, ensure_ascii=True))
        return 2

    registry_path = Path(args[0])
    if not registry_path.is_absolute():
        registry_path = Path.cwd() / registry_path

    try:
        from fcc_test_contracts.headless.provider_registry import (
            load_provider_registry,
            validate_registry_contract_identities,
            validate_registry_naming,
        )
        # Sibling entry point. Resolved through contract_cli because the two
        # trees disagree on whether ``scripts/`` is a package, and importing the
        # same file under both names would give it two module identities.
        batch_main = _contract_cli.sibling_module(
            __file__, 'check_headless_api_contracts_batch',
        ).main

        registry = load_provider_registry(registry_path, PROJECT_ROOT)
        # ⚠️ Naming first: it asks whether the DOCUMENT is well formed, and
        # identity asks whether the document AGREES WITH an artifact. Ask the
        # first question first, or a mis-named new provider is reported as an
        # identity mismatch and the author goes looking at the wrong file.
        validate_registry_naming(registry)
        validate_registry_contract_identities(registry)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({
            'compatible': False,
            'error': {
                'code': 'registry_usage_error',
                'path': str(registry_path),
                'message': str(exc),
            },
            'providers': [],
        }, sort_keys=True, indent=2, ensure_ascii=True))
        return 2

    return batch_main(registry.artifact_paths)


if __name__ == '__main__':
    raise SystemExit(main())
