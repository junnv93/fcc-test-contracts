"""Boot-time enforcement of the proxy-trust configuration (2026-08-22).

The *judgement* — which sources may be trusted as our own reverse proxy — is the
pure policy in :mod:`domain.services.proxy_trust_policy`. This module is the thin
env-reading boundary that runs it once per process, at the ASGI factory, next to
``install_sampler_from_env``: both are process-level, env-driven concerns that
must be settled before the first request is served.

## Why a *refusal* and not a warning

The dangerous configuration here fails **silently**. If the trusted set grows to
swallow the real client, uvicorn's reverse walk over ``X-Forwarded-For`` steps
past that client and returns the **leftmost** entry — the one an attacker wrote —
and no exception is raised, no status code changes, and no measurement looks
wrong. Every downstream consumer of the peer address (the rate-limit peer tier,
the spraying observation key) then keys on a value the attacker chose.

A warning is the right response to *degradation*; it is the wrong response to a
configuration whose whole failure mode is that nobody notices. So:

* an unsafe value **refuses to boot**, naming the entry and why;
* an absent value **boots and announces** — that is today's shipped state and it
  is a capacity fact, not a hazard (see :func:`peer_axis_mode`).

## ⚠️ There is deliberately no bypass variable

This repository's hygiene gates are fail-open with a loud notice, because a
false positive there costs more than the defect. That reasoning does **not**
transfer: the refusal here has no false positive to trade against — the values it
refuses are exactly the values that hand an attacker the peer identity. An escape
hatch for "trust everything" is just "trust everything", reached one variable
later. The honest fix is always to name the hop.

⚠️ **The variable is uvicorn's own** (``FORWARDED_ALLOW_IPS``). We do not invent
an alias: with two names, an operator can set ours, watch this module approve it,
and have uvicorn keep its loopback default — approval of a value nothing reads.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional, Tuple

from fcc_test_contracts.common.logging_channel import get_logger
from fcc_test_contracts.common.operator_notice import (
    CHANNEL_PROXY_TRUST,
    announce,
)
from fcc_test_contracts.common.proxy_trust_policy import (
    TRUSTED_PROXY_ENV,
    TrustDefect,
    describe_defect,
    parse_trusted_proxies,
    peer_axis_mode,
    trust_defects,
)


__all__ = [
    'CLIENT_RANGES_ENV',
    'DEGRADED_PEER_AXIS_PHRASE',
    'REFUSAL_PREFIX',
    'TRUSTED_PROXY_ENV',
    'enforce_trusted_proxy_config',
    'observe_local_gateways',
    'resolve_client_ranges',
    'resolve_peer_axis_mode',
    'resolve_trusted_proxies',
]


#: Optional operator declaration of where real clients live (comma-separated
#: CIDRs). Present, it lets the policy refuse a trusted set that overlaps them.
#: Absent, that one check is **skipped** — the other two still run. A gate that
#: refuses because it cannot observe is a gate that gets switched off.
CLIENT_RANGES_ENV = 'FCC_CENTRAL_CLIENT_RANGES'

#: Module-level SSOT for the two operator-facing phrases, so the runbook can
#: point at a string this code actually emits and a rename moves both together
#: (the same discipline the revocation-eviction phrases already use).
REFUSAL_PREFIX = 'refusing to start: unsafe proxy trust configuration'
DEGRADED_PEER_AXIS_PHRASE = (
    'peer rate-limit tier is charged per DEPLOYMENT, not per caller'
)

_LOGGER_NAME = 'proxy_trust'


def _announce(log, level: str, message: str) -> None:
    """Say it to the logger **and** to the stream ``docker logs`` reads.

    ⚠️ **The reasoning moved, not the behaviour.** Why the logger alone does not
    reach the operator — and why that is answered here rather than by attaching
    a handler — now lives in ``operator_notice``, because a second wave measured
    the same failure on a different message and produced a third copy of these
    two lines. One of those copies sat in ``src/infrastructure/``, where a raw
    ``print`` is forbidden outright, so the idiom needed an owner rather than
    another sibling. This function stays as the name ADR-0021 ``D-14`` and
    contract ``M-7`` point at; the channel tag it emits is unchanged.
    """
    announce(CHANNEL_PROXY_TRUST, message, log=log, level=level)


def _read(environ: Optional[Mapping[str, str]], key: str) -> str:
    source = os.environ if environ is None else environ
    try:
        value = source.get(key)
    except Exception:  # noqa: BLE001 — a hostile mapping must not break boot
        return ''
    return value if isinstance(value, str) else ''


#: Where Linux publishes the kernel routing table. Read, never parsed elsewhere.
_ROUTE_TABLE = '/proc/net/route'
#: A default route's destination and mask are both all-zero in that table.
_DEFAULT_ROUTE_HEX = '00000000'


def observe_local_gateways(route_table: str = _ROUTE_TABLE) -> Tuple[str, ...]:
    """This host's default-gateway addresses, or ``()`` when it cannot be read.

    ⚠️ **This is an observation the policy cannot make for itself.** The policy is
    pure; *"what does this machine route through"* is a fact about the machine, so
    it is read here and passed in — the same separation
    ``artifact_custody_policy`` and ``workbook_upload_gc_policy`` already use.

    Why it matters: from inside a container, a connection that arrived through a
    **published port** presents as the bridge gateway. So trusting the gateway
    trusts every caller who can reach a published port. Adversarial review
    measured that end to end — the throttle disappeared entirely.

    Total and best-effort. On Windows (a chamber node) the file does not exist and
    this answers ``()``, which makes the check skip rather than fail: a gate that
    refuses because it could not observe is a gate that gets switched off.
    """
    try:
        with open(route_table, 'r', encoding='ascii', errors='replace') as handle:
            lines = handle.read().splitlines()
    except Exception:  # noqa: BLE001 — absent on non-Linux; never fatal
        return ()
    gateways = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 8:
            continue
        destination, gateway_hex, mask = fields[1], fields[2], fields[7]
        if destination != _DEFAULT_ROUTE_HEX or mask != _DEFAULT_ROUTE_HEX:
            continue
        try:
            packed = int(gateway_hex, 16)
        except ValueError:
            continue
        if not packed:
            continue
        # little-endian hex, as the kernel writes it
        octets = [(packed >> shift) & 0xFF for shift in (0, 8, 16, 24)]
        address = '.'.join(str(octet) for octet in octets)
        if address not in gateways:
            gateways.append(address)
    return tuple(gateways)


def resolve_trusted_proxies(
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[str, ...]:
    """The entries uvicorn will build its trust set from, normalised."""
    return parse_trusted_proxies(_read(environ, TRUSTED_PROXY_ENV))


def resolve_client_ranges(
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[str, ...]:
    """The operator's declaration of where real clients live (may be empty)."""
    return parse_trusted_proxies(_read(environ, CLIENT_RANGES_ENV))


def resolve_peer_axis_mode(
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """The **expectation** axis for this process: ``per-source`` or ``deployment-wide``.

    A one-line env boundary over :func:`peer_axis_mode`, so the observation axis
    (:mod:`application.common.peer_axis_observer`) reads the same resolution the
    boot announcement does. Re-reading ``FORWARDED_ALLOW_IPS`` in a second place
    would be a second answer to *"is a hop trusted"*, and the looser of two
    answers becomes the effective policy.

    ⚠️ This is the **expectation**, not the observation — it says the server is
    prepared to restore the real address, not that different addresses arrive.
    That distinction is the whole reason the observation axis exists; see
    :mod:`domain.services.peer_axis_observation`.
    """
    return peer_axis_mode(resolve_trusted_proxies(environ))


def enforce_trusted_proxy_config(
    environ: Optional[Mapping[str, str]] = None,
    *,
    logger=None,
) -> Tuple[str, ...]:
    """Refuse an unsafe trust configuration; announce a degraded one.

    Returns the resolved entries so a caller may report them. Raises
    :class:`ValueError` when the policy names any defect — uvicorn's ``--factory``
    load turns that into a clean, loud non-start.
    """
    log = logger if logger is not None else get_logger(_LOGGER_NAME)
    entries = resolve_trusted_proxies(environ)
    defects: Tuple[TrustDefect, ...] = trust_defects(
        entries,
        client_ranges=resolve_client_ranges(environ),
        local_gateways=observe_local_gateways(),
    )
    if defects:
        reasons = '; '.join(describe_defect(defect) for defect in defects)
        raise ValueError(
            f'{REFUSAL_PREFIX}: {TRUSTED_PROXY_ENV}={_read(environ, TRUSTED_PROXY_ENV)!r} — '
            f'{reasons} '
            # ⚠️ 이 문장은 **두 종류의 호스트**가 읽는다. 중앙 허브에는 리버스 프록시가
            # 있고 챔버 노드에는 없다 — 후자에게 "프록시 주소를 적어라" 는 실행 불가능한
            # 지시이고, 옳은 조치(변수를 지운다)는 어디에도 적혀 있지 않았다.
            f'If this host runs behind a reverse proxy, name that proxy by its own '
            f'address and nothing wider. If it does not (a chamber node serves the '
            f'session API directly), unset {TRUSTED_PROXY_ENV} instead.'
        )

    mode = peer_axis_mode(entries)
    if not entries:
        # Not a defect — this is the shipped default, and behind a reverse proxy
        # it is exactly why a source ceiling may not be tightened yet
        # (ADR-0021 D-11). Said out loud so it is an observation, not a guess.
        _announce(log, 'warning', (
            f'{TRUSTED_PROXY_ENV} is unset, so the transport source address is '
            f'taken as presented by the immediate peer. If this host sits behind a '
            f'reverse proxy that peer is ONE address, and then the '
            f'{DEGRADED_PEER_AXIS_PHRASE}. If it serves callers directly (a chamber '
            f'node), the address is already the real caller and nothing is lost. '
            f'(peer-axis mode: {mode}).'
        ))
    else:
        _announce(log, 'info', (
            f'proxy trust configured: {TRUSTED_PROXY_ENV}={",".join(entries)} '
            f'(peer-axis mode: {mode})'
        ))
    return entries
