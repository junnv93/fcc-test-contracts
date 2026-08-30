"""Environment-variable readers used by typed runtime configs (F-2-D4 SSOT).

Both ``SessionApiConfig`` and ``HeadlessApiConfig`` previously held duplicate
``_env_text`` / ``_env_bool`` / ``_env_int`` / ``_env_float`` / ``_env_csv`` /
``_env_paths`` helpers. Consolidated here to remove the drift surface.
"""
from __future__ import annotations

from typing import Mapping


__all__ = [
    'read_text',
    'read_bool',
    'read_int',
    'read_float',
    'read_csv',
    'read_paths',
]


def read_text(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key, '') or '').strip()


def read_bool(environ: Mapping[str, str], key: str, *, default: bool) -> bool:
    raw = read_text(environ, key)
    if not raw:
        return default
    return raw.lower() in {'1', 'true', 'yes', 'on'}


def read_int(environ: Mapping[str, str], key: str, *, default: int) -> int:
    raw = read_text(environ, key)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{key} must be > 0, got {value}")
    return value


def read_float(environ: Mapping[str, str], key: str, *, default: float) -> float:
    raw = read_text(environ, key)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be a float, got {raw!r}") from exc
    if value < 0:
        raise ValueError(f"{key} must be >= 0, got {value}")
    return value


def read_csv(environ: Mapping[str, str], key: str) -> tuple[str, ...]:
    """Comma- or semicolon-separated origin list. Empty → empty tuple."""
    raw = read_text(environ, key)
    if not raw:
        return ()
    normalized = raw.replace(';', ',')
    return tuple(part.strip() for part in normalized.split(',') if part.strip())


def read_paths(environ: Mapping[str, str], key: str) -> tuple[str, ...]:
    """Semicolon-separated filesystem paths. Windows-safe (drive ``C:`` keeps the colon)."""
    raw = read_text(environ, key)
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(';') if part.strip())
