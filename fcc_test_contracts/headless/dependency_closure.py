"""Which operations an operation cannot be served without — derived, not listed.

§6.7.1 of the KC provider identity judgement asked what makes a *legal* subset
of the contract, and answered with three arms: core is present, the declaration
matches the surface, and **the dependency closure holds** — *"serve publish and
you must serve create"*. Only the third arm has teeth: the first two compare a
provider to itself, so a provider that declares nothing and serves nothing
passes them both.

The closure is not a hand-written table. A hand-written table is a second
authority that drifts from the routes it describes, and this repository has
measured that failure five times over in one artifact alone. It is derived:

    consumption   a route path containing ``{x}`` requires ``x``
    production    an operation whose response declares ``x`` at top level,
                  under a write method, and that does not itself take ``x``
                  from the path, is a minimal producer of ``x``

⚠️ **Both narrowings in the production rule are load-bearing**, and each was
added because the wider rule was measured and found unsound:

* *does not take it from the path* — otherwise ``get_test_plan_draft`` produces
  ``draft_id``, which is handing back what it was given, not making one.
* *top level, not the whole $ref closure* — otherwise ``get_published_test_plan``
  produces ``project_id`` and ``draft_id``, because a published plan mentions
  the project it belongs to and the draft it came from. A nested occurrence is a
  reference to something else's identity.
* *a write method* — otherwise ``list_test_plan_drafts`` produces ``draft_id``,
  and a provider could satisfy the closure for ``publish_test_plan_draft`` while
  having no way to bring a draft into existence. Listing is discovery; creation
  is a write.

With all three, the derivation reproduces the judgement's worked example
exactly: the minimal producers of ``draft_id`` are ``create_test_plan_draft``
and ``import_test_plan``, and no others.

Identifiers are then classed in **four** ways, because "has no producer" has
four different meanings and a closure that cannot tell them apart is either
vacuous or refuses every provider:

    provider_produced   the provider makes it. The closure REQUIRES a producer.
    external            it arrives from outside the headless surface. Exempt.
                        ⚠️ Without this, every provider is red — there is no
                        operation that creates a project, because central owns
                        projects.
    side_effect         it comes into existence when something runs. Exempt.
                        No operation creates a measurement session; measuring
                        does.
    defect              it has no producer because a name does not line up, and
                        that is a bug in this contract rather than a fact about
                        providers. ⚠️ Currently EMPTY — the one member was
                        repaired the day the class was written.

⚠️ ``defect`` is **not an exemption.** :data:`DEFECT_IDENTIFIERS` is a ratchet:
:func:`validate_identifier_classes` refuses a contract in which the set has
grown, so a new naming mismatch cannot be absorbed by classifying it. Shrinking
it — fixing one — is a deliberate edit here. Written any other way, the class
declaration becomes the place defects go to be legitimised, which is the
failure §6.7.2 named when it required defects to be repaired *before* the
classes are relied on.
"""
from __future__ import annotations

import re

from fcc_test_contracts.headless.api_contract_constants import (
    HEADLESS_API_PATH_PARAMS,
)

__all__ = [
    'DEFECT_IDENTIFIERS',
    'IDENTIFIER_CLASSES',
    'IDENTIFIER_CLASS_DEFECT',
    'IDENTIFIER_CLASS_EXTERNAL',
    'IDENTIFIER_CLASS_PROVIDER_PRODUCED',
    'IDENTIFIER_CLASS_SIDE_EFFECT',
    'IdentifierClassError',
    'closure_issues',
    'consumed_identifiers',
    'identifier_producers',
    'validate_identifier_classes',
]

IDENTIFIER_CLASS_PROVIDER_PRODUCED = 'provider_produced'
IDENTIFIER_CLASS_EXTERNAL = 'external'
IDENTIFIER_CLASS_SIDE_EFFECT = 'side_effect'
IDENTIFIER_CLASS_DEFECT = 'defect'

_WRITE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
_PATH_PARAM = re.compile(r'\{(\w+)\}')


class IdentifierClassError(ValueError):
    """The identifier classes and the contract surface disagree."""


#: Every path parameter, classed. Keys must be exactly
#: ``HEADLESS_API_PATH_PARAMS`` — :func:`validate_identifier_classes` checks it,
#: so a new path parameter cannot slip in unclassed and be silently exempt.
IDENTIFIER_CLASSES: dict[str, str] = {
    'draft_id': IDENTIFIER_CLASS_PROVIDER_PRODUCED,
    'draft_row_id': IDENTIFIER_CLASS_PROVIDER_PRODUCED,
    'generation_job_id': IDENTIFIER_CLASS_PROVIDER_PRODUCED,
    'plan_id': IDENTIFIER_CLASS_PROVIDER_PRODUCED,
    'request_id': IDENTIFIER_CLASS_PROVIDER_PRODUCED,
    # Central owns projects. No headless operation creates one and none should:
    # a provider that could mint project ids would be authoring central's
    # identity space.
    'project_id': IDENTIFIER_CLASS_EXTERNAL,
    # A session is what a measurement leaves behind. The contract has no
    # "create session" operation because there is no such act — running is.
    'session_id': IDENTIFIER_CLASS_SIDE_EFFECT,
    # ⚠️ ``job_uuid``, not ``job_id``. Until 2026-09-05 the measurement route
    # took ``{job_id}`` and no operation produced a field of that name — submit
    # returned the storage PK as ``id`` and stop echoed ``job_id`` — so a client
    # could not learn mechanically where the value in the path comes from, and a
    # consumer choosing wrongly between the two got a 404. The repair moved the
    # route to the opaque handle the schema already carried; see
    # ``path_identifier_policy`` for the standards it follows.
    'job_uuid': IDENTIFIER_CLASS_PROVIDER_PRODUCED,
}


#: The ratchet. Grows ⇒ red; see the module docstring.
#:
#: ⚠️ **Empty, and that is a state to defend rather than a state to assume.**
#: It held ``job_id`` for part of 2026-09-05 — a defect that had been invisible
#: while a second axis published a field of the same name, and that became
#: visible the moment that collision was repaired. An empty ratchet does not
#: mean the derivation found nothing; it means everything it found was fixed.
DEFECT_IDENTIFIERS: frozenset[str] = frozenset()


def consumed_identifiers(operation_id: str, routes: dict) -> frozenset[str]:
    """The identifiers ``operation_id`` cannot be called without."""
    _method, path = routes[operation_id]
    return frozenset(_PATH_PARAM.findall(path))


def _top_level_properties(schema_name: str | None, schemas: dict) -> frozenset[str]:
    schema = schemas.get(schema_name) if schema_name else None
    return frozenset((schema or {}).get('properties') or {})


def identifier_producers(
    operations: dict,
    routes: dict,
    schemas: dict,
) -> dict[str, tuple[str, ...]]:
    """identifier -> the operations that can bring one into existence."""
    producers: dict[str, list[str]] = {name: [] for name in HEADLESS_API_PATH_PARAMS}
    for operation_id in sorted(operations):
        method, _path = routes[operation_id]
        if method not in _WRITE_METHODS:
            continue
        consumed = consumed_identifiers(operation_id, routes)
        declared = _top_level_properties(
            operations[operation_id].get('response'), schemas
        )
        for identifier in producers:
            if identifier in declared and identifier not in consumed:
                producers[identifier].append(operation_id)
    return {name: tuple(found) for name, found in producers.items()}


def validate_identifier_classes(
    operations: dict,
    routes: dict,
    schemas: dict,
) -> None:
    """Refuse a contract whose classes and derivation have come apart.

    ⚠️ This is a declaration checked against a derivation, not a derivation
    checked against a derivation. The classes are written by hand in this
    module; the producers are read out of the routes and schemas. That is the
    whole value — two things that agree because they were built the same way
    agree by construction and say nothing (measured: five byte-identical copies
    of one artifact, all five stale).
    """
    unclassed = sorted(set(HEADLESS_API_PATH_PARAMS) - set(IDENTIFIER_CLASSES))
    if unclassed:
        raise IdentifierClassError(
            f'path parameters with no identifier class: {unclassed}'
        )
    stale = sorted(set(IDENTIFIER_CLASSES) - set(HEADLESS_API_PATH_PARAMS))
    if stale:
        raise IdentifierClassError(
            f'identifier classes for parameters no route takes: {stale}'
        )

    producers = identifier_producers(operations, routes, schemas)

    # A provider_produced identifier with no producer is not a class we can
    # judge against — it is an unnamed defect.
    unproducible = sorted(
        identifier
        for identifier, found in producers.items()
        if not found
        and IDENTIFIER_CLASSES[identifier] == IDENTIFIER_CLASS_PROVIDER_PRODUCED
    )
    if unproducible:
        raise IdentifierClassError(
            'identifiers classed provider_produced that no operation produces: '
            f'{unproducible} — either a producer is missing or the name does '
            'not line up; class it as a defect and add it to '
            'DEFECT_IDENTIFIERS deliberately'
        )

    declared_defects = sorted(
        identifier
        for identifier, klass in IDENTIFIER_CLASSES.items()
        if klass == IDENTIFIER_CLASS_DEFECT
    )
    if frozenset(declared_defects) != DEFECT_IDENTIFIERS:
        raise IdentifierClassError(
            f'defect ratchet disagrees with the classes: declared '
            f'{declared_defects}, ratchet {sorted(DEFECT_IDENTIFIERS)}'
        )

    # A defect that acquired a producer has been fixed — shrink the ratchet.
    repaired = sorted(
        identifier for identifier in DEFECT_IDENTIFIERS if producers[identifier]
    )
    if repaired:
        raise IdentifierClassError(
            f'identifiers still classed as defects now have producers: '
            f'{repaired} — reclass them and shrink DEFECT_IDENTIFIERS'
        )


def closure_issues(
    served: set[str] | frozenset[str],
    operations: dict,
    routes: dict,
    schemas: dict,
) -> list[dict]:
    """What is missing from ``served`` for it to be a closed subset.

    Returns one entry per unsatisfied dependency::

        {'operation': ..., 'identifier': ..., 'producers': (...)}

    An identifier classed ``external`` or ``side_effect`` never appears — its
    value comes from outside this surface. One classed ``defect`` never appears
    either, and that is the cost of leaving a defect unrepaired: the closure is
    silent exactly where the contract cannot answer. The ratchet is what keeps
    that silence from spreading.
    """
    producers = identifier_producers(operations, routes, schemas)
    issues: list[dict] = []
    for operation_id in sorted(served):
        for identifier in sorted(consumed_identifiers(operation_id, routes)):
            if IDENTIFIER_CLASSES.get(identifier) != IDENTIFIER_CLASS_PROVIDER_PRODUCED:
                continue
            if set(producers[identifier]) & set(served):
                continue
            issues.append({
                'operation': operation_id,
                'identifier': identifier,
                'producers': producers[identifier],
            })
    return issues
