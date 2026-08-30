"""Env → :class:`RateLimitPolicy` loader shared by the three web surfaces (2026-07-19).

Mirror of :mod:`application.common.auth_config`'s prefix pattern: one dataclass
of env-var *suffixes* (the SSOT for the names) plus a loader that resolves them
under a surface prefix — ``FCC_SESSION_`` / ``FCC_HEADLESS_`` / ``FCC_PLATFORM_``.

Coercion and per-field fallback are NOT duplicated here: raw strings go straight
into :meth:`RateLimitPolicy.from_raw`, the pure domain parser, exactly as
``PlatformApiConfig`` feeds ``ChamberProxyPolicy.from_raw``. This module only
knows *where the strings come from*.

Secure by default: an unset ``…_RATE_LIMIT_ENABLED`` yields an **enabled**
policy. The kill-switch is explicit (``…_RATE_LIMIT_ENABLED=0``), which is the
direction that fails safe — a deployment that forgets the variable is protected,
not exposed. Note this is the *composition-root* default; the app factories
still default to ``rate_limit_policy=None`` (no limiting at all) so existing
programmatic embedders and unit tests are byte-identical.

dependency-free: stdlib + ``domain.services.rate_limit_policy`` only.
"""
from __future__ import annotations

from typing import Mapping

from fcc_test_contracts.common.env_loaders import read_text
from fcc_test_contracts.common.rate_limit_policy import RateLimitPolicy


__all__ = [
    'RATE_LIMIT_ENV_FIELD_PREFIX',
    'RATE_LIMIT_ENV_SUFFIXES',
    'rate_limit_env_keys',
    'rate_limit_env_map',
    'load_rate_limit_policy',
]


#: Namespace applied when these keys are merged into a surface's flat env map
#: (``FCC_SESSION_ENV`` / ``HEADLESS_API_ENV`` / ``PLATFORM_API_ENV``), so a
#: generic name like ``enabled`` cannot collide with a surface's own field.
RATE_LIMIT_ENV_FIELD_PREFIX = 'rate_limit_'


#: ``{RateLimitPolicy.from_raw kwarg: env-var suffix}``. Single SSOT for the
#: names so the loader, the docs, and any parity audit reference one mapping.
RATE_LIMIT_ENV_SUFFIXES: dict[str, str] = {
    'enabled': 'RATE_LIMIT_ENABLED',
    'max_requests': 'RATE_LIMIT_REQUESTS',
    'window_seconds': 'RATE_LIMIT_WINDOW_SECONDS',
    'metrics_max_requests': 'RATE_LIMIT_METRICS_REQUESTS',
    'metrics_window_seconds': 'RATE_LIMIT_METRICS_WINDOW_SECONDS',
}


def rate_limit_env_keys(prefix: str) -> dict[str, str]:
    """Return ``{from_raw kwarg: full env-var name}`` for a surface prefix."""
    if not prefix:
        raise ValueError('env-var prefix must be non-empty (e.g. "FCC_SESSION_")')
    return {field: f'{prefix}{suffix}' for field, suffix in RATE_LIMIT_ENV_SUFFIXES.items()}


def rate_limit_env_map(prefix: str) -> dict[str, str]:
    """Namespaced projection of :func:`rate_limit_env_keys` for surface ENV maps.

    ``{'rate_limit_enabled': 'FCC_SESSION_RATE_LIMIT_ENABLED', ...}`` — merged
    into each surface's flat env-name map so the runbook/env-example parity
    audits (which iterate those maps) cover the new keys automatically.
    """
    return {
        f'{RATE_LIMIT_ENV_FIELD_PREFIX}{field}': env_name
        for field, env_name in rate_limit_env_keys(prefix).items()
    }


def load_rate_limit_policy(
    environ: Mapping[str, str],
    *,
    prefix: str,
    default_enabled: bool = True,
) -> RateLimitPolicy:
    """Read the rate-limit env vars under ``prefix`` into the pure policy SSOT."""
    keys = rate_limit_env_keys(prefix)
    return RateLimitPolicy.from_raw(
        enabled=read_text(environ, keys['enabled']),
        max_requests=read_text(environ, keys['max_requests']),
        window_seconds=read_text(environ, keys['window_seconds']),
        metrics_max_requests=read_text(environ, keys['metrics_max_requests']),
        metrics_window_seconds=read_text(environ, keys['metrics_window_seconds']),
        default_enabled=default_enabled,
    )
