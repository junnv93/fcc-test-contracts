"""What may appear as a resource identifier in a route path — and why not a PK.

A path parameter is the most public thing an API has: it is in the URL, in
logs, in bookmarks, in bug reports. Two industry authorities say the same thing
about what belongs there, and they say it for different reasons, which is why
both are cited rather than one:

* **OWASP API Security Top 10 2023, API1:2023 (Broken Object Level
  Authorization)** — *"Prefer the use of random and unpredictable values as
  GUIDs for records' IDs."* A sequential identifier is enumerable, so the only
  thing standing between a caller and every other record is the authorization
  check — and BOLA is the top entry on that list precisely because that check
  is the one most often missing or incomplete.
* **Zalando RESTful API Guidelines, Rule 174** — *"IDs must be opaque strings
  and not numbers. IDs are unique within some documented context, are stable
  and don't change for a given object once assigned."* Rule 144 gives the
  second reason: sequential numeric ids *"may reveal critical, confidential
  business information, like order volume, to non-privileged clients."*

That second reason is not abstract here. ``measurement_jobs.id`` is
``INTEGER PRIMARY KEY AUTOINCREMENT``, so its value is **the number of
measurement jobs the laboratory has ever run.** For an EMC test house that is
commercial information, and it was being handed to every caller of
``POST /headless/jobs``.

And a third reason is local to this contract, measured 2026-09-05 by the KC
lane: **a per-provider integer is not unique across providers.** KC's job 1 and
FCC's job 1 are different things wearing the same name, and the day the centre
aggregates a queue across providers those two collide. ``job_uuid`` was already
in the schema — unique-indexed in migration 006 — because that problem was
foreseen; it simply was not the value the route took.

⚠️ **The rule is enforced, and what does not yet satisfy it is named.**
:data:`INTEGER_IDENTIFIER_GRANDFATHER` is a ratchet, not an exemption list: it
may shrink and never grow. Three path parameters are still integers and each is
a live surface nobody has raised — renaming them in the same commit that
repaired ``job_id`` would be three unannounced wire breaks riding along with
one decided change. Naming them is what makes them findable; the ratchet is
what stops a fourth from joining quietly.
"""
from __future__ import annotations

__all__ = [
    'INTEGER_IDENTIFIER_GRANDFATHER',
    'PathIdentifierPolicyError',
    'validate_path_identifier_policy',
]


class PathIdentifierPolicyError(ValueError):
    """A route path takes an identifier the policy does not allow."""


#: Path parameters that are still integers, with the reason each has not moved.
#: ⚠️ Ratchet — :func:`validate_path_identifier_policy` refuses any addition.
#: Removing one is the deliberate edit; it means the surface was migrated.
INTEGER_IDENTIFIER_GRANDFATHER: dict[str, str] = {
    'session_id': (
        'A measurement session is created by measuring, not by an operation, '
        'and its id is referenced by five read routes plus the report submit. '
        'Migrating it is its own wave with its own consumers.'
    ),
    'request_id': (
        'Report-automation request ids address four routes including the '
        'download-grant flow, which no provider serves today — the migration '
        'is cheap but it belongs to whoever brings that axis up.'
    ),
    'draft_row_id': (
        'The stable AUTOINCREMENT row handle (test_plan_draft_rows.id). It is '
        'a child identifier scoped by {draft_id}, so it is not enumerable '
        'without already holding an opaque parent id — the weakest case of the '
        'three, and the last that should move.'
    ),
}


def validate_path_identifier_policy(path_params: dict) -> None:
    """Refuse a contract that adds a new numeric path identifier.

    Called at import from ``api_contract_surfaces`` rather than left to a test,
    for the same reason ``DuplicateContractKeyError`` is: a new integer path
    parameter builds a valid artifact and resolves a valid route. The only
    witness would be the enumeration it enables.
    """
    numeric = {
        name
        for name, schema in path_params.items()
        if (schema or {}).get('type') == 'integer'
    }
    added = sorted(numeric - set(INTEGER_IDENTIFIER_GRANDFATHER))
    if added:
        raise PathIdentifierPolicyError(
            f'new integer path identifiers: {added} — path identifiers must be '
            'opaque strings (OWASP API1:2023; Zalando RESTful API Guidelines '
            'rule 174). If this genuinely cannot be an opaque string, add it to '
            'INTEGER_IDENTIFIER_GRANDFATHER with the reason, and understand '
            'that the ratchet exists to make that an argument rather than a '
            'default.'
        )
    departed = sorted(set(INTEGER_IDENTIFIER_GRANDFATHER) - set(path_params))
    if departed:
        raise PathIdentifierPolicyError(
            f'grandfathered identifiers no route takes: {departed} — the '
            'surface migrated; remove them from the ratchet so it keeps '
            'shrinking'
        )
    still_numeric = sorted(set(INTEGER_IDENTIFIER_GRANDFATHER) - numeric)
    if still_numeric:
        raise PathIdentifierPolicyError(
            f'grandfathered identifiers that are no longer integers: '
            f'{still_numeric} — they were migrated; shrink the ratchet'
        )
