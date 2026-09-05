"""Which contract is this — as a value that moves when the contract moves.

⚠️ **The version string is not that value.** Measured 2026-09-04: the SSOT
artifact carried ``version == '1.0.0'`` on both 2026-08-31 (39 operations) and
2026-09-04 (40 operations, ``get_published_test_plan`` added in ``5151e2c``).
A conformance result keyed to the version string therefore cannot distinguish
*"checked against the contract you are serving"* from *"checked against a
contract that has since changed"* — the two states have the same value on that
axis, which is the defect class ``check-axis-blindness.md`` names.

This module supplies the axis that does move: a digest over the contract
document in the **same canonical form the checker compares**.

That last clause is the whole design. :func:`contract_comparison_document` is
not a private helper of this module — it is the form
:func:`check_api_contract_compatibility` reduces both sides to before comparing,
and the checker now calls it. One definition, two consumers. Written the other
way (a digest that strips ``provider`` "the same way" the checker does) there
would be two definitions of *"the same contract"*, and the day they diverge
neither says so.
"""
from __future__ import annotations

import hashlib
import json

__all__ = [
    'CONTRACT_IDENTITY_ALGORITHM',
    'FeatureScopeError',
    'contract_comparison_document',
    'contract_identity',
    'contract_identity_digest',
    'feature_scoped_document',
    'feature_scoped_identity',
]


class FeatureScopeError(ValueError):
    """A declared feature is not one this contract document declares."""

#: Named in the evidence document rather than assumed, so a future change of
#: algorithm is a value a reader can see rather than a silent reinterpretation
#: of the same field.
CONTRACT_IDENTITY_ALGORITHM = 'sha256'


def contract_comparison_document(document: dict) -> dict:
    """The contract document reduced to what compatibility actually compares.

    ``provider`` is dropped. It carries *who serves this contract*, not *what
    the contract is*, and every provider is expected to differ there — a
    provider block that participated in the comparison would make every foreign
    contract incompatible by construction.
    """
    return {key: value for key, value in document.items() if key != 'provider'}


def contract_identity_digest(document: dict) -> str:
    """Digest of ``document`` in the canonical comparison form.

    Deterministic across processes and machines: keys sorted, non-ASCII escaped,
    no incidental whitespace. Two documents that the checker would call the same
    contract produce the same digest, and any change the checker would report
    produces a different one.
    """
    canonical = json.dumps(
        contract_comparison_document(document),
        sort_keys=True,
        ensure_ascii=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def contract_identity(document: dict) -> dict:
    """The identity block an evidence document carries.

    ``operations`` is present for a human reading a diff and is **not** a
    judgement axis — the digest is. Recording it alongside follows
    ``check-axis-blindness.md`` §*값은 옮겨지고 조건은 안 옮겨진다*: a count that
    travels without the predicate that produced it is not a measurement, and the
    digest is that predicate made explicit.
    """
    return {
        'algorithm': CONTRACT_IDENTITY_ALGORITHM,
        'digest': contract_identity_digest(document),
        'operations': len(document.get('operations') or {}),
    }


def _schema_closure(names: set[str], schemas: dict) -> set[str]:
    """Every schema reachable from ``names`` through ``$ref``."""
    reached: set[str] = set()
    pending = [name for name in names if name]
    while pending:
        name = pending.pop()
        if name in reached or name not in schemas:
            continue
        reached.add(name)
        stack = [schemas[name]]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                ref = node.get('$ref')
                if isinstance(ref, str):
                    pending.append(ref.rsplit('/', 1)[-1])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return reached


def feature_scoped_document(document: dict, declared_features) -> dict:
    """``document`` reduced to the features a provider says it serves.

    The judgement §6.6 designed compares one digest against another. That works
    only while both sides describe the same surface — and after §6.7 they do
    not: a provider that legitimately serves a subset would have to reproduce
    operations it never implemented in order to match a whole-contract digest.
    Scoping the document to the declared features restores the comparison
    without weakening it, because BOTH sides are reduced by this same function
    (the caller passes the provider's declaration; the centre recomputes from
    its own SSOT).

    In scope: every ``required`` feature — always, whatever was declared — plus
    the declared ones. Routes and operations are filtered to that set; schemas
    are filtered to the ``$ref`` closure reachable from those operations, so a
    provider is not digesting shapes it never serves; the ``features`` block is
    filtered likewise.

    ⚠️ ``provider`` is dropped here too, by :func:`contract_comparison_document`.
    Scoping is a second reduction, not a replacement for the first.
    """
    features = document.get('features') or {}
    declared = set(declared_features or ())
    unknown = sorted(declared - set(features))
    if unknown:
        raise FeatureScopeError(
            f'declared features this contract does not declare: {unknown}'
        )
    in_scope = declared | {
        feature_id
        for feature_id, properties in features.items()
        if (properties or {}).get('required')
    }

    operations = document.get('operations') or {}
    scoped_operations = {
        name: operation
        for name, operation in operations.items()
        if operation.get('feature') in in_scope
    }
    schemas = document.get('schemas') or {}
    reachable = _schema_closure(
        {
            name
            for operation in scoped_operations.values()
            for name in (operation.get('request'), operation.get('response'))
            if name
        },
        schemas,
    )

    scoped = dict(contract_comparison_document(document))
    scoped['operations'] = scoped_operations
    scoped['routes'] = {
        name: route
        for name, route in (document.get('routes') or {}).items()
        if name in scoped_operations
    }
    scoped['schemas'] = {
        name: schema for name, schema in schemas.items() if name in reachable
    }
    scoped['features'] = {
        feature_id: properties
        for feature_id, properties in features.items()
        if feature_id in in_scope
    }
    return scoped


def feature_scoped_identity(document: dict, declared_features) -> dict:
    """The identity block for a provider that serves ``declared_features``.

    ``features`` is carried alongside the digest for the same reason
    ``operations`` is: so a human reading a mismatch can see WHICH surface the
    two sides thought they were comparing. The digest remains the only
    judgement axis.
    """
    scoped = feature_scoped_document(document, declared_features)
    canonical = json.dumps(
        scoped, sort_keys=True, ensure_ascii=True, separators=(',', ':')
    )
    return {
        'algorithm': CONTRACT_IDENTITY_ALGORITHM,
        'digest': hashlib.sha256(canonical.encode('utf-8')).hexdigest(),
        'operations': len(scoped.get('operations') or {}),
        'features': sorted(scoped.get('features') or {}),
    }
