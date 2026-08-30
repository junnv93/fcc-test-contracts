"""Logger-name assembly SSOT shared by every lane (contracts-owned, 2026-08-13).

Getting a named child logger under the project's root namespace is
field-neutral: it needs no infrastructure side effects (file handlers, log
directory creation, notification/event bus composition). Those belong to
``logger_config.LoggingSystem``, the provider-owned module that keeps eager
bootstrap for its 185 existing ``get_logger`` consumers.

This module exists so callers outside the provider lane (domain services,
platform application code, chamber node adapters) can obtain a correctly
namespaced logger without importing provider infrastructure to do it. Once
``logger_config.get_logger`` runs anywhere in the process, every child logger
obtained here already inherits its handlers via Python's normal logger
propagation — dependency-free child loggers are ordinary standard-library
behaviour, not a second logging system.
"""
from __future__ import annotations

import logging
import sys
from threading import Lock


# Server composition roots opt into this handler explicitly.  The marker lives
# beside the installer so provider-owned logger bootstrap and extracted
# platform entrypoints share one capability rather than maintaining parallel
# handler policies.
_SERVER_STREAM_HANDLER_MARKER = '_fcc_server_stream_handler'
_SERVER_STREAM_LOCK = Lock()


#: Root logger name every ``test_automation.*`` child logger nests under.
#: ``logger_config.LoggingSystem.LOGGER_NAME`` delegates to this constant so
#: the name is defined exactly once.
LOGGER_ROOT: str = 'test_automation'


def get_logger(name: str) -> logging.Logger:
    """Return ``logging.getLogger(f'{LOGGER_ROOT}.{name}')``.

    Does not bootstrap handlers. Callers that need the eager
    ``LoggingSystem`` side effects (file handlers, log directory creation)
    should import ``logger_config.get_logger`` instead — this accessor is
    for lanes that must not depend on provider infrastructure to get a
    logger.
    """
    return logging.getLogger(f'{LOGGER_ROOT}.{name}')


def _is_plain_stream_handler(handler: logging.Handler) -> bool:
    """Return whether *handler* is a stream sink rather than a file sink."""
    return isinstance(handler, logging.StreamHandler) and not isinstance(
        handler, logging.FileHandler
    )


def _human_formatter() -> logging.Formatter:
    """Return the human formatter used by the server stream boundary."""
    return logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)-7s %(message)s'
    )


def _server_logger(logger: logging.Logger | None) -> logging.Logger:
    """Resolve the shared logger without bootstrapping provider infrastructure."""
    return logger if logger is not None else logging.getLogger(LOGGER_ROOT)


def install_server_stream_handler(
    logger: logging.Logger | None = None,
) -> logging.StreamHandler:
    """Install the one server-only stderr stream handler.

    The default path is deliberately dependency-free: an extracted FastAPI
    platform entrypoint can install the operator-visible stream without
    importing provider-owned ``logger_config``.  The provider compatibility
    wrapper supplies its already-bootstrapped logger, preserving the legacy
    public API and existing in-memory/file sinks.
    """
    root = _server_logger(logger)
    with _SERVER_STREAM_LOCK:
        candidates = [
            handler
            for handler in root.handlers
            if _is_plain_stream_handler(handler)
        ]
        marked = [
            handler
            for handler in candidates
            if getattr(handler, _SERVER_STREAM_HANDLER_MARKER, False) is True
        ]
        handler = marked[0] if marked else (candidates[0] if candidates else None)

        if handler is None:
            handler = logging.StreamHandler(sys.stderr)
            root.addHandler(handler)

        # A test or embedding host may have left more than one plain stream
        # handler on this logger. Retain one so the server guarantee is about
        # emitted lines, not merely our marker.
        for duplicate in candidates:
            if duplicate is handler:
                continue
            root.removeHandler(duplicate)
            try:
                duplicate.close()
            except Exception:
                pass

        # ``setStream`` updates a handler retained across redirected-stderr
        # test windows and makes the production target explicit.
        set_stream = getattr(handler, 'setStream', None)
        if callable(set_stream):
            set_stream(sys.stderr)
        else:  # pragma: no cover - supported Python exposes setStream
            handler.stream = sys.stderr
        handler.setLevel(logging.INFO)
        handler.setFormatter(_human_formatter())
        setattr(handler, _SERVER_STREAM_HANDLER_MARKER, True)
        return handler


def get_server_stream_handler(
    logger: logging.Logger | None = None,
) -> logging.StreamHandler | None:
    """Return the installed server stream without bootstrapping logging."""
    root = logger
    if root is None:
        root = logging.getLogger(LOGGER_ROOT)
    with _SERVER_STREAM_LOCK:
        for handler in root.handlers:
            if getattr(handler, _SERVER_STREAM_HANDLER_MARKER, False) is True:
                return handler
    return None
