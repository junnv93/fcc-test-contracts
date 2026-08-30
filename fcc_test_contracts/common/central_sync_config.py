"""Central HTTP result-sync configuration SSOT — the shared half.

This module is intentionally separate from ``headless.central_db_config``.
The Session Node may send authenticated result batches to the central Platform,
but it must never import the central database DSN namespace or a database
driver. Provider identity, batch sizing, and the optional periodic drainer are
the only sync settings needed on the chamber side.

Both sides of that protocol read this file — the node composition and the
platform's own ``central_db_config``, which derives its overlapping env map from
:data:`CENTRAL_RESULT_SYNC_ENV`. That is why the contracts lane owns it
(2026-08-15, platform-provider-crossing-closure): it was the platform lane's
last provider import under ``src``, and it is provider-free by content — a typed
env value object with no I/O, no driver and no endpoint.

**The batch-size default is defined here, not derived from the worker.** It used
to read ``BackendSyncWorkerConfig().batch_limit``, which put the number in a
provider worker dataclass while the env key that tunes it
(``FCC_CENTRAL_SYNC_BATCH_LIMIT``) was published from this module. The direction
is now the one the env key already implied: this module owns the value and the
worker derives its dataclass default from it. Still exactly one number.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from fcc_test_contracts.common.env_loaders import read_int, read_text


__all__ = [
    'CENTRAL_RESULT_SYNC_ENV',
    'CENTRAL_SYNC_DEFAULT_BATCH_LIMIT',
    'DEFAULT_POLL_INTERVAL_SECONDS',
    'CentralHttpSyncConfig',
    'coerce_poll_interval',
]


# Public SSOT for settings that are safe and required on the chamber side.
# The central DB module derives its overlapping env map from this mapping; the
# node composition imports this module directly and therefore has no DSN key.
CENTRAL_RESULT_SYNC_ENV: dict[str, str] = {
    'provider_id': 'FCC_CENTRAL_PROVIDER_ID',
    'batch_limit': 'FCC_CENTRAL_SYNC_BATCH_LIMIT',
    'poll_interval_seconds': 'FCC_CENTRAL_SYNC_POLL_INTERVAL_SECONDS',
    # Outbox retry knobs. ⚠️ These were declared in ``headless.central_db_config``
    # until 2026-08-29 even though the env names already said which side owns them
    # (the ``FCC_CENTRAL_SYNC_*`` chamber family, not the central DSN key). A node
    # that wanted its own retry tuning had to import the central DSN namespace to
    # read them, which is exactly what this module's first paragraph exists to
    # prevent. ``CENTRAL_DB_ENV`` spreads this mapping, so the central side's env
    # map is byte-identical after the move.
    #
    # ⚠️ The DSN key is named by description rather than spelled out on purpose:
    # ``test_chamber_sync_config_does_not_own_central_database_namespace`` judges
    # this file by literal text, and in that axis "declares the key" and "mentions
    # the key while explaining that it does not declare it" are the same value.
    'retry_max_retries': 'FCC_CENTRAL_SYNC_RETRY_MAX_RETRIES',
    'retry_base_delay_seconds': 'FCC_CENTRAL_SYNC_RETRY_BASE_DELAY_SECONDS',
    'retry_max_delay_seconds': 'FCC_CENTRAL_SYNC_RETRY_MAX_DELAY_SECONDS',
}

# One batch size across the config and the worker: ``BackendSyncWorkerConfig``
# derives its dataclass default from this name. Changing it here changes both.
CENTRAL_SYNC_DEFAULT_BATCH_LIMIT = 100

# Zero disables the optional periodic drainer; cycle-end remains the explicit
# trigger. The value is a tuning default, not an endpoint or secret.
DEFAULT_POLL_INTERVAL_SECONDS = 300


def coerce_poll_interval(raw: str) -> int:
    """Parse the periodic interval while preserving zero as the disable signal."""
    text = (raw or '').strip()
    if not text:
        return DEFAULT_POLL_INTERVAL_SECONDS
    try:
        value = int(text)
    except ValueError:
        return DEFAULT_POLL_INTERVAL_SECONDS
    return value if value > 0 else 0


@dataclass(frozen=True)
class CentralHttpSyncConfig:
    """Typed chamber result-sync settings with no database connection field."""

    provider_id: str = ''
    batch_limit: int = CENTRAL_SYNC_DEFAULT_BATCH_LIMIT
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    #: Outbox retry knobs, **raw**. Empty string = use the domain SSOT default
    #: for that field.
    #:
    #: ⚠️ **Raw is this module's rule here, not an exception to it.** Beside
    #: ``batch_limit: int`` these three read as an inconsistency to tidy up, and
    #: the natural tidy-up — *"there is a policy class, why keep strings?"* — is
    #: the ``depends_on: []`` widening the split rules call laundering.
    #:
    #: Measured, there is no inconsistency. This module already uses a **tolerant
    #: local coercer** rather than ``read_int`` wherever tolerance is the
    #: semantics: ``coerce_poll_interval`` exists because zero is a valid disable
    #: signal that ``read_int`` rejects. The retry knobs are tolerant for the same
    #: kind of reason — ``read_int('abc')`` and ``read_int('0')`` both **raise**,
    #: which would turn a retry-tuning typo into a crash of the node's sync
    #: composition, while ``from_raw`` falls back to the SSOT default. Their
    #: tolerant coercer is domain-owned (``_coerce_positive_int``) and this lane
    #: may not reach it, so raw is where that rule lands.
    #:
    #: The caller resolves them with ``OutboxRetryPolicy.from_raw``;
    #: :attr:`outbox_retry_knobs` names the mapping once, and
    #: ``TestTheKnobNamesCannotDriftFromTheParser`` derives the expected knob set
    #: from that parser's own signature — a rename on either side is red rather
    #: than a silently ignored env var.
    retry_max_retries: str = ''
    retry_base_delay_seconds: str = ''
    retry_max_delay_seconds: str = ''

    @property
    def scheduler_enabled(self) -> bool:
        return self.poll_interval_seconds > 0

    @property
    def outbox_retry_knobs(self) -> dict[str, str]:
        """Raw knobs keyed by ``OutboxRetryPolicy.from_raw``'s parameter names.

        One place names the mapping, so the two readers (this lane's callers and
        ``CentralDbConfig``) cannot drift on which env value feeds which field.
        """
        return {
            'max_retries': self.retry_max_retries,
            'base_delay_seconds': self.retry_base_delay_seconds,
            'max_delay_seconds': self.retry_max_delay_seconds,
        }

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None,
    ) -> 'CentralHttpSyncConfig':
        env = os.environ if environ is None else environ
        return cls(
            provider_id=read_text(env, CENTRAL_RESULT_SYNC_ENV['provider_id']),
            batch_limit=read_int(
                env,
                CENTRAL_RESULT_SYNC_ENV['batch_limit'],
                default=CENTRAL_SYNC_DEFAULT_BATCH_LIMIT,
            ),
            poll_interval_seconds=coerce_poll_interval(
                read_text(env, CENTRAL_RESULT_SYNC_ENV['poll_interval_seconds']),
            ),
            retry_max_retries=read_text(
                env, CENTRAL_RESULT_SYNC_ENV['retry_max_retries']),
            retry_base_delay_seconds=read_text(
                env, CENTRAL_RESULT_SYNC_ENV['retry_base_delay_seconds']),
            retry_max_delay_seconds=read_text(
                env, CENTRAL_RESULT_SYNC_ENV['retry_max_delay_seconds']),
        )
