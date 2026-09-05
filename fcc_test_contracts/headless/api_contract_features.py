"""Which operations make up which capability — the conformance grouping SSOT.

Before this module the contract had **no grouping at all** (measured 2026-09-04:
``feature_id`` values enumerated in 0 places, ``operation -> feature`` mappings in
0 places). Every provider invented its own strings, and central had no way to
compare a provider's declaration against the contract surface. The consequence
was that the only judgement available was *"serves all 40 operations"*, which is
a gate no partial provider can ever pass — KC serves 21 of 40 and the rest are
awaiting an operator decision or a lab, so KC was permanently ``compatible=false``
for reasons that had nothing to do with conformance.

⚠️ **This is not the same axis as ``ProviderUiDescriptor.features``.** Measured
2026-09-05, before writing a line of this module:

    FCC (reference provider) declares  test_plan_edit · equipment_config ·
                                       reference_tables · correction_tables ·
                                       job_submission
    KC declares                        test-plan-authoring · test-plan-export · ...

Those are not two spellings of one vocabulary — they are two **axes**. Three of
FCC's five (``equipment_config`` / ``reference_tables`` / ``correction_tables``)
correspond to sub-tables of the UI descriptor and to no headless operation at
all. ADR-0010 D-7 already decided that separation: the typed contract and the
display descriptor are *two channels*, and *"descriptor must not penetrate the
typed contract domain"*. So the conformance grouping is declared HERE, in the
contract, and travels in the conformance evidence document — not in the runtime
descriptor.

⚠️ Consequently ``ProviderFeature.feature_id`` is deliberately **not**
enum-locked to :data:`FEATURE_IDS`. Locking it would turn the reference provider
red for declaring display capabilities it genuinely has, and would fold two axes
into one name — the defect class this contract just finished removing from
``job_id`` (see ``surface_test_plan``).

Membership is declared **once**, on the operation itself (``_operation(feature=)``),
and this module holds only the feature's own properties. Spelling the membership
in both places would make one of them derived, and a comparison between a
derivation and its own source is an identity — the failure this repository
measured five times over in ``headless-api.openapi.json`` (five byte-identical
copies, all five wrong).
"""
from __future__ import annotations

__all__ = [
    'CORE_FEATURE_IDS',
    'FEATURE_IDS',
    'HEADLESS_FEATURES',
    'UnknownFeatureError',
    'feature_operations',
    'validate_feature_membership',
]


class UnknownFeatureError(KeyError):
    """An operation claimed a feature this table does not declare."""


#: feature_id -> properties. ``required`` is the non-emptiness arm of the
#: conformance judgement: a provider that declares nothing is still judged
#: against every required feature, so "declare no features and pass" is not a
#: reachable state.
#:
#: ⚠️ ``label`` is **absent on purpose.** ``ProviderFeature.label`` is the
#: provider's own localized display string (KC ships Korean labels); a label
#: here would be a second, English, authority for the same screen text and the
#: two would drift. What the contract owns is the identity and the membership.
#:
#: ``blocked_by`` names the debt that keeps a real provider from serving the
#: feature today. It is documentation, not a judgement axis — but it is the
#: reason the boundaries fall where they do, and recording it is what makes the
#: grouping criterion checkable: *"different things are blocked by different
#: debts"* can be argued with, *"these two are blocked by the same debt"* can be
#: asked.
HEADLESS_FEATURES: dict[str, dict] = {
    'core': {
        'required': True,
        'description': (
            'Identity, contract discovery and backend liveness. Required of '
            'every provider — without these central cannot even ask what the '
            'provider supports, so no declaration can excuse their absence.'
        ),
    },
    'measurement-jobs': {
        'required': False,
        'description': (
            'The measurement job queue: submit, list, read and stop. '
            '⚠️ Surface only — whether a worker consumes the queue is a '
            'runtime fact that headless_status reports, not a contract fact.'
        ),
    },
    'report-automation': {
        'required': False,
        'description': (
            'Report generation requests, their outputs and the download '
            'stream.'
        ),
    },
    'session-results': {
        'required': False,
        'description': (
            'Reading what a measurement session produced: results, attempts, '
            'artifacts and the results export.'
        ),
    },
    'test-plan-authoring': {
        'required': False,
        'description': (
            'Creating and editing test-plan drafts and their rows, including '
            'validation.'
        ),
    },
    'test-plan-export': {
        'required': False,
        'description': (
            'Writing a draft back out as the provider\'s own workbook. '
            '⚠️ Separate from authoring because it is blocked by a different '
            'thing — the draft-to-workbook column mapping — and a provider can '
            'author fully while having no such mapping.'
        ),
    },
    'test-plan-generation': {
        'required': False,
        'description': (
            'Deriving a test-plan draft from the generation catalogue: '
            'preview, submit, and read back the generation job.'
        ),
    },
    'test-plan-publication': {
        'required': False,
        'description': (
            'Publishing a draft as an immutable plan, listing and reading '
            'publications, and importing a plan from a workbook.'
        ),
    },
}


#: Every declared feature id.
FEATURE_IDS: frozenset[str] = frozenset(HEADLESS_FEATURES)


#: The features no declaration can opt out of.
CORE_FEATURE_IDS: frozenset[str] = frozenset(
    feature_id
    for feature_id, properties in HEADLESS_FEATURES.items()
    if properties['required']
)


def validate_feature_membership(operations: dict) -> None:
    """Raise unless every operation names a feature this table declares.

    Called at import time from ``api_contract_surfaces`` rather than left to a
    test, for the same reason ``DuplicateContractKeyError`` is: an operation
    whose feature is missing or misspelled still builds an artifact and still
    resolves a route. The only witness would be a provider judged against a
    feature nobody defined.
    """
    missing = sorted(
        name for name, operation in operations.items()
        if not operation.get('feature')
    )
    if missing:
        raise UnknownFeatureError(
            f'operations declare no feature: {missing}'
        )
    unknown = sorted({
        (name, operation['feature'])
        for name, operation in operations.items()
        if operation['feature'] not in FEATURE_IDS
    })
    if unknown:
        raise UnknownFeatureError(
            'operations name a feature this contract does not declare: '
            f'{unknown}'
        )
    unused = sorted(FEATURE_IDS - {op['feature'] for op in operations.values()})
    if unused:
        # A feature with no operations cannot be served, cannot be missed, and
        # cannot be judged — declaring one is a way to make a provider look
        # richer than it is.
        raise UnknownFeatureError(
            f'features declared with no operations: {unused}'
        )


def feature_operations(operations: dict) -> dict[str, tuple[str, ...]]:
    """feature_id -> the operation ids that make it up, derived from the ops.

    Derived rather than declared: see the module docstring. A caller that needs
    the grouping as a table gets it from here, so the table and the operations
    cannot disagree.
    """
    grouped: dict[str, list[str]] = {feature_id: [] for feature_id in HEADLESS_FEATURES}
    for name in sorted(operations):
        grouped[operations[name]['feature']].append(name)
    return {feature_id: tuple(names) for feature_id, names in grouped.items()}
