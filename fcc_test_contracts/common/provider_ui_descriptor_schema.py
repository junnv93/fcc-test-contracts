"""Shared provider UI descriptor contract schema (WEB-PROVIDER-UI-0, 2026-05-29).

Dependency-free JSON-Schema fragments + status / row-identity vocabularies for the
provider-aware UI descriptor. Lives in ``application/common`` — a *neutral* shared
location — so BOTH the provider surface (``application.headless.api_contracts``)
and the platform proxy surface (``application.central_contract.api_contracts``) can merge
the same component shapes into their OpenAPI schema dicts **without** the platform
contract importing the provider module (the descriptor pattern's whole point: the
platform renders the contract generically; it never reaches into provider code).

Schema fragments use the in-document ``#/schemas/<Name>`` ``$ref`` style — the
shared ``application.common.openapi_schema_builder.build_components_schemas``
normalizes them to ``#/components/schemas/<Name>`` for OpenAPI 3.1, identical to
every other contract on these surfaces.

read-only foundation: the descriptor describes *what* to render; row edit/save/
publish are deferred to WEB-PROVIDER-UI-0.5+ (stable-row-identity ADR).
"""
from __future__ import annotations


__all__ = [
    'FEATURE_STATUS_SUPPORTED',
    'FEATURE_STATUS_READ_ONLY',
    'FEATURE_STATUS_UNSUPPORTED',
    'FEATURE_STATUS_PLANNED',
    'FEATURE_STATUS_PROVIDER_SPECIFIC',
    'FEATURE_STATUS_RESTRICTED',
    'FEATURE_STATUSES',
    'ROW_IDENTITY_SOURCE_HISTORY_CONDITION',
    'ROW_IDENTITY_SOURCE_MATCH_DEFAULT',
    'ROW_IDENTITY_SOURCES',
    'FIELD_DATA_TYPE_STRING',
    'FIELD_DATA_TYPE_IPV4',
    'FIELD_DATA_TYPE_GPIB_ADDRESS',
    'FIELD_DATA_TYPES',
    'PROVIDER_UI_DESCRIPTOR_SCHEMAS',
]


# ---------------------------------------------------------------------------
# Capability status vocabulary (provider_contract §4.1). The UI renders each
# feature according to its status; ``restricted`` (admin/approval) extends the
# §4.1 set for the correction/limit workflow (provider_aware prompt §1.5 example).
# ---------------------------------------------------------------------------
FEATURE_STATUS_SUPPORTED = 'supported'
FEATURE_STATUS_READ_ONLY = 'read_only'
FEATURE_STATUS_UNSUPPORTED = 'unsupported'
FEATURE_STATUS_PLANNED = 'planned'
FEATURE_STATUS_PROVIDER_SPECIFIC = 'provider_specific'
FEATURE_STATUS_RESTRICTED = 'restricted'

FEATURE_STATUSES = (
    FEATURE_STATUS_SUPPORTED,
    FEATURE_STATUS_READ_ONLY,
    FEATURE_STATUS_UNSUPPORTED,
    FEATURE_STATUS_PLANNED,
    FEATURE_STATUS_PROVIDER_SPECIFIC,
    FEATURE_STATUS_RESTRICTED,
)

# ---------------------------------------------------------------------------
# Row-identity source tokens. The descriptor declares WHICH SSOT a table's row
# identity is derived from — never a hardcoded column array. The actual column
# list (``row_identity_columns``) is derived from that SSOT by the provider
# builder, and naming the source is what keeps the two from drifting apart.
#
# ⚠️ **That intent is provider-neutral; the enum that used to enforce it was not.**
# The schema constrained this field to the two constants below — which are one
# provider's Python symbol names (``Col.*``, measured 2026-09-04: the only
# ``Col.`` strings anywhere in the shared contract). A provider whose row
# identity is its own set had no true value to write:
#
#   FCC  Col.MATCH_DEFAULT      (10)  Test Technology Band Bandwidth Channel
#                                     Tone Location Mode Modulation Antenna
#   FCC  Col.HISTORY_CONDITION  (14)  ↑ + four power columns
#   KC   RESULT_MATCH_COLUMNS   (11)  ↑ MATCH_DEFAULT's ten + Temperature
#
# KC's identity is the ten **plus a temperature axis FCC does not have** (room /
# low / high are different rows). Writing ``Col.MATCH_DEFAULT`` there would not
# be merely meaningless — it would be **false**, and a consumer honouring it
# would collapse three rows into one. That is the UI-side twin of the defect
# D-4 closed (a result and its completion marker landing on different rows).
#
# So the enum is gone and the field stays required: the value now names **the
# provider's own** row-identity SSOT symbol. FCC keeps writing the two constants
# below; KC writes ``RESULT_MATCH_COLUMNS``; both are true. Same class as the
# ``template_profile`` default (``fcc-default``) that §5① of the KC identity
# ruling repaired — a shared contract carrying one provider's vocabulary.
#
# ⚠️ The two constants below are **FCC's**, kept because FCC's builder imports
# them. They are not this contract's vocabulary and must not be re-closed into
# an enum.
# ---------------------------------------------------------------------------
ROW_IDENTITY_SOURCE_HISTORY_CONDITION = 'Col.HISTORY_CONDITION'
ROW_IDENTITY_SOURCE_MATCH_DEFAULT = 'Col.MATCH_DEFAULT'

ROW_IDENTITY_SOURCES = (
    ROW_IDENTITY_SOURCE_HISTORY_CONDITION,
    ROW_IDENTITY_SOURCE_MATCH_DEFAULT,
)


# ---------------------------------------------------------------------------
# Field data types. Closed on purpose: the platform must render a provider's
# fields **without branching on the provider**, and it can only do that if every
# token it may receive maps to a widget it already has. A free-form string would
# force exactly the branch the descriptor pattern exists to avoid — and the
# branch would live in platform code, where a provider's vocabulary has no
# business being.
#
# Kept to what is actually rendered. A new member is a real decision (the
# renderer gains a widget), not a convenience, so speculative numeric/boolean
# members are deliberately absent until something emits them.
# ---------------------------------------------------------------------------
FIELD_DATA_TYPE_STRING = 'string'
FIELD_DATA_TYPE_IPV4 = 'ipv4'
FIELD_DATA_TYPE_GPIB_ADDRESS = 'gpib_address'

FIELD_DATA_TYPES = (
    FIELD_DATA_TYPE_STRING,
    FIELD_DATA_TYPE_IPV4,
    FIELD_DATA_TYPE_GPIB_ADDRESS,
)


_FIELD_DESCRIPTOR = {
    'type': 'object',
    'required': ['field_id', 'label', 'data_type', 'required'],
    'properties': {
        'field_id': {'type': 'string'},
        'label': {'type': 'string'},
        'data_type': {'type': 'string', 'enum': list(FIELD_DATA_TYPES)},
        'required': {'type': 'boolean'},
    },
    'additionalProperties': False,
}

PROVIDER_UI_DESCRIPTOR_SCHEMAS = {
    'ProviderUiDescriptor': {
        'type': 'object',
        'required': [
            'provider_id', 'display_name', 'ui_version', 'features',
            'test_plan_tables', 'equipment', 'reference_tables', 'correction_tables',
            'workbench_area_technologies',
        ],
        'properties': {
            'provider_id': {'type': 'string'},
            'display_name': {'type': 'string'},
            'ui_version': {'type': 'integer'},
            'features': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ProviderFeature'},
            },
            'test_plan_tables': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ProviderTableDescriptor'},
            },
            'equipment': {
                'type': 'array',
                'items': {'$ref': '#/schemas/EquipmentConfigDescriptor'},
            },
            'reference_tables': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ReferenceTableDescriptor'},
            },
            'correction_tables': {
                'type': 'array',
                'items': {'$ref': '#/schemas/CorrectionTableDescriptor'},
            },
            # Phase 6 P6-1: provider-owned workbench_area → technologies mapping
            # (area-id → array of technology tokens). The platform/web consume it
            # read-only to roll measurement progress up to the area level.
            'workbench_area_technologies': {
                'type': 'object',
                'additionalProperties': {
                    'type': 'array',
                    'items': {'type': 'string'},
                },
            },
        },
        'additionalProperties': False,
    },
    'ProviderFeature': {
        'type': 'object',
        'required': ['feature_id', 'label', 'status'],
        'properties': {
            'feature_id': {'type': 'string'},
            'label': {'type': 'string'},
            'status': {'type': 'string', 'enum': list(FEATURE_STATUSES)},
        },
        'additionalProperties': False,
    },
    'ProviderFieldDescriptor': dict(_FIELD_DESCRIPTOR),
    'ProviderTableDescriptor': {
        'type': 'object',
        'required': [
            'table_id', 'label', 'sheet_name',
            'row_identity_source', 'row_identity_columns', 'columns',
        ],
        'properties': {
            'table_id': {'type': 'string'},
            'label': {'type': 'string'},
            'sheet_name': {'type': 'string'},
            # ⚠️ No ``enum``: see the ROW_IDENTITY_SOURCES comment. The value names
            # the PROVIDER's own row-identity SSOT symbol, not one of FCC's two.
            'row_identity_source': {'type': 'string'},
            'row_identity_columns': {'type': 'array', 'items': {'type': 'string'}},
            'columns': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ProviderFieldDescriptor'},
            },
        },
        'additionalProperties': False,
    },
    'EquipmentConfigDescriptor': {
        'type': 'object',
        # `sheet_name` left out of `required` — see the property's description.
        'required': ['group_id', 'label', 'fields'],
        'properties': {
            'group_id': {'type': 'string'},
            'label': {'type': 'string'},
            'sheet_name': {
                'type': ['string', 'null'],
                'description': (
                    'The workbook sheet these settings are read from today, when '
                    'there is one. It was required, which quietly made this '
                    'descriptor a sheet mirror rather than a settings form: a '
                    'provider with no workbook could not describe its equipment '
                    'at all, and the read-only status was a consequence of that '
                    'shape rather than a decision. The sibling table descriptors '
                    'keep it required because they really are sheet mirrors.'
                ),
            },
            'fields': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ProviderFieldDescriptor'},
            },
        },
        'additionalProperties': False,
    },
    'ReferenceTableDescriptor': {
        'type': 'object',
        'required': ['table_id', 'label', 'sheet_name', 'columns'],
        'properties': {
            'table_id': {'type': 'string'},
            'label': {'type': 'string'},
            'sheet_name': {'type': 'string'},
            'columns': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ProviderFieldDescriptor'},
            },
        },
        'additionalProperties': False,
    },
    'CorrectionTableDescriptor': {
        'type': 'object',
        'required': ['table_id', 'label', 'sheet_name', 'access', 'columns'],
        'properties': {
            'table_id': {'type': 'string'},
            'label': {'type': 'string'},
            'sheet_name': {'type': 'string'},
            'access': {'type': 'string', 'enum': list(FEATURE_STATUSES)},
            'columns': {
                'type': 'array',
                'items': {'$ref': '#/schemas/ProviderFieldDescriptor'},
            },
        },
        'additionalProperties': False,
    },
}
