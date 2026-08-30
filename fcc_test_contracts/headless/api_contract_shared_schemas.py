"""Headless contract surface — api contract shared schemas."""
from __future__ import annotations



SHARED_SCHEMAS = {
    # 1:1 with ``execution_job_store._job_to_dict``. Same rule as
    # ``ReportRequestSnapshot`` below, and the same seal
    # (``tests/test_headless_snapshot_contract_conformance.py``): the string
    # members are non-nullable because the builder coerces NULL to ``''``
    # (``row.<col> or ''`` / ``_dt()``), while ``session_id`` / ``payload_json``
    # / ``options_json`` are passed through and are therefore declared nullable.
    #
    # The split is not stylistic. ``routes/jobs.tsx::orDash`` is typed
    # ``(value: string | undefined) => string`` and guards with
    # ``value !== undefined && value !== ''``: a ``null`` passes that guard and
    # is returned unchanged, so the declared ``string`` return is unsound and
    # the table cell receives ``null`` as a React child — which React renders
    # as **nothing**. The symptom is a silently blank cell where an em-dash
    # belongs, not a visible error. (An earlier draft of this comment said it
    # renders the text "null"; an adversarial review disproved that. Blank is
    # the worse failure of the two — nobody files a bug about whitespace.)
    'MeasurementJobSnapshot': {
        'type': 'object',
        'required': ['id', 'status', 'excel_path'],
        'properties': {
            'id': {'type': 'integer'},
            'job_uuid': {'type': 'string'},
            'excel_path': {'type': 'string'},
            'session_id': {'type': 'integer', 'nullable': True},
            'status': {'type': 'string'},
            'requested_by': {'type': 'string'},
            'assigned_worker_id': {'type': 'string'},
            'stop_requested': {'type': 'boolean'},
            'status_message': {'type': 'string'},
            'payload_json': {'type': 'string', 'nullable': True},
            'options_json': {'type': 'string', 'nullable': True},
            'created_at': {'type': 'string'},
            'claimed_at': {'type': 'string'},
            'lease_expires_at': {'type': 'string'},
            'started_at': {'type': 'string'},
            'finished_at': {'type': 'string'},
            'updated_at': {'type': 'string'},
        },
        'additionalProperties': True,
    },
    'ReportAutomationQueueStats': {
        'type': 'object',
        'required': ['queued', 'running', 'completed', 'failed', 'cancelled'],
        'properties': {
            'queued': {'type': 'integer'},
            'running': {'type': 'integer'},
            'completed': {'type': 'integer'},
            'failed': {'type': 'integer'},
            'cancelled': {'type': 'integer'},
            'oldest_queued_request_id': {'type': 'integer', 'nullable': True},
        },
        'additionalProperties': True,
    },
}
