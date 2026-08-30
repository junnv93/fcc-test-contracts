"""The psycopg-paramstyle shim: one identity, proven by running it.

This file replaces a decision procedure that could not terminate. Until
2026-09-07 the raw-``sqlite3.connect`` ratchet carried an ``evidence`` rule named
``qmark_wrapper`` whose job was to decide, from source text alone, whether a
fixture's private ``_QmarkCursor`` "really translates ``%s`` to ``?``". Three
independent adversarial reviews broke it by the same mechanism, and the third
named the mechanism precisely:

    The exemption is a claim about a **runtime object** — "the thing that
    receives SQL at this site translates". The validator proved a property of a
    **definition** and assumed the definition described the object. But
    ``obj.execute`` resolves over ``type(obj).__mro__`` and ``obj.__dict__``,
    and every slot in that search is writable by ordinary code. The enumeration
    of "ways a name can be replaced" is a strict subset of "ways attribute
    resolution can change", and the latter has no closed enumeration.

Counterexample counts went 6 → 22 → 20 across the three rounds, i.e. they did
not converge. So the repair is not another rule: it is removing the surface the
rule had to judge. Every fixture now reaches SQL through **one** wrapper
(``tests/support/central_pg_sqlite_shim``), which does not open a raw
connection at all — it goes through ``SqliteConnectionFactory``. The ratchet's
question becomes "is this the identity we tested?", which is decidable, and this
file is where that identity is tested.

Two axes, and they are different questions:

* **structural** — is the shim still the only paramstyle-translating wrapper?
  (If a twelfth private copy appears, the identity argument silently stops
  covering it.)
* **behavioural** — does the shim actually translate, and does the raw engine
  actually reject the untranslated form? A positive alone would pass even if
  SQLite happened to tolerate ``%s``; the control is what makes the positive
  mean something.
"""
from __future__ import annotations

import ast
import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _extra in (_REPO_ROOT / 'src', _REPO_ROOT / 'tests'):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from _ast_string_finder import static_eval_string  # noqa: E402
from fcc_test_contracts.common.sqlite_connection_factory import (  # noqa: E402
    SqliteConnectionFactory,
)
from fcc_test_contracts.common.sqlite_pragma_policy import (  # noqa: E402
    SQLITE_BUSY_TIMEOUT_MS,
)
from support.central_pg_sqlite_shim import (  # noqa: E402
    AdoptedQmarkConnection,
    QmarkConnection,
    QmarkCursor,
    RowcountBlindConnection,
    RowcountBlindCursor,
)


#: The one file allowed to define a paramstyle-translating wrapper.
SHIM_PATH = 'tests/support/central_pg_sqlite_shim.py'

#: Directories the structural scan walks. ``src/`` is deliberately absent — a
#: paramstyle shim in production code would be a different (worse) defect and
#: is already refused by the psycopg adapters' own contract; this axis is about
#: test doubles multiplying.
SCANNED_ROOTS = ('tests', 'scripts')

#: DB-API method names that make a class *a driver* rather than a helper. The
#: shim's own seam (``translate``) is included so a copy cannot dodge by moving
#: the rewrite one method along — the shape the retired validator kept losing to.
_DRIVER_METHODS = frozenset({'execute', 'executemany', 'executescript', 'translate'})


def _translates_paramstyle(call: ast.Call) -> bool:
    """``<expr>.replace('%s', '?')`` — the six-line copy's load-bearing line.

    Uses :func:`static_eval_string` rather than a bare ``ast.Constant`` check
    (checklist C-2): ``'%' + 's'`` and an f-string spell the same literal.

    ⚠️ ``>= 2`` arguments, not ``== 2``. ``statement.replace('%s', '?', -1)`` is
    identical in meaning and nothing about it is evasive; an independent review
    wrote it as one of eight working copies the first version of this predicate
    missed. The unbound ``str.replace(statement, '%s', '?')`` spelling is
    resolved for the same reason.
    """
    if not isinstance(call.func, ast.Attribute) or call.func.attr != 'replace':
        return False
    if (
        isinstance(call.func.value, ast.Name)
        and call.func.value.id == 'str'
        and len(call.args) >= 3
    ):
        return (
            static_eval_string(call.args[1]) == '%s'
            and static_eval_string(call.args[2]) == '?'
        )
    if len(call.args) < 2:
        return False
    first, second = (static_eval_string(arg) for arg in call.args[:2])
    return first == '%s' and second == '?'


def paramstyle_translating_definitions(root: Path) -> tuple[tuple[str, str, int], ...]:
    """Every ``(relpath, class name, line)`` that defines a translating wrapper.

    The unit is *a class with a translating* ``execute`` **method**, not a class
    that happens to contain the literal anywhere. Translating one statement
    inline (``SQL.replace('%s', '?')`` at a call site, including inside a
    ``TestCase`` method) is a local rewrite that claims nothing; a class whose
    ``execute`` translates is an object presenting itself as a driver, and that
    is the thing the retired evidence rule had to judge and could not.

    ⚠️ Measured, not guessed: walking the whole class body flagged five
    ``TestCase`` classes that assert production SQL against a DDL fixture. A
    detector that nags on legitimate code is a detector somebody deletes, and
    the deletion takes the two real findings with it.

    ⚠️ **This is a guardrail against the copies coming back, not a proof that
    no translation can exist.** A copy spelled with ``re.sub`` or a translation
    table would not be seen. That limit is acceptable *here* and was not
    acceptable for the retired rule, because the direction of failure is
    opposite: the old rule's blind spots **granted** a raw-connection exemption,
    while this one's merely fail to nag. Nothing rests on its completeness.
    """
    found: list[tuple[str, str, int]] = []
    for scanned in SCANNED_ROOTS:
        base = root / scanned
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*.py')):
            rel = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                methods = [
                    member for member in node.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and member.name in _DRIVER_METHODS
                ]
                if any(
                    isinstance(inner, ast.Call) and _translates_paramstyle(inner)
                    for method in methods
                    for inner in ast.walk(method)
                ):
                    found.append((rel, node.name, node.lineno))
            # Module-level helpers too: a private class that delegates its
            # rewrite to ``_qmark(statement)`` is the same debt with an extra
            # hop, and an independent review used exactly that hop to hide a
            # working copy. Measured on this tree: widening costs **zero** false
            # positives, because a call-site rewrite lives inside a method.
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if any(
                    isinstance(inner, ast.Call) and _translates_paramstyle(inner)
                    for inner in ast.walk(node)
                ):
                    found.append((rel, node.name, node.lineno))
    return tuple(found)


# --------------------------------------------------------------------------- #
# Behavioural census                                                         #
# --------------------------------------------------------------------------- #

# The structural detector above is intentionally only a review-time nag. The
# correctness owner below supplies the same DB-API-shaped input to a minimal
# AST capsule and observes what reaches its recorder. It never imports an
# arbitrary test module: most test modules have module-level fixtures,
# registrations, or filesystem setup.
_CENSUS_SQL = 'X %s'
_CENSUS_PARAMETERS = ('census-parameter-7',)
_CENSUS_REWRITTEN_SQL = 'X ?'
_CAPSULE_SAFE_MODULES = frozenset({'re', 'string', 'typing', '__future__'})
_CAPSULE_SAFE_CALLS = frozenset({
    'dict', 'frozenset', 'list', 'ord', 're.compile', 'set', 'str.maketrans',
    'tuple',
})
_CAPSULE_BUILTINS = frozenset({
    'BaseException', 'Exception', 'False', 'None', 'True', 'ValueError',
    'RuntimeError', 'TypeError', 'bool', 'bytes', 'classmethod', 'enumerate',
    'float', 'int', 'isinstance', 'len', 'list', 'object', 'property', 'range',
    'repr', 'set', 'staticmethod', 'str', 'super', 'tuple', 'type', 'zip', 'ord',
})
_DB_API_STATEMENT_NAMES = frozenset({
    'command', 'operation', 'query', 'sql', 'statement', 'stmt',
})
_PROBE_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class CandidateIdentity:
    """Stable identity for one class-owned DB-API ``execute`` member."""

    relative_path: str
    qualified_class_name: str
    execute_owner: str


@dataclass(frozen=True)
class ObservedMemberEvidence:
    """The member-level evidence which makes a census finding meaningful."""

    execute_owner: str
    statement: str
    parameters: tuple[object, ...]


@dataclass(frozen=True)
class CensusFailure:
    """A candidate that could not be safely probed; never silently discard it."""

    identity: CandidateIdentity
    reason: str


@dataclass(frozen=True)
class CensusReport:
    """Immutable census output: exact observations plus named failures."""

    observations: tuple[tuple[CandidateIdentity, ObservedMemberEvidence], ...]
    failures: tuple[CensusFailure, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @property
    def mapping(self):
        """Return the candidate identity → member evidence mapping read-only."""
        return MappingProxyType(dict(self.observations))


@dataclass
class _CapsuleCandidate:
    identity: CandidateIdentity
    tree: ast.Module
    class_node: ast.ClassDef
    executable: ast.AST
    binding_node: ast.AST | None
    constructor_kinds: dict[str, list[str]]


class _CapsuleRejected(Exception):
    """A source-level reason for refusing to construct a probe capsule."""


class _CapsuleAnnotationStripper(ast.NodeTransformer):
    """Remove annotations so capsules do not resolve unrelated names."""

    def _strip_args(self, args: ast.arguments) -> None:
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            arg.annotation = None
            arg.type_comment = None
        if args.vararg:
            args.vararg.annotation = None
        if args.kwarg:
            args.kwarg.annotation = None

    def visit_FunctionDef(self, node: ast.FunctionDef):  # noqa: N802 - AST API
        node = self.generic_visit(node)
        self._strip_args(node.args)
        node.returns = None
        node.type_comment = None
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):  # noqa: N802
        node = self.generic_visit(node)
        self._strip_args(node.args)
        node.returns = None
        node.type_comment = None
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign):  # noqa: N802
        node = self.generic_visit(node)
        if node.value is None:
            return None
        return ast.Assign(targets=[node.target], value=node.value)


def _strip_capsule_annotations(tree: ast.Module) -> ast.Module:
    cloned = _CapsuleAnnotationStripper().visit(copy.deepcopy(tree))
    ast.fix_missing_locations(cloned)
    return cloned


def _assigned_names(node: ast.AST) -> set[str]:
    names = {
        child.id for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
    }
    for child in ast.walk(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = child.args
            names.update(arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))
            if args.vararg:
                names.add(args.vararg.arg)
            if args.kwarg:
                names.add(args.kwarg.arg)
    return names


def _global_names(node: ast.AST) -> set[str]:
    loaded = {
        child.id for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }
    return loaded - _assigned_names(node) - {'__class__', 'cls', 'self'}


def _imported_names(node: ast.Import | ast.ImportFrom) -> dict[str, str]:
    if isinstance(node, ast.Import):
        return {
            (alias.asname or alias.name.split('.')[0]): alias.name
            for alias in node.names
        }
    return {
        (alias.asname or alias.name): node.module or ''
        for alias in node.names
    }


def _import_is_safe(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.ImportFrom):
        return not node.level and (node.module or '').split('.')[0] in _CAPSULE_SAFE_MODULES
    return all(alias.name.split('.')[0] in _CAPSULE_SAFE_MODULES for alias in node.names)


def _call_path(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_path(node.value)
        return f'{prefix}.{node.attr}' if prefix else node.attr
    return None


def _is_safe_pure_expression(node: ast.AST) -> bool:
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.Attribute):
        return _is_safe_pure_expression(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_safe_pure_expression(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is None or _is_safe_pure_expression(key) for key in node.keys
        ) and all(_is_safe_pure_expression(value) for value in node.values)
    if isinstance(node, ast.UnaryOp):
        return _is_safe_pure_expression(node.operand)
    if isinstance(node, ast.BinOp):
        return _is_safe_pure_expression(node.left) and _is_safe_pure_expression(node.right)
    if isinstance(node, ast.Call):
        path = _call_path(node.func)
        return (
            path in _CAPSULE_SAFE_CALLS
            and all(_is_safe_pure_expression(arg) for arg in node.args)
            and all(_is_safe_pure_expression(keyword.value) for keyword in node.keywords)
        )
    return False


def _assignment_targets(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        return set()
    return {target.id for target in targets if isinstance(target, ast.Name)}


def _class_post_bindings(tree: ast.Module) -> dict[str, ast.Assign]:
    bindings: dict[str, ast.Assign] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.attr == 'execute'
        ):
            bindings[target.value.id] = node
    return bindings


def _resolve_executable(node: ast.AST, top_level: dict[str, ast.AST]) -> ast.AST | None:
    if isinstance(node, ast.Name):
        resolved = top_level.get(node.id)
        return resolved if isinstance(resolved, (ast.FunctionDef, ast.Lambda)) else None
    return node if isinstance(node, (ast.FunctionDef, ast.Lambda)) else None


def _callable_shape(node: ast.AST, *, bound_self: bool) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = [*node.args.posonlyargs, *node.args.args]
        if bound_self:
            args = args[1:]
    else:
        return False
    return bool(args) and args[0].arg.lower() in _DB_API_STATEMENT_NAMES


def _delegates_to_super(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == 'execute'
        and isinstance(child.func.value, ast.Call)
        and isinstance(child.func.value.func, ast.Name)
        and child.func.value.func.id == 'super'
        for child in ast.walk(node)
    )


def _has_db_api_delegate(node: ast.AST) -> bool:
    """Select cursor-like wrappers without enumerating rewrite spellings."""
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == 'execute'
        and _call_path(child.func.value) != 'self'
        for child in ast.walk(node)
    )


def _find_init_lambda(class_node: ast.ClassDef) -> ast.Lambda | None:
    init = next(
        (
            member for member in class_node.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name == '__init__'
        ),
        None,
    )
    if init is None:
        return None
    for node in ast.walk(init):
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Attribute)
            and target.attr == 'execute'
            and isinstance(target.value, ast.Name)
            and target.value.id == 'self'
            for target in node.targets
        ) and isinstance(node.value, ast.Lambda):
            return node.value
    return None


def _constructor_kinds(class_node: ast.ClassDef) -> dict[str, list[str]]:
    init = next(
        (
            member for member in class_node.body
            if isinstance(member, ast.FunctionDef) and member.name == '__init__'
        ),
        None,
    )
    if init is None:
        return {'positional': [], 'keywords': []}
    args = [*init.args.posonlyargs, *init.args.args]
    if args and args[0].arg in {'self', 'cls'}:
        args = args[1:]
    default_start = len(args) - len(init.args.defaults)

    def kind(name: str) -> str:
        lowered = name.lower()
        if lowered in {'sink', 'log', 'record', 'records'}:
            return 'list'
        if lowered in {'fail', 'raise_error', 'return_error'}:
            return 'false'
        if lowered in {'row', 'rows'}:
            return 'list'
        return 'recorder'

    return {
        'positional': [
            kind(arg.arg) for index, arg in enumerate(args) if index < default_start
        ],
        'keywords': [
            kind(arg.arg)
            for arg, default in zip(init.args.kwonlyargs, init.args.kw_defaults)
            if default is None
        ],
    }


def _required_keyword_names(class_node: ast.ClassDef) -> tuple[str, ...]:
    init = next(
        (
            member for member in class_node.body
            if isinstance(member, ast.FunctionDef) and member.name == '__init__'
        ),
        None,
    )
    if init is None:
        return ()
    return tuple(
        arg.arg for arg, default in zip(init.args.kwonlyargs, init.args.kw_defaults)
        if default is None
    )


def _discover_capsule_candidates(root: Path) -> tuple[_CapsuleCandidate, ...]:
    candidates: list[_CapsuleCandidate] = []
    for scanned in SCANNED_ROOTS:
        base = root / scanned
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*.py')):
            try:
                tree = _strip_capsule_annotations(
                    ast.parse(path.read_text(encoding='utf-8'))
                )
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            top_level = {
                node.name: node for node in tree.body
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            }
            bindings = _class_post_bindings(tree)
            for class_node in tree.body:
                if not isinstance(class_node, ast.ClassDef):
                    continue
                binding_node = bindings.get(class_node.name)
                executable: ast.AST | None = None
                owner = f'{class_node.name}.execute'
                bound_self = True
                if binding_node is not None:
                    executable = _resolve_executable(binding_node.value, top_level)
                if executable is None:
                    for member in class_node.body:
                        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == 'execute':
                            executable = member
                            break
                        if isinstance(member, ast.Assign) and any(
                            isinstance(target, ast.Name) and target.id == 'execute'
                            for target in member.targets
                        ):
                            executable = _resolve_executable(member.value, top_level)
                            break
                init_lambda = _find_init_lambda(class_node)
                if init_lambda is not None:
                    executable = init_lambda
                    binding_node = None
                    owner = f'{class_node.name}.__init__.execute'
                    bound_self = False
                if executable is None or not _callable_shape(executable, bound_self=bound_self):
                    continue
                if not (_has_db_api_delegate(class_node) or _has_db_api_delegate(executable)):
                    continue
                # A subclass that merely injects a side action and calls its
                # parent's execute is a consumer of the inherited translator,
                # not another translation owner. This keeps the inherited
                # controls from duplicating QmarkCursor.
                if _delegates_to_super(executable):
                    continue
                relative = path.relative_to(root).as_posix()
                candidates.append(_CapsuleCandidate(
                    identity=CandidateIdentity(relative, class_node.name, owner),
                    tree=tree,
                    class_node=class_node,
                    executable=executable,
                    binding_node=binding_node,
                    constructor_kinds=_constructor_kinds(class_node),
                ))
    return tuple(candidates)


def _forbidden_effect(node: ast.AST) -> str | None:
    direct_calls = {
        'eval': 'dynamic code execution',
        'exec': 'dynamic code execution',
        'input': 'host input',
        'open': 'file I/O',
        'breakpoint': 'debugger side effect',
    }
    dangerous_attributes = {
        'accept', 'bind', 'listen', 'mkdir', 'popen', 'read_bytes', 'read_text',
        'recv', 'recvfrom', 'remove', 'rmdir', 'run', 'send', 'sendall',
        'unlink', 'write_bytes', 'write_text',
    }
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            path = _call_path(child.func)
            if path in direct_calls:
                return f'{direct_calls[path]} via {path}()'
            if isinstance(child.func, ast.Attribute):
                if child.func.attr == 'connect':
                    return 'network/raw database open via .connect()'
                if child.func.attr in dangerous_attributes:
                    return f'host side effect via .{child.func.attr}()'
                root = _call_path(child.func.value)
                if root and root.split('.')[0] in {'os', 'pathlib', 'socket', 'sqlite3', 'subprocess'}:
                    return f'host side effect via {root}.{child.func.attr}()'
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, (ast.Attribute, ast.Subscript)):
                    root = _call_path(target.value)
                    if root and root.split('.')[0] in {'os', 'sys'}:
                        return f'process state mutation via {root}'
    return None


def _validate_class_definition(class_node: ast.ClassDef) -> None:
    allowed_decorators = {'classmethod', 'property', 'staticmethod'}
    for decorator in class_node.decorator_list:
        if _call_path(decorator) not in allowed_decorators:
            raise _CapsuleRejected(f'unsafe class decorator {ast.unparse(decorator)}')
    for base in class_node.bases:
        if not isinstance(base, ast.Name):
            raise _CapsuleRejected(f'unsafe class base {ast.unparse(base)}')
    for member in class_node.body:
        if isinstance(member, (ast.Assign, ast.AnnAssign)):
            value = member.value
            if value is None or not _is_safe_pure_expression(value):
                raise _CapsuleRejected(
                    f'unsafe class binding at line {getattr(member, "lineno", "?")}'
                )
        elif isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Pass)):
            for decorator in member.decorator_list:
                if _call_path(decorator) not in allowed_decorators:
                    raise _CapsuleRejected(
                        f'unsafe method decorator {ast.unparse(decorator)}'
                    )
        elif isinstance(member, ast.Expr) and isinstance(member.value, ast.Constant) and isinstance(member.value.value, str):
            continue
        else:
            raise _CapsuleRejected(
                f'unsafe class-level statement {type(member).__name__}'
            )


def _build_capsule(candidate: _CapsuleCandidate) -> str:
    tree = candidate.tree
    symbols = {
        node.name: node for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assignments = {
        name: node for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for name in _assignment_targets(node)
    }
    imports: dict[str, ast.Import | ast.ImportFrom] = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.update({name: node for name in _imported_names(node)})

    _validate_class_definition(candidate.class_node)
    effect = _forbidden_effect(candidate.executable)
    if effect:
        raise _CapsuleRejected(f'forbidden candidate effect: {effect}')
    if candidate.binding_node is not None and not _is_safe_pure_expression(candidate.binding_node.value):
        raise _CapsuleRejected('unsafe module-level execute binding')

    selected_names = {candidate.class_node.name}
    pending = [candidate.class_node.name]
    if candidate.binding_node is not None:
        pending.extend(_global_names(candidate.binding_node))
    selected_assignments: set[str] = set()
    selected_imports: set[int] = set()
    binding_line = getattr(candidate.binding_node, 'lineno', None)
    while pending:
        name = pending.pop()
        if name in _CAPSULE_BUILTINS or name == '__future__':
            continue
        if name in symbols:
            selected_names.add(name)
            node = symbols[name]
        elif name in assignments:
            if name in selected_assignments:
                continue
            selected_assignments.add(name)
            node = assignments[name]
            if not _is_safe_pure_expression(node.value):
                raise _CapsuleRejected(f'unsafe module constant {name}')
        elif name in imports:
            node = imports[name]
            if not _import_is_safe(node):
                module = node.module if isinstance(node, ast.ImportFrom) else ast.unparse(node)
                raise _CapsuleRejected(f'unsafe import required by capsule: {module}')
            selected_imports.add(id(node))
            continue
        else:
            raise _CapsuleRejected(f'unresolved capsule dependency {name!r}')
        effect = _forbidden_effect(node)
        if effect:
            raise _CapsuleRejected(f'forbidden candidate dependency effect: {effect}')
        pending.extend(
            dependency for dependency in _global_names(node)
            if dependency != candidate.class_node.name
            and dependency not in _CAPSULE_BUILTINS
        )

    effect = _forbidden_effect(candidate.class_node)
    if effect:
        raise _CapsuleRejected(f'forbidden candidate effect: {effect}')

    chosen: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            chosen.append(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) in selected_imports:
            chosen.append(node)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in selected_names:
            chosen.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if _assignment_targets(node) & selected_assignments:
                chosen.append(node)
            elif binding_line is not None and getattr(node, 'lineno', None) == binding_line:
                chosen.append(node)
    source = '\n\n'.join(ast.unparse(node) for node in chosen)
    if not source.strip():
        raise _CapsuleRejected('empty AST capsule')
    return source


_CAPSULE_PROBE_SCRIPT = r'''
import builtins
import json
import sys


class _DeniedHostEffect(RuntimeError):
    pass


def _deny(*_args, **_kwargs):
    raise _DeniedHostEffect('host effect denied by census probe')


builtins.open = _deny


class _ProbeValue:
    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __contains__(self, _item):
        return False

    def __getitem__(self, _item):
        return self

    def __call__(self, *_args, **_kwargs):
        return self

    def __getattr__(self, _name):
        return self

    def pop(self, *_args, **_kwargs):
        return None


class _ProbeHub:
    def __init__(self):
        self.calls = []

    def record(self, statement, parameters):
        try:
            values = tuple(parameters)
        except TypeError:
            values = parameters
        self.calls.append((statement, values))


class _ProbeObject:
    def __init__(self, hub):
        self._hub = hub
        self.executed = []
        self.statements = []
        self.applied = {}
        self.invalid_index_snapshots = []
        self.autocommit = False
        self.closed = False
        self.rowcount = 0

    def execute(self, statement, parameters=()):
        self._hub.record(statement, parameters)

    def executemany(self, statement, parameters):
        for values in parameters:
            self._hub.record(statement, values)

    def cursor(self):
        return self

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def respond(self, *_args, **_kwargs):
        return [], []

    def next_result(self, *_args, **_kwargs):
        return []

    def rows_for(self, *_args, **_kwargs):
        return []

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        self.closed = True

    def __getattr__(self, _name):
        return _ProbeValue()


def _value(kind, hub):
    if kind == 'list':
        return []
    if kind == 'false':
        return False
    if kind == 'string':
        return 'census-sentinel'
    return _ProbeObject(hub)


def _main():
    payload = json.loads(sys.argv[1])
    namespace = {}
    try:
        # This is the validated, dependency-closed capsule, never the source
        # of a whole repository module.
        exec(compile(payload['capsule'], '<ast-capsule>', 'exec'), namespace, namespace)
        cls = namespace[payload['class_name']]
        hub = _ProbeHub()
        kinds = payload['constructor_kinds']
        args = [_value(kind, hub) for kind in kinds['positional']]
        kwargs = {
            name: _value(kind, hub)
            for name, kind in zip(kinds['keyword_names'], kinds['keywords'])
        }
        instance = cls(*args, **kwargs)
        execute = getattr(instance, 'execute', None)
        if not callable(execute):
            raise TypeError('candidate has no callable execute member after construction')
        execute(payload['sql'], tuple(payload['parameters']))
        print(json.dumps({
            'ok': True,
            'calls': [
                {'statement': statement, 'parameters': list(parameters)}
                for statement, parameters in hub.calls
            ],
        }))
    except BaseException as exc:
        print(json.dumps({
            'ok': False,
            'reason': f'{type(exc).__name__}: {exc}',
        }))


_main()
'''


def _probe_candidate(
    candidate: _CapsuleCandidate,
    capsule: str,
) -> tuple[ObservedMemberEvidence | None, str | None]:
    kinds = candidate.constructor_kinds
    payload = {
        'capsule': capsule,
        'class_name': candidate.class_node.name,
        'constructor_kinds': {
            **kinds,
            'keyword_names': list(_required_keyword_names(candidate.class_node)),
        },
        'sql': _CENSUS_SQL,
        'parameters': list(_CENSUS_PARAMETERS),
    }
    try:
        result = subprocess.run(
            [sys.executable, '-I', '-c', _CAPSULE_PROBE_SCRIPT, json.dumps(payload)],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, 'probe timeout exceeded'
    except OSError as exc:
        return None, f'probe process unavailable: {type(exc).__name__}: {exc}'
    stdout = result.stdout.strip().splitlines()
    if result.returncode != 0:
        return None, f'probe process exited {result.returncode}: {result.stderr.strip()}'
    if not stdout:
        return None, 'probe returned no JSON result'
    try:
        response = json.loads(stdout[-1])
    except json.JSONDecodeError as exc:
        return None, f'probe returned invalid JSON: {exc}'
    if not response.get('ok'):
        return None, f'candidate execution failed: {response.get("reason", "unknown failure")}'
    for call in response.get('calls', []):
        statement = call.get('statement')
        parameters = tuple(call.get('parameters', ()))
        if statement == _CENSUS_REWRITTEN_SQL and parameters == _CENSUS_PARAMETERS:
            return ObservedMemberEvidence(
                execute_owner=candidate.identity.execute_owner,
                statement=statement,
                parameters=parameters,
            ), None
    return None, None


def behavioral_paramstyle_census(root: Path) -> CensusReport:
    """Seal paramstyle behaviour using isolated AST capsules, not imports.

    The returned mapping is exact. A candidate that is DB-API-shaped but cannot
    be safely built or probed is a named failure; it is never silently converted
    into a non-finding. Diagnostics and failures are deliberately separate from
    observations so an incidental subprocess error cannot be mistaken for a
    killed mutation.
    """
    observations: dict[CandidateIdentity, ObservedMemberEvidence] = {}
    failures: list[CensusFailure] = []
    diagnostics: list[str] = []
    for candidate in _discover_capsule_candidates(root):
        try:
            capsule = _build_capsule(candidate)
        except _CapsuleRejected as exc:
            failures.append(CensusFailure(candidate.identity, str(exc)))
            continue
        evidence, reason = _probe_candidate(candidate, capsule)
        if reason is not None:
            failures.append(CensusFailure(candidate.identity, reason))
        elif evidence is None:
            diagnostics.append(f'no translation observed: {candidate.identity}')
        else:
            observations[candidate.identity] = evidence
    return CensusReport(
        observations=tuple(sorted(
            observations.items(),
            key=lambda item: (
                item[0].relative_path,
                item[0].qualified_class_name,
                item[0].execute_owner,
            ),
        )),
        failures=tuple(failures),
        diagnostics=tuple(diagnostics),
    )


def _mutation_has_positive_evidence(
    report: CensusReport,
    identity: CandidateIdentity,
) -> bool:
    """Judge a mutation from its own member evidence only."""
    evidence = report.mapping.get(identity)
    return bool(
        evidence is not None
        and evidence.execute_owner == identity.execute_owner
        and evidence.statement == _CENSUS_REWRITTEN_SQL
        and evidence.parameters == _CENSUS_PARAMETERS
    )


_BEHAVIOURAL_MUTATIONS: dict[str, str] = {
    'three_argument_replace': """class Cursor:
    def __init__(self, raw): self.raw = raw
    def execute(self, statement, parameters=()):
        self.raw.execute(statement.replace('%s', '?', -1), parameters)
""",
    'unbound_replace': """class Cursor:
    def __init__(self, raw): self.raw = raw
    def execute(self, statement, parameters=()):
        self.raw.execute(str.replace(statement, '%s', '?'), parameters)
""",
    'module_helper_hop': """def qmark(statement):
    return statement.replace('%s', '?')
class Cursor:
    def __init__(self, raw): self.raw = raw
    def execute(self, statement, parameters=()):
        self.raw.execute(qmark(statement), parameters)
""",
    're_sub': """import re
class Cursor:
    def __init__(self, raw): self.raw = raw
    def execute(self, statement, parameters=()):
        self.raw.execute(re.sub('%s', '?', statement), parameters)
""",
    'translation_table': """TABLE = {ord('%'): '?', ord('s'): None}
class Cursor:
    def __init__(self, raw): self.raw = raw
    def execute(self, statement, parameters=()):
        self.raw.execute(statement.translate(TABLE), parameters)
""",
    'init_lambda_binding': """class Cursor:
    def __init__(self, raw):
        self.raw = raw
        self.execute = lambda statement, parameters=(): raw.execute(statement.replace('%s', '?'), parameters)
""",
    'post_class_assignment': """class Cursor:
    def __init__(self, raw): self.raw = raw
def execute(self, statement, parameters=()):
    self.raw.execute(statement.replace('%s', '?'), parameters)
Cursor.execute = execute
""",
    'character_scanner': """class Cursor:
    def __init__(self, raw): self.raw = raw
    def execute(self, statement, parameters=()):
        out = []
        index = 0
        while index < len(statement):
            if statement[index:index + 2] == '%s': out.append('?'); index += 2
            else: out.append(statement[index]); index += 1
        self.raw.execute(''.join(out), parameters)
""",
}


class TestTheBehaviouralCensusIsTheSeal(unittest.TestCase):
    """The executable axis closes the shapes a source scan cannot enumerate."""

    def _root_with(self, source: str) -> tuple[tempfile.TemporaryDirectory, Path]:
        tmp = tempfile.TemporaryDirectory(prefix='paramstyle_behaviour_')
        root = Path(tmp.name)
        (root / 'tests').mkdir()
        (root / 'tests' / 'probe.py').write_text(source, encoding='utf-8')
        return tmp, root

    def test_repository_mapping_reads_the_member_evidence(self) -> None:
        report = behavioral_paramstyle_census(_REPO_ROOT)
        expected = CandidateIdentity(SHIM_PATH, 'QmarkCursor', 'QmarkCursor.execute')
        self.assertEqual((expected,), tuple(report.mapping))
        evidence = report.mapping[expected]
        self.assertEqual('X ?', evidence.statement)
        self.assertEqual(('census-parameter-7',), evidence.parameters)
        self.assertEqual((), report.failures)

    def test_all_eight_working_shapes_are_found_by_behaviour(self) -> None:
        applied: set[str] = set()
        survived: set[str] = set()
        for name, source in _BEHAVIOURAL_MUTATIONS.items():
            before = source.replace('?', '%s')
            self.assertNotEqual(before, source, name)
            applied.add(name)
            tmp, root = self._root_with(source)
            try:
                report = behavioral_paramstyle_census(root)
                self.assertEqual(1, len(report.mapping), f'{name}: {report}')
                identity = next(iter(report.mapping))
                if not _mutation_has_positive_evidence(report, identity):
                    survived.add(name)
            finally:
                tmp.cleanup()
        self.assertEqual(set(_BEHAVIOURAL_MUTATIONS), applied)
        self.assertEqual(set(), survived, f'applied={sorted(applied)} survived={sorted(survived)}')

    def test_negative_and_unprobeable_candidates_do_not_fail_open(self) -> None:
        source = """class RecorderOnly:
    def __init__(self, raw): self.raw = raw
    def execute(self, statement, parameters=()): self.raw.execute(statement, parameters)
class NotADriver:
    def execute(self, value): return value
class Hostile:
    def __init__(self, raw): self.raw = raw
    def execute(self, statement, parameters=()):
        open('must-not-exist', 'w')
        self.raw.execute(statement.replace('%s', '?'), parameters)
"""
        tmp, root = self._root_with(source)
        try:
            report = behavioral_paramstyle_census(root)
        finally:
            tmp.cleanup()
        self.assertEqual((), report.observations)
        self.assertTrue(any(f.identity.qualified_class_name == 'Hostile' for f in report.failures))
        self.assertFalse(any(f.identity.qualified_class_name == 'NotADriver' for f in report.failures))

    def test_duplicate_count_does_not_satisfy_identity_mapping(self) -> None:
        tmp, root = self._root_with(_BEHAVIOURAL_MUTATIONS['re_sub'])
        try:
            report = behavioral_paramstyle_census(root)
        finally:
            tmp.cleanup()
        wrong = CandidateIdentity('tests/probe.py', 'OtherCursor', 'OtherCursor.execute')
        self.assertNotIn(wrong, report.mapping)
        self.assertNotEqual(1, len(report.mapping) if wrong in report.mapping else 0)


class TestQmarkShimIsTheOnlyParamstyleShim(unittest.TestCase):
    """The identity argument only covers what shares the identity."""

    def test_the_repository_defines_exactly_one_translating_wrapper(self) -> None:
        offenders = [
            entry for entry in paramstyle_translating_definitions(_REPO_ROOT)
            if entry[0] != SHIM_PATH
        ]
        self.assertEqual(
            [], offenders,
            'a private paramstyle wrapper reappeared — import '
            f'{SHIM_PATH} instead, or say here why this one cannot: {offenders}',
        )

    def test_the_detector_is_a_nag_and_the_census_is_the_seal(self) -> None:
        """Say plainly which of the two axes actually holds the line.

        An independent review planted a *working* 15th private wrapper and
        measured which gate caught it: with an ordinary import the **raw-connect
        census** failed and this detector contributed nothing; with an unusual
        import spelling both went blind together (that half is now closed —
        ``test_the_census_finds_a_raw_connection_however_it_is_spelled``).

        So the honest statement is: **the census is the seal, this detector is a
        nag.** It exists to make a returning copy noisy at review time, not to
        prove one cannot exist — a syntactic scan cannot prove that, and this
        very file demonstrates why: the shim's own translation moved into
        ``_substitute_paramstyle`` (a character-wise scanner, no ``.replace``
        at all) and the detector correctly stopped matching it.

        This test asserts the *policy*, so a future reader cannot mistake the
        detector for a completeness proof: the shim's own module is exempt by
        path, and nothing else may match.
        """
        found = paramstyle_translating_definitions(_REPO_ROOT)
        self.assertEqual(
            [], [entry for entry in found if entry[0] != SHIM_PATH],
            f'only {SHIM_PATH} may translate paramstyle: {found}',
        )

    def test_the_scan_visits_every_python_file_under_its_roots(self) -> None:
        """A seal over an empty — or truncated — collection passes silently.

        ⚠️ This used to assert ``> 100`` files, which is a fact about *this*
        repository, not about the scan. The delivered ``fcc-test-contracts``
        package ships a subset of ``tests/`` and the assertion failed there for
        no defect at all. The property that actually matters is *the walk was
        not truncated*, so it is checked by deriving the same set a second,
        independent way (``os.walk``) and comparing — true in a full checkout
        and in a delivered box alike.
        """
        expected: set[str] = set()
        for scanned in SCANNED_ROOTS:
            base = _REPO_ROOT / scanned
            if not base.is_dir():
                continue
            for parent, _dirs, files in os.walk(base):
                for name in files:
                    if name.endswith('.py'):
                        expected.add(
                            (Path(parent) / name).relative_to(_REPO_ROOT).as_posix()
                        )
        walked = {
            path.relative_to(_REPO_ROOT).as_posix()
            for scanned in SCANNED_ROOTS
            if (_REPO_ROOT / scanned).is_dir()
            for path in (_REPO_ROOT / scanned).rglob('*.py')
        }
        self.assertEqual(expected, walked)
        # Non-vacuous in any tree that ships the subject: the shim is one of them.
        self.assertIn(SHIM_PATH, walked)

    def test_the_detector_fires_on_a_private_copy(self) -> None:
        """Non-vacuity, against a tree that really contains the shape."""
        with tempfile.TemporaryDirectory(prefix='paramstyle_offender_') as tmp:
            root = Path(tmp)
            (root / 'tests').mkdir()
            (root / 'tests' / 'probe.py').write_text(
                'class _QmarkCursor:\n'
                '    def __init__(self, raw):\n'
                '        self._raw = raw\n'
                '    def execute(self, statement, parameters=()):\n'
                "        self._raw.execute(statement.replace('%s', '?'), parameters)\n",
                encoding='utf-8',
            )
            self.assertEqual(
                (('tests/probe.py', '_QmarkCursor', 1),),
                paramstyle_translating_definitions(root),
            )

    def test_the_detector_sees_a_concatenated_literal(self) -> None:
        """C-2: a bare ``ast.Constant`` check would miss this spelling."""
        with tempfile.TemporaryDirectory(prefix='paramstyle_concat_') as tmp:
            root = Path(tmp)
            (root / 'tests').mkdir()
            (root / 'tests' / 'probe.py').write_text(
                'class _Sneaky:\n'
                '    def execute(self, statement):\n'
                "        return statement.replace('%' + 's', '?')\n",
                encoding='utf-8',
            )
            self.assertEqual(
                (('tests/probe.py', '_Sneaky', 1),),
                paramstyle_translating_definitions(root),
            )

    def test_the_detector_ignores_an_inline_rewrite_in_a_test_method(self) -> None:
        """A call-site rewrite inside a test is not an object claiming to be a driver.

        This is the shape the real tree actually has — nine sites, every one of
        them a ``TestCase`` method asserting production SQL against a DDL
        fixture. Flagging them would make the detector a nuisance, and a
        nuisance detector gets deleted along with its real findings.
        """
        with tempfile.TemporaryDirectory(prefix='paramstyle_inline_') as tmp:
            root = Path(tmp)
            (root / 'tests').mkdir()
            (root / 'tests' / 'probe.py').write_text(
                'import unittest\n'
                'class TestSqlAgainstDdl(unittest.TestCase):\n'
                '    def test_it(self):\n'
                "        sql = SEARCH_SQL.replace('%s', '?')\n"
                '        self.assertTrue(sql)\n',
                encoding='utf-8',
            )
            self.assertEqual((), paramstyle_translating_definitions(root))

    def test_the_detector_follows_the_helper_hop(self) -> None:
        """A module-level ``_qmark()`` is the same debt with one extra hop.

        An independent review hid a working copy behind exactly this hop while
        both gates stayed green. Measured on the real tree, catching it costs
        **zero** false positives — the nine legitimate rewrites are all inside
        test methods, never at module level.
        """
        with tempfile.TemporaryDirectory(prefix='paramstyle_helper_') as tmp:
            root = Path(tmp)
            (root / 'tests').mkdir()
            (root / 'tests' / 'probe.py').write_text(
                'def _qmark(statement):\n'
                "    return statement.replace('%s', '?')\n"
                'class _Cursor:\n'
                '    def __init__(self, raw):\n'
                '        self._raw = raw\n'
                '    def execute(self, statement, parameters=()):\n'
                '        self._raw.execute(_qmark(statement), parameters)\n',
                encoding='utf-8',
            )
            self.assertEqual(
                (('tests/probe.py', '_qmark', 1),),
                paramstyle_translating_definitions(root),
            )

    def test_the_detector_sees_a_three_argument_replace(self) -> None:
        """``replace('%s', '?', -1)`` is identical in meaning and was missed."""
        with tempfile.TemporaryDirectory(prefix='paramstyle_three_') as tmp:
            root = Path(tmp)
            (root / 'tests').mkdir()
            (root / 'tests' / 'probe.py').write_text(
                'class _Cursor:\n'
                '    def execute(self, statement, parameters=()):\n'
                "        return statement.replace('%s', '?', -1)\n",
                encoding='utf-8',
            )
            self.assertEqual(
                (('tests/probe.py', '_Cursor', 1),),
                paramstyle_translating_definitions(root),
            )


# ⚠️ The claim *"the retired evidence rules are gone from the ratchet's
# vocabulary"* deliberately does **not** live here. It lives in
# ``tests/test_wal_checkpoint_durability.py``, next to the vocabulary it is
# about. Measured reason: lane attribution files this file under
# ``fcc-test-contracts`` (with the shim it tests) and the ratchet under
# ``fcc-unlicensed-headless``, so the delivered contracts box does not contain
# the ratchet at all — the assertion failed there for a file it could not see,
# and a box is not allowed to grow a new failure. An assertion belongs in the
# box that ships its subject.
class _ForgetfulCursor(QmarkCursor):
    """A subclass whose dialect seam forgets to do anything — the mutation, in-tree.

    Under the previous design (one overridable ``translate`` doing both halves)
    this class produced untranslated SQL and was caught by a post-condition
    ``assert``. It now cannot: paramstyle substitution is applied by
    :meth:`QmarkCursor._run` through a module-level function, so an override
    loses a *concession* and never the placeholders.
    """

    def translate_dialect(self, statement: str) -> str:
        return statement


class TestTheShimTranslates(unittest.TestCase):
    """Behaviour, against a real engine — with the control that gives it meaning."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix='qmark_shim_')
        self.db_path = str(Path(self._tmp.name) / 'central.sqlite3')
        self.conn = QmarkConnection(self.db_path)
        cursor = self.conn.cursor()
        cursor.execute('CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)')
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_a_psycopg_statement_round_trips(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute('INSERT INTO t (id, v) VALUES (%s, %s)', ('a', 'one'))
        self.conn.commit()
        cursor.execute('SELECT v FROM t WHERE id = %s', ('a',))
        self.assertEqual([('one',)], cursor.fetchall())

    def test_the_raw_engine_rejects_the_untranslated_form(self) -> None:
        """The control. Without it the positive above would also pass if SQLite
        happened to accept ``%s``, i.e. it would not be evidence of translation."""
        raw = SqliteConnectionFactory(self.db_path).create()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                raw.execute('INSERT INTO t (id, v) VALUES (%s, %s)', ('b', 'two'))
        finally:
            raw.close()

    def test_an_override_cannot_lose_the_paramstyle(self) -> None:
        """Construction, not assertion — the strongest form this property has.

        Overriding the seam is the same defect the retired validator could not
        see: an override changes what ``obj.execute`` resolves *through*. The
        earlier design caught it with a post-condition ``assert``; two
        independent findings killed that (an ``assert`` is deleted by
        ``python -O``, and the check cannot be a pure function of the output
        once ``%%`` may legitimately produce a literal ``%s``). So the
        substitution no longer goes through ``self`` at all, and the forgetful
        subclass below simply *works*.
        """
        raw = SqliteConnectionFactory(self.db_path).create()
        try:
            cursor = _ForgetfulCursor(raw.cursor())
            cursor.execute('INSERT INTO t (id, v) VALUES (%s, %s)', ('c', 'three'))
            raw.commit()
            cursor.execute('SELECT v FROM t WHERE id = %s', ('c',))
            self.assertEqual([('three',)], cursor.fetchall())
            # ...and it really is the forgetful one: the dialect concession is gone.
            self.assertIn('now()', cursor.translate('UPDATE t SET v = now()'))
        finally:
            raw.close()

    def test_the_postgres_concessions_still_apply(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute('INSERT INTO t (id, v) VALUES (%s, now())', ('d',))
        self.conn.commit()
        cursor.execute('SELECT v FROM t WHERE id = %s FOR UPDATE', ('d',))
        self.assertEqual(1, len(cursor.fetchall()))


class TestTheTranslationIsSubstringSafe(unittest.TestCase):
    """A literal ``%`` must survive, and ``now()`` must not eat an identifier.

    Both were **silent** wrongness — the statement reaching the engine was
    valid SQL that returned different rows. The execute-time post-condition
    cannot see either, because from its point of view the ``%s`` really was
    consumed. Found by an independent adversarial review; sealed here because
    the shim is now the single owner and 34 consumers inherit it.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix='qmark_substring_')
        self.db_path = str(Path(self._tmp.name) / 'central.sqlite3')
        self.conn = QmarkConnection(self.db_path)
        cursor = self.conn.cursor()
        cursor.execute('CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)')
        cursor.execute('INSERT INTO t (id, v) VALUES (%s, %s)', ('a', 'sample'))
        cursor.execute('INSERT INTO t (id, v) VALUES (%s, %s)', ('b', 'know()'))
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_a_percent_escape_becomes_one_literal_percent(self) -> None:
        """psycopg spells a literal percent ``%%``. It must arrive as ``%``."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM t WHERE v LIKE '%%sample'")
        self.assertEqual([('a',)], cursor.fetchall())

    def test_percent_s_is_a_placeholder_even_when_a_word_follows(self) -> None:
        """Faithful to psycopg, which is the point of a shim.

        ⚠️ An independent review reported ``LIKE '%sample'`` -> ``LIKE '?ample'``
        as corruption. It is not: psycopg reads the same two characters as a
        placeholder, and the correct psycopg spelling for a literal percent is
        ``%%``. Diverging here would make the shim disagree with the driver it
        stands in for — the failure mode a test double exists to avoid. What
        *was* a real defect is the escape, sealed above.
        """
        self.assertEqual(
            "SELECT v FROM t WHERE v LIKE '?ample'",
            self.conn.cursor().translate("SELECT v FROM t WHERE v LIKE '%sample'"),
        )

    def test_placeholders_still_translate_next_to_an_escape(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM t WHERE v LIKE '%%sam' || %s", ('ple',))
        self.assertEqual([('a',)], cursor.fetchall())

    def test_now_does_not_rewrite_the_tail_of_an_identifier(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM t WHERE v = %s', ('know()',))
        self.assertEqual([('b',)], cursor.fetchall())

    def test_a_real_now_call_is_still_rewritten(self) -> None:
        """The concession itself must not be lost to the word anchor."""
        self.assertIn(
            'CURRENT_TIMESTAMP',
            self.conn.cursor().translate('UPDATE t SET v = now() WHERE id = %s'),
        )


class TestCursorCloseActuallyCloses(unittest.TestCase):
    """Making ``QmarkCursor.close`` a no-op survived a 1005-test consumer run.

    A wrapper that silently stops releasing cursors leaks them for as long as
    the connection lives, and no consumer notices because SQLite is forgiving.
    Cheap to hold, and the sort of thing that is never noticed until a fixture
    holds thousands.
    """

    def test_the_raw_cursor_is_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix='qmark_close_') as tmp:
            conn = QmarkConnection(str(Path(tmp) / 'x.sqlite3'))
            try:
                cursor = conn.cursor()
                cursor.execute('CREATE TABLE t (id TEXT)')
                cursor.close()
                with self.assertRaises(sqlite3.ProgrammingError):
                    cursor.execute('SELECT 1')
            finally:
                conn.close()


class TestTheForUpdateStripIsAnchored(unittest.TestCase):
    """The comment calls the anchoring a safety property. Nothing tested it.

    Un-anchoring the regex is a mutation that survived a full 1005-test
    consumer run — a documented invariant with zero enforcement, in the file
    whose whole thesis is "the identity we tested".
    """

    def test_a_literal_containing_the_words_is_not_clipped(self) -> None:
        statement = (
            "SELECT id FROM t WHERE note = 'queued FOR UPDATE' AND x = %s"
        )
        self.assertEqual(
            "SELECT id FROM t WHERE note = 'queued FOR UPDATE' AND x = ?",
            QmarkCursor(None).translate(statement),
        )

    def test_a_trailing_clause_is_still_stripped(self) -> None:
        for tail in ('FOR UPDATE', 'FOR UPDATE NOWAIT', 'FOR UPDATE SKIP LOCKED'):
            with self.subTest(tail=tail):
                self.assertEqual(
                    'SELECT id FROM t WHERE x = ?',
                    QmarkCursor(None).translate(f'SELECT id FROM t WHERE x = %s {tail}'),
                )


class TestTheGuaranteeSurvivesOptimisedMode(unittest.TestCase):
    """``python -O`` strips ``assert``. The guarantee must not be one.

    Measured by an independent review: under ``-O`` the old post-condition
    vanished and untranslated SQL fell through to the engine. The repair is not
    a louder assertion — it is that the substitution no longer goes through an
    overridable seam, so there is nothing for ``-O`` to remove.
    """

    def test_translation_still_happens_with_assertions_disabled(self) -> None:
        source = _REPO_ROOT / SHIM_PATH
        result = subprocess.run(
            [
                sys.executable, '-O', '-c',
                'import sqlite3, sys; sys.path[:0] = [%r, %r]\n'
                'from support.central_pg_sqlite_shim import QmarkCursor\n'
                'class Forgetful(QmarkCursor):\n'
                '    def translate_dialect(self, statement):\n'
                '        return statement\n'
                'raw = sqlite3.connect(":memory:")\n'
                'raw.execute("CREATE TABLE t (id TEXT)")\n'
                'c = Forgetful(raw.cursor())\n'
                'c.execute("INSERT INTO t (id) VALUES (%%s)", ("a",))\n'
                'c.execute("SELECT id FROM t WHERE id = %%s", ("a",))\n'
                'print("OK" if c.fetchall() == [("a",)] else "BAD")\n'
                % (str(_REPO_ROOT / 'src'), str(_REPO_ROOT / 'tests')),
            ],
            capture_output=True, cwd=str(_REPO_ROOT), timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr.decode('utf-8', 'replace'))
        self.assertIn(
            'OK', result.stdout.decode('utf-8', 'replace'),
            'translation did not happen under python -O — source: ' + str(source),
        )


class TestRowcountIsDelegated(unittest.TestCase):
    """``-1`` forever is not "unknown" — it is a driver that can never answer."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix='qmark_rowcount_')
        self.db_path = str(Path(self._tmp.name) / 'central.sqlite3')
        self.conn = QmarkConnection(self.db_path)
        cursor = self.conn.cursor()
        cursor.execute('CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)')
        for key in ('a', 'b', 'c'):
            cursor.execute('INSERT INTO t (id, v) VALUES (%s, %s)', (key, 'old'))
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_an_update_reports_the_rows_it_touched(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute('UPDATE t SET v = %s WHERE id IN (%s, %s)', ('new', 'a', 'b'))
        self.assertEqual(2, cursor.rowcount)

    def test_an_update_that_matches_nothing_reports_zero(self) -> None:
        """The branch a pinned ``-1`` silently deleted: adapters read ``== 0``
        to tell "no such row" from "updated"."""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE t SET v = %s WHERE id = %s', ('new', 'zzz'))
        self.assertEqual(0, cursor.rowcount)

    def test_a_blind_cursor_reports_minus_one_and_still_translates(self) -> None:
        conn = RowcountBlindConnection(self.db_path)
        try:
            cursor = conn.cursor()
            self.assertIsInstance(cursor, RowcountBlindCursor)
            cursor.execute('UPDATE t SET v = %s WHERE id = %s', ('new', 'a'))
            self.assertEqual(-1, cursor.rowcount)
            cursor.execute('SELECT v FROM t WHERE id = %s', ('a',))
            self.assertEqual([('new',)], cursor.fetchall())
        finally:
            conn.close()


class TestTheConnectionCarriesTheProjectBaseline(unittest.TestCase):
    """The shim is not a second raw-``sqlite3.connect`` entry point.

    This is the property that took the eight fixtures out of the ratchet's
    census: they no longer open connections themselves, so there is nothing to
    grant an exemption to.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix='qmark_pragma_')
        self.db_path = str(Path(self._tmp.name) / 'central.sqlite3')

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_the_factory_pragmas_are_applied(self) -> None:
        conn = QmarkConnection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('PRAGMA foreign_keys')
            self.assertEqual([(1,)], cursor.fetchall())
            cursor.execute('PRAGMA busy_timeout')
            self.assertEqual([(SQLITE_BUSY_TIMEOUT_MS,)], cursor.fetchall())
            cursor.execute('PRAGMA journal_mode')
            self.assertEqual([('wal',)], cursor.fetchall())
        finally:
            conn.close()

    def test_the_shim_module_opens_no_raw_connection(self) -> None:
        """Derived from the module source, not from this file's memory of it."""
        tree = ast.parse((_REPO_ROOT / SHIM_PATH).read_text(encoding='utf-8'))
        raw_connects = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'connect'
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'sqlite3'
        ]
        self.assertEqual([], raw_connects)


class TestAdoptedConnectionOwnership(unittest.TestCase):
    """Wrapping a caller-owned connection must not close it."""

    def test_close_is_a_no_op_and_the_connection_survives(self) -> None:
        raw = SqliteConnectionFactory(':memory:').create()
        try:
            raw.execute('CREATE TABLE t (id TEXT)')
            adopted = AdoptedQmarkConnection(raw)
            cursor = adopted.cursor()
            cursor.execute('INSERT INTO t (id) VALUES (%s)', ('a',))
            adopted.close()
            # Still usable — the wrapper closed nothing.
            self.assertEqual([('a',)], raw.execute('SELECT id FROM t').fetchall())
        finally:
            raw.close()

    def test_an_owning_connection_does_close(self) -> None:
        """The contrast that makes the no-op above a decision rather than a bug."""
        with tempfile.TemporaryDirectory(prefix='qmark_owned_') as tmp:
            conn = QmarkConnection(str(Path(tmp) / 'x.sqlite3'))
            conn.close()
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.cursor()


if __name__ == '__main__':
    unittest.main()
