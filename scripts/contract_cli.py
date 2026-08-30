"""Entry-point plumbing shared by the contract-checking CLIs.

These scripts ship **inside** ``fcc-test-contracts``. That is the whole point
of them: a joining provider team receives the contract artifacts and the
checker, and their first real task is to run the checker against their own
contract JSON. Under ADR-0018 D-5 the provider repositories stay private, so
there is no reference implementation to copy — the artifacts and this procedure
are the entire channel.

Two things were wrong with that, and both were invisible:

1. **The delivered package could not run its own checker.** The scripts put
   ``<root>/src`` on ``sys.path`` because that is where the modules live in the
   monorepo. In the extracted package there is no ``src/``; the package sits at
   ``<root>/fcc_test_contracts/``. Running the shipped
   ``scripts/check_headless_api_contract.py`` from the shipped tree raised
   ``ModuleNotFoundError: No module named 'fcc_test_contracts'``. The existing
   standalone-import seal deletes ``scripts/`` before probing — *"entry points,
   not package modules"* — so nothing looked.
2. **``--help`` printed a traceback.** Argument handling was hand-rolled
   positional slicing, so the first command a new developer types crashed with a
   Python stack trace pointing at ``pathlib``.

Root discovery is declared, not guessed: :data:`IMPORT_ROOT_CANDIDATES` names
the two shapes this package is ever deployed in, and the first one that exists
wins. Dependency-free by contract — the contracts lane may import nothing but
the standard library.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys

#: Directories that may hold the importable package, relative to the tree root,
#: most specific first. ``src`` is the monorepo layout; ``.`` is the extracted
#: package, where ``fcc_test_contracts/`` sits at the top level. Listing both is
#: not a fallback chain hiding an unknown — these are the only two shapes the
#: manifest produces, and a third would be a new deployment decision.
IMPORT_ROOT_CANDIDATES: tuple[str, ...] = ('src', '.')


def tree_root(script_file: str) -> Path:
    """Root of the tree a CLI is running from: monorepo root or package root."""
    return Path(script_file).resolve().parents[1]


def ensure_importable(script_file: str) -> Path:
    """Put the package root on ``sys.path`` and return the tree root.

    Also adds the script's own directory so a CLI can import its siblings in
    the delivered package, where ``scripts/`` is a directory of entry points
    rather than an importable package of the monorepo.
    """
    root = tree_root(script_file)
    for candidate in IMPORT_ROOT_CANDIDATES:
        path = (root / candidate).resolve()
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    own_dir = str(Path(script_file).resolve().parent)
    if own_dir not in sys.path:
        sys.path.insert(0, own_dir)
    return root


def sibling_module(script_file: str, module_name: str):
    """Import a sibling entry point under whichever shape the tree has.

    The monorepo ships ``scripts/__init__.py``, so siblings are reachable as
    ``scripts.<name>``. The extracted package deliberately does not — see this
    module's own note that ``scripts/`` there is *a directory of entry points
    rather than an importable package* — so the same import must use the bare
    name, which :func:`ensure_importable` puts on the path.

    The shape is *asked*, not guessed at by catching ``ImportError``: a bare
    ``except ImportError`` fallback would also swallow a genuine failure raised
    from inside the sibling and retry it under a second name. Importing the same
    file under two names is its own hazard — two module objects, two sets of
    globals, and a ``mock.patch`` on one that the other never sees.
    """
    own_dir = Path(script_file).resolve().parent
    if (own_dir / '__init__.py').is_file():
        return importlib.import_module(f'{own_dir.name}.{module_name}')
    return importlib.import_module(module_name)


def build_parser(*, prog: str, description: str) -> argparse.ArgumentParser:
    """A parser that answers ``--help`` instead of crashing on it."""
    return argparse.ArgumentParser(prog=prog, description=description)


def load_contract(raw_path: str) -> dict:
    """Read a contract JSON, resolving a relative path against the working directory.

    The previous rule resolved relative paths against the *repository* root,
    which is invisible to someone running the shipped package from their own
    checkout: ``check ./my-contract.json`` would look somewhere else entirely.
    Every existing caller passes an absolute path, so this is the standard
    behaviour rather than a change of contract.
    """
    return json.loads(Path(raw_path).expanduser().read_text(encoding='utf-8'))


def emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True))


def emit_usage_error(code: str, path: str, message: str, **extra) -> None:
    emit({
        'compatible': False,
        'error': {'code': code, 'path': path, 'message': message},
        **extra,
    })
