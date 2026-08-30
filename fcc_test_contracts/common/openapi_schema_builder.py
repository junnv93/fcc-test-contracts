"""Shared OpenAPI 3.1 schema-building helpers (FE-P0d, 2026-05-27).

The Headless API (``application.headless.api_schema``) and the Platform API
(``application.platform.api_schema``) both turn a dependency-free contract SSOT
(routes / operations / schemas / path-params) into an OpenAPI 3.1 document. The
*normalization* rules are identical across both surfaces:

1. ``$ref: '#/schemas/X'`` (contract-internal) → ``$ref: '#/components/schemas/X'``
2. Swagger-2 ``nullable: true`` → an OpenAPI 3.1 **union with null**. Which
   spelling that union takes depends on how the schema constrains the value:

   a. constrained by ``type`` (string or list) — the keyword is already a
      disjunction, so null joins it in place: ``type: [<orig>, 'null']``
   b. constrained *without* ``type`` (``$ref`` / ``allOf`` / ``oneOf`` /
      ``enum`` …) — lifted into ``anyOf: [<constraint verbatim>, {'type':
      'null'}]``. A sibling ``type: ['null']`` would be read *conjunctively*
      (``T AND null``), an uninhabited intersection that ``openapi-typescript``
      renders as ``null & T`` and TypeScript collapses to ``never``.
   c. not constrained at all — **the meaning is not narrowed**: only the
      ``nullable`` key is dropped, because such a schema already admits null.

   Annotation keywords (``ANNOTATION_KEYWORDS`` — ``title`` / ``description`` /
   …) stay outside the union in case (b); they describe the field, not one
   branch of it.

3. A **shape-less** ``type: 'object'`` (no ``properties`` / ``additionalProperties``
   / combinator) → the free-form intent is made *explicit* with
   ``additionalProperties: true``. JSON Schema already reads the bare form as
   "any object", but ``openapi-typescript`` reads the absent
   ``additionalProperties`` as *closed* and renders ``Record<string, never>`` —
   a type no value can inhabit. See :func:`normalize_free_form_object`.

This module is the single definition of those rules so the two surfaces cannot
drift apart. Per-surface *document assembly* (info block, securityScheme,
tags, operation summaries) legitimately differs and stays in each surface's
``api_schema`` module — extracting a single mega-builder would over-abstract.

dependency-free: stdlib typing only (``application.common`` purity invariant —
no fastapi / PySide6 / sqlalchemy / infrastructure imports).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from fcc_test_contracts.common.api_error_codes import (
    ERROR_CODE_STATUS,
    ErrorCode,
    PROBLEM_JSON_MEDIA_TYPE,
)


__all__ = [
    'apply_operation_error_responses',
    'build_components_schemas',
    'free_form_object_schema',
    'iter_path_param_names',
    'MULTIPART_FILE_FIELD',
    'MULTIPART_MEDIA_TYPE',
    'multipart_file_request_body',
    'normalize_contract_schema',
    'normalize_free_form_object',
    'normalize_nullable',
    'normalize_ref',
    'PROBLEM_DETAILS_SCHEMA_NAME',
    'ERROR_CODE_SCHEMA_NAME',
    'problem_details_component_schemas',
    'problem_error_response',
]


# RFC 9457 (B1): the component schema names for the shared Problem Details body
# + the machine-readable code enum. Both surfaces merge these into their
# ``components.schemas`` so the generated TS bundle carries one ``ProblemDetails``
# / ``ErrorCode`` type (consumed by ``apps/web`` ApiError.code narrowing).
PROBLEM_DETAILS_SCHEMA_NAME = 'ProblemDetails'
ERROR_CODE_SCHEMA_NAME = 'ErrorCode'


def problem_details_component_schemas(
    codes: Sequence[ErrorCode],
) -> dict[str, Any]:
    """Return the ``ErrorCode`` + ``ProblemDetails`` component schemas (B1).

    ``codes`` is the set this surface publishes — pass
    ``surface_error_codes(ApiSurface.X)`` so a surface advertises only what it
    can actually emit. ``codes`` is mandatory: a default of "publish the
    unscoped shared union" is a trap for the next surface, which quietly gets
    every code it never declared minus the ones it actually needs (a real
    scoped code shipped that way once — see
    ``tests/test_error_code_publication_axis_invariants.py``).

    Values are still derived from the ``ErrorCode`` enum SSOT (never a
    hand-maintained string list), so a code's spelling cannot drift from the
    Python taxonomy. ``ProblemDetails`` references the code enum via the
    contract-internal ``#/schemas/`` form, normalized to
    ``#/components/schemas/`` by :func:`build_components_schemas`.
    """
    published = tuple(codes)
    return {
        ERROR_CODE_SCHEMA_NAME: {
            'type': 'string',
            'description': 'Machine-readable error identifier (RFC 9457 code).',
            'enum': [code.value for code in published],
        },
        PROBLEM_DETAILS_SCHEMA_NAME: {
            'type': 'object',
            'description': (
                'RFC 9457 Problem Details for HTTP APIs '
                '(application/problem+json error body).'
            ),
            'required': ['type', 'title', 'status', 'detail', 'code'],
            'properties': {
                'type': {'type': 'string', 'format': 'uri-reference',
                         'default': 'about:blank'},
                'title': {'type': 'string'},
                'status': {'type': 'integer'},
                'detail': {'type': 'string'},
                'code': {'$ref': f'#/schemas/{ERROR_CODE_SCHEMA_NAME}'},
                'instance': {'type': 'string', 'nullable': True},
                'params': {'type': 'object', 'additionalProperties': True,
                           'nullable': True},
            },
            'additionalProperties': True,
        },
    }


def problem_error_response(description: str) -> dict[str, Any]:
    """Build an OpenAPI error response object with a problem+json body (B1).

    The body schema references the shared ``ProblemDetails`` component so every
    error response across both surfaces advertises the same machine-readable
    shape. ``description`` is the human-readable per-code summary.
    """
    return {
        'description': description,
        'content': {
            PROBLEM_JSON_MEDIA_TYPE: {
                'schema': {'$ref': f'#/components/schemas/{PROBLEM_DETAILS_SCHEMA_NAME}'},
            },
        },
    }


def apply_operation_error_responses(
    responses: dict[str, Any], operation: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge an operation's declared ``error_responses`` into ``responses``.

    Single SSOT mechanism for *operation-specific* error responses across BOTH
    web surfaces (headless + platform): an operation declares
    ``error_responses={'409': '<desc>', '410': '<desc>', ...}`` in its contract
    SSOT and this helper emits a problem+json response (RFC 9457, B1) carrying
    that description. Keeps the two ``_build_responses_for`` builders from
    drifting into divergent mechanisms. Mutates and returns ``responses`` for
    call-site chaining. Codes are coerced to ``str`` so int/str declarations
    serialize identically.
    """
    for code, description in (operation.get('error_responses') or {}).items():
        responses[str(code)] = problem_error_response(description)
    return responses


def iter_path_param_names(path: str):
    """Yield ``{name}`` template placeholders from an OpenAPI path string.

    Shared with invariant tests so the SSOT extraction logic has a single
    definition (no duplicated regex/scan).
    """
    cursor = 0
    while True:
        start = path.find('{', cursor)
        if start == -1:
            return
        end = path.find('}', start + 1)
        if end == -1:
            return
        yield path[start + 1:end]
        cursor = end + 1


def normalize_ref(value: Any) -> Any:
    """Rewrite ``$ref: '#/schemas/X'`` (contract-internal) to OpenAPI 3.1
    canonical ``$ref: '#/components/schemas/X'``. Mutates nothing — returns a
    new structure so the source dicts stay byte-identical."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == '$ref' and isinstance(item, str) and item.startswith('#/schemas/'):
                out[key] = '#/components/schemas/' + item[len('#/schemas/'):]
            else:
                out[key] = normalize_ref(item)
        return out
    if isinstance(value, list):
        return [normalize_ref(item) for item in value]
    return value


#: OpenAPI 3.1 JSON Schema spelling of the null type.
NULL_TYPE = 'null'

#: Keyword used to express "this schema OR null" for schemas that are not
#: constrained by a ``type`` keyword. ``anyOf`` (not ``oneOf``) because that is
#: what the artifact's hand-written precedent uses (``SampleEnvelope
#: .latest_intake``) — one meaning must have exactly one idiom, or the next
#: reviewer copies the wrong one. ``anyOf`` is also the weaker (and therefore
#: safer) claim: ``oneOf`` additionally asserts the branches are mutually
#: exclusive, which is a promise about ``T`` this normaliser cannot make.
NULLABLE_UNION_KEYWORD = 'anyOf'


#: JSON Schema / OpenAPI keywords that *annotate* a schema rather than constrain
#: it. When a schema is lifted into a nullable union these stay at the property
#: level — they describe the field, not one branch of it, and tooling (docs
#: renderers, ``openapi-typescript`` JSDoc) reads them there. Constraint
#: keywords go into the branch.
ANNOTATION_KEYWORDS = frozenset({
    'title',
    'description',
    'default',
    'deprecated',
    'readOnly',
    'writeOnly',
    'example',
    'examples',
    'externalDocs',
    '$comment',
})


def _null_branch() -> dict[str, Any]:
    """A fresh ``{'type': 'null'}`` union branch (never a shared mutable)."""
    return {'type': NULL_TYPE}


def _apply_nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Express "…or null" on an already-normalised schema.

    Which spelling is correct depends on *how the schema constrains the value*:

    - A ``type`` keyword is itself a disjunction of primitive types, so null can
      simply join it: ``type: [original, 'null']``.
    - ``$ref`` / ``allOf`` / ``oneOf`` / ``enum`` constrain **conjunctively**
      with their siblings. Writing ``type: ['null']`` beside them therefore says
      ``T AND null`` — an intersection that is inhabited by nothing.
      ``openapi-typescript`` renders it as ``null & T`` and TypeScript collapses
      that to ``never``, so every read of the field is a compile error even
      though the wire carries ``T | null``. Such a schema has to be lifted into
      an explicit union.
    """
    base_type = schema.get('type')
    if isinstance(base_type, str):
        schema['type'] = [base_type, NULL_TYPE]
        return schema
    if isinstance(base_type, list):
        if NULL_TYPE not in base_type:
            schema['type'] = list(base_type) + [NULL_TYPE]
        return schema

    # No ``type`` keyword → union. Annotations describe the field and stay put;
    # only the constraint keywords are lifted into a branch.
    annotations = {k: v for k, v in schema.items() if k in ANNOTATION_KEYWORDS}
    constraints = {k: v for k, v in schema.items() if k not in ANNOTATION_KEYWORDS}

    # Nothing constrains the value, so it already admits null — wrapping would
    # turn "no narrowing" into noise.
    if not constraints:
        return annotations

    # Already a union: extend it in place instead of nesting union-in-union.
    existing = constraints.get(NULLABLE_UNION_KEYWORD)
    if list(constraints) == [NULLABLE_UNION_KEYWORD] and isinstance(existing, list):
        if any(
            isinstance(branch, Mapping) and branch.get('type') == NULL_TYPE
            for branch in existing
        ):
            return {**annotations, **constraints}
        return {
            **annotations,
            NULLABLE_UNION_KEYWORD: list(existing) + [_null_branch()],
        }

    # The constraint half goes into a branch **verbatim**. Deliberately no
    # special case for ``{'allOf': [X]}`` → ``X``: that collapse is
    # meaning-preserving but it is a *second* rule that sniffs member count, it
    # cannot generalise to multi-member ``allOf``, and it makes the output shape
    # depend on how the declaration happened to be spelled. One rule is worth
    # more than an idiom that matches the hand-written precedent byte for byte.
    return {
        **annotations,
        NULLABLE_UNION_KEYWORD: [constraints, _null_branch()],
    }


def normalize_nullable(value: Any) -> Any:
    """Translate the Swagger-2 ``nullable: true`` convention into its OpenAPI
    3.1 canonical form.

    Nullability is always a **union** with null. For a ``type``-constrained
    schema that union can be folded into the ``type`` keyword itself
    (``type: [original, 'null']``); for a ``$ref``/``allOf``/``oneOf``/``enum``
    schema it cannot, and must be spelled ``anyOf: [schema, {type: 'null'}]``.
    See :func:`_apply_nullable` for why conflating the two produces a generated
    TypeScript type of ``never``.

    Idempotent — values without ``nullable`` pass through unchanged, and the
    output of this function carries no ``nullable`` key to re-trigger it.
    """
    if isinstance(value, Mapping):
        # First descend (avoid double-normalising nested structures).
        normalised: dict[str, Any] = {k: normalize_nullable(v) for k, v in value.items()}
        if normalised.pop('nullable', False):
            return _apply_nullable(normalised)
        return normalised
    if isinstance(value, list):
        return [normalize_nullable(item) for item in value]
    return value


#: OpenAPI 3.1 JSON Schema spelling of the object type.
OBJECT_TYPE = 'object'

#: Media type of a browser/``openapi-fetch`` file upload. One spelling so the
#: three uploading surfaces cannot disagree with each other or with the routes.
MULTIPART_MEDIA_TYPE = 'multipart/form-data'

#: Form field name every upload operation in this repository uses. A parameter
#: of :func:`multipart_file_request_body` rather than a literal repeated at each
#: call site — the OpenAPI document and the FastAPI ``UploadFile`` parameter
#: have to agree, and a disagreement surfaces only as a 422 on a real upload.
MULTIPART_FILE_FIELD = 'file'

#: Value written for a free-form object's ``additionalProperties``. Named
#: because it is the *widening* half of :func:`normalize_free_form_object` —
#: writing ``False`` here would invert the rule into the very narrowing the
#: normaliser exists to prevent.
FREE_FORM_ADDITIONAL_PROPERTIES = True

#: Keywords by which a schema declares what an object *contains*. If any is
#: present the declaration has already stated its shape, so
#: :func:`normalize_free_form_object` keeps its hands off — it only fills the
#: gap where nothing at all was said. ``$ref``/combinators are included because
#: the shape then lives in the referenced/composed schema, not here.
OBJECT_SHAPE_KEYWORDS = frozenset({
    'properties',
    'patternProperties',
    'additionalProperties',
    'unevaluatedProperties',
    'propertyNames',
    '$ref',
    'allOf',
    'anyOf',
    'oneOf',
    'not',
})


def _declares_object_type(schema: Mapping[str, Any]) -> bool:
    """True when ``type`` admits ``'object'`` (scalar or list spelling).

    The list spelling is not hypothetical: :func:`normalize_nullable` turns
    ``{'type': 'object', 'nullable': True}`` into ``{'type': ['object',
    'null']}``, so a normaliser that only matched the scalar string would miss
    every nullable free-form mapping — which is exactly half of the defect
    population in the headless artifact.
    """
    declared = schema.get('type')
    if isinstance(declared, str):
        return declared == OBJECT_TYPE
    if isinstance(declared, list):
        return OBJECT_TYPE in declared
    return False


def normalize_free_form_object(value: Any) -> Any:
    """Make a shape-less ``type: 'object'`` say *explicitly* that it is free-form.

    A schema that declares ``type: 'object'`` and nothing else is, in JSON
    Schema, "any object" — the absence of ``properties``/``additionalProperties``
    imposes no constraint. ``openapi-typescript`` reads that same absence as a
    *closed* object and renders ``Record<string, never>``: a type inhabited by
    no value at all. Every client field so typed becomes unassignable, so the
    only value the front end can compile is ``{}`` — which the server then
    rejects. That is the ``CreateTestPlanDraftRequest.scope_profile`` defect:
    the schema said "any mapping", the generated type said "nothing", and the
    compiler forced the client to send a payload the domain always refuses.

    This is the sibling of :func:`normalize_nullable`, and the same rule of
    thumb governs both: **normalise toward the declared meaning, never narrow
    it.** The nullable fallback's second defect was turning "anything, or null"
    into "null only"; writing ``additionalProperties: false`` here would repeat
    that mistake in the object axis. Hence
    :data:`FREE_FORM_ADDITIONAL_PROPERTIES` is ``True``: the emitted artifact
    states the meaning the declaration already had.

    Deliberately *not* a hard error on the bare form. Raising would force each
    declaration site to spell the intent out, but the cheapest way to silence
    such an error is ``additionalProperties: false`` — the narrowing this
    function exists to prevent. A total normaliser cannot be silenced wrongly,
    and it also covers declarations written after this rule was forgotten.

    Idempotent: the output carries ``additionalProperties``, which is itself a
    shape keyword, so a second pass is a no-op.
    """
    if isinstance(value, Mapping):
        normalised: dict[str, Any] = {
            key: normalize_free_form_object(item) for key, item in value.items()
        }
        if _declares_object_type(normalised) and not (
            OBJECT_SHAPE_KEYWORDS & normalised.keys()
        ):
            normalised['additionalProperties'] = FREE_FORM_ADDITIONAL_PROPERTIES
        return normalised
    if isinstance(value, list):
        return [normalize_free_form_object(item) for item in value]
    return value


def free_form_object_schema() -> dict[str, Any]:
    """A fresh schema saying *explicitly* "any JSON object".

    The spelling every surface must reach for when it has to emit an object
    whose shape is genuinely unconstrained — a response-schema fallback, a
    catch-all extension bag. Writing the bare ``{'type': 'object'}`` there means
    the same thing in JSON Schema but renders as ``Record<string, never>`` in
    the generated TypeScript (see :func:`normalize_free_form_object`), so the
    literal is not interchangeable with this factory even though the *meaning*
    is. Returns a new dict each call — never a shared mutable that a caller
    could edit into every other call site's fallback.
    """
    return {
        'type': OBJECT_TYPE,
        'additionalProperties': FREE_FORM_ADDITIONAL_PROPERTIES,
    }


def multipart_file_request_body(
    *,
    field: str = MULTIPART_FILE_FIELD,
    description: str | None = None,
) -> dict[str, Any]:
    """The one spelling of a ``multipart/form-data`` single-file request body.

    OpenAPI 3.1 expresses a file upload as an object schema with a
    ``format: binary`` property; ``openapi-typescript`` renders that as a
    ``FormData``/``File`` request, which is what ``openapi-fetch`` callers need.

    This factory exists because the idiom was written out **twice, byte for
    byte** — once for the headless test-plan import and once for the platform
    sample-inventory imports — and this repository was about to write it a third
    time for the session workbook upload. Three hand-kept copies of one wire
    idiom is a drift surface, and the drift would only show up in a *generated*
    artifact, i.e. in somebody's frontend, not in a test. One idiom, one
    definition — the same reason :func:`free_form_object_schema` exists next
    door rather than each surface spelling out its own widening.

    The field name is a parameter rather than a literal at each call site so the
    three surfaces cannot disagree about what the form field is called; today
    all three use :data:`MULTIPART_FILE_FIELD`.

    ``required: True`` is not a default anyone should override: an upload
    operation whose body is optional has no meaning — the upload *is* the
    operation. Returns a new dict each call, never a shared mutable.
    """
    schema: dict[str, Any] = {
        'type': OBJECT_TYPE,
        'required': [field],
        'properties': {
            field: {'type': 'string', 'format': 'binary'},
        },
    }
    if description is not None:
        schema['properties'][field]['description'] = description
    return {
        'required': True,
        'content': {
            MULTIPART_MEDIA_TYPE: {
                'schema': schema,
            },
        },
    }


def normalize_contract_schema(schema: Any) -> Any:
    """Apply the full contract → OpenAPI 3.1 normalization pipeline to one schema.

    :func:`normalize_ref`, then :func:`normalize_nullable`, then
    :func:`normalize_free_form_object`, in that order — the artifact then lints
    clean under OpenAPI 3.1 validators while the source contract stays a
    dependency-free machine contract.

    The free-form pass runs **after** the nullable pass on purpose: nullable
    rewrites ``{'type': 'object'}`` into the list spelling ``{'type':
    ['object', 'null']}``, and running the object pass first would leave the
    ordering-dependent question of which spelling it has to recognise. Last
    means it always sees the final ``type`` keyword.

    This function — not the three-call sequence — is the pipeline SSOT. A
    surface that assembles schemas **inline into ``paths``** (rather than into
    ``components.schemas``) never reaches :func:`build_components_schemas`, and
    that is precisely how the session surface stayed outside the normalisation
    the two sibling surfaces already had. Such a surface calls this directly;
    it does not re-spell the sequence, because a second spelling is a second
    place for the ordering rule above to be got wrong.
    """
    return normalize_free_form_object(normalize_nullable(normalize_ref(schema)))


def build_components_schemas(schemas: Mapping[str, Any]) -> dict[str, Any]:
    """Build OpenAPI 3.1 ``components.schemas`` from a contract schema mapping.

    Each schema goes through :func:`normalize_contract_schema` (the pipeline
    SSOT). This function adds only the per-name iteration.
    """
    return {
        name: normalize_contract_schema(raw_schema)
        for name, raw_schema in schemas.items()
    }
