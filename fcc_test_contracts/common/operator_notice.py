"""Logger-only publication for facts an operator must be able to read.

The API composition roots explicitly install the server stderr handler in
``logger_config``.  This module only adds the channel tag and emits one logger
record, so request/boot notices share the ordinary file, structured, in-memory,
and server-stream sinks without maintaining a second output path.
"""
from __future__ import annotations

from typing import Optional

from fcc_test_contracts.common.logging_channel import get_logger as _channel_get_logger

#: Channel tags. Operators grep these, so they are constants rather than
#: literals at the call sites — a rename must move the runbook with it.
CHANNEL_PROXY_TRUST = 'proxy-trust'
CHANNEL_PLATFORM_API = 'platform-api'
CHANNEL_LOCAL_AUTH = 'local-auth'

#: The level used when a caller does not name one. Deliberately not ``info``:
#: everything routed here is something an operator is expected to act on.
DEFAULT_LEVEL = 'warning'


def announce(
    channel: str,
    message: str,
    *,
    log: Optional[object] = None,
    level: str = DEFAULT_LEVEL,
) -> None:
    """Publish one tagged logger record.

    ``log`` is optional so callers without a logger can still use the shared
    hierarchy. An unknown level falls back rather than raising: this runs on
    the boot path and inside exception handlers. Attribute lookup failures
    use the shared child logger; invocation failures are not retried because
    the adapter may already have published the record.
    """
    tagged_message = f'[{channel}] {_one_line(message)}'
    child_name = f'operator_notice.{channel}'

    def _emit(target: object) -> tuple[bool, bool]:
        """Return ``(emitted, attempted)`` without retrying an uncertain emit.

        A logger adapter can publish a record and then raise while flushing or
        forwarding it.  Retrying that call would create a duplicate operator
        notice, so an invocation that reached a callable is treated as
        attempted even when it raises.  Attribute lookup and missing levels
        remain safe to fall back from.
        """
        # ``getattr`` itself can raise for a hostile or lazily-proxied logger;
        # this path is deliberately safe because notices are used in error
        # handlers as well as during boot.
        try:
            emit = getattr(target, level, None)
            if not callable(emit):
                emit = getattr(target, DEFAULT_LEVEL, None)
        except Exception:  # noqa: BLE001 — hostile attribute lookup
            return False, False
        if not callable(emit):
            return False, False
        try:
            emit('%s', tagged_message)
        except Exception:  # noqa: BLE001 — it may have emitted before raising
            return False, True
        return True, True

    try:
        target = log if log is not None else _channel_get_logger(child_name)
    except Exception:  # noqa: BLE001 — a notice must not raise
        target = None

    if target is not None:
        emitted, attempted = _emit(target)
        if emitted or attempted:
            return

    # A supplied logger may be a broken adapter. Fall back to the same named
    # hierarchy once; this remains logger-only and therefore cannot duplicate
    # a valid record.
    if log is not None:
        try:
            fallback = _channel_get_logger(child_name)
        except Exception:  # noqa: BLE001 — a notice must not raise
            return
        _emit(fallback)


#: What a newline inside a notice becomes. A visible marker rather than a space:
#: the operator should be able to tell that the original text had a break.
NEWLINE_REPLACEMENT = ' ⏎ '


def _one_line(message: str) -> str:
    """Collapse embedded newlines so one notice cannot forge another.

    ⚠️ **These messages carry driver text.** A 5xx notice renders
    ``str(exception)``, and a database driver's message is multi-line often
    enough — so a value that reaches an exception message could emit a second
    line beginning with a channel tag, and an operator grepping for
    ``[platform-api]`` would read it as a notice this process made. Log
    injection is cheap to prevent and expensive to notice.
    """
    try:
        text = str(message)
    except Exception:  # noqa: BLE001 — a hostile __str__ must not lose the line
        return '<unprintable>'
    for character in ('\r\n', '\r', '\n'):
        text = text.replace(character, NEWLINE_REPLACEMENT)
    return text
