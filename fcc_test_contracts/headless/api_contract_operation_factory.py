"""Headless contract surface — api contract operation factory."""
from __future__ import annotations

from typing import Optional



def _operation(
    *,
    request: Optional[str],
    response: str,
    permission: str,
    feature: str,
    query_params: Optional[list] = None,
    binary_response: bool = False,
    binary_media_type: Optional[str] = None,
    error_responses: Optional[dict] = None,
    multipart_request: bool = False,
    header_params: Optional[list] = None,
    success_status: int = 200,
    request_required: bool = False,
) -> dict:
    op = {
        'request': request,
        'response': response,
        'permission': permission,
        # Which capability this operation is part of (2026-09-05). Declared
        # here — on the operation, at the keystroke that creates it — rather
        # than in a feature -> operations table elsewhere, so that adding an
        # operation cannot leave it ungrouped. ``api_contract_features``
        # validates the value at import; ``feature_operations()`` derives the
        # table for callers that want it the other way round.
        #
        # ⚠️ Unlike every other optional key below, this one is REQUIRED and
        # present on all 40 operations. It therefore moves the contract digest
        # for every operation at once — deliberately, and at the cheapest
        # moment available: no provider had yet published conformance evidence
        # against the old digest (confirmed with the KC lane, 2026-09-05).
        'feature': feature,
    }
    # Only operations that actually take query parameters / return a binary
    # stream / declare extra error responses carry the extra key, so the other
    # operations' contract dicts (and the serialized api-contract document) stay
    # byte-identical to before.
    if query_params is not None:
        op['query_params'] = query_params
    if binary_response:
        op['binary_response'] = True
    # 2026-08-11: what the route actually sends. Before this key the builder
    # rendered every binary response as ``application/octet-stream`` while
    # ``export_test_plan_draft`` sent the xlsx MIME — the contract said one thing
    # and the wire did another, and nothing could see it because the route typed
    # its own literal. The route now reads THIS value, so the two cannot drift.
    # Absent ⇒ octet-stream, so every operation that does not declare it keeps a
    # byte-identical serialized contract (artifact drift gate).
    if binary_media_type is not None:
        op['binary_media_type'] = binary_media_type
    # FE-P6 (2026-05-29): operation-specific error responses beyond the default
    # 400/403/404 set (e.g. the download stream's 409/410). Keys are HTTP status
    # strings so they serialize identically into the OpenAPI ``responses`` map.
    if error_responses is not None:
        op['error_responses'] = error_responses
    # Phase 4 L3 (2026-06-22): a multipart/form-data upload (file binary) instead
    # of an application/json body. Only the import operation sets this, so every
    # other operation's contract dict stays byte-identical (artifact drift gate).
    # ``request`` stays None (no JSON request schema ref) — the OpenAPI builder
    # reads ``multipart_request`` to emit the file requestBody.
    if multipart_request:
        op['multipart_request'] = True
    if header_params is not None:
        op['header_params'] = header_params
    if success_status != 200:
        op['success_status'] = success_status
    if request_required:
        op['request_required'] = True
    return op
