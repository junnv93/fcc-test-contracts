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
    'contract_comparison_document',
    'contract_identity',
    'contract_identity_digest',
]

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
