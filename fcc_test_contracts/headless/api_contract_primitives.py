"""Headless contract surface — api contract primitives."""
from __future__ import annotations

from typing import Optional



class ApiContractError(ValueError):
    """Raised when API request data violates the shared contract.

    ``field`` names WHICH request field was rejected, when the raising site
    structurally knows it — and the sites that decode a named field always do,
    because the name is an argument they were already holding. It rides to the
    client in the RFC 9457 ``params`` extension, declared by
    ``PROBLEM_PARAM_FIELDS``.

    Without it a 400 could say only *"the request failed"*: the server knew the
    offending axis, wrote it into a human sentence, and the screen could not read
    that sentence without parsing prose written for a person — which this
    repository forbids, and rightly, since the prose names Python-side types
    (``'NOPE' is not a valid BtPacket``).

    ⚠️ **This lane is dependency-free (SPLIT-1, P0), so the declaration is a bare
    literal** — it must not import the allow-list it has to satisfy. The
    ``⊆ PROBLEM_PARAM_ALLOWLIST`` check therefore lives in the gate
    (``tests/test_problem_params_axis``), which walks every declaring class.

    ``field`` is keyword-only and optional, so every existing
    ``raise ApiContractError('…')`` site is untouched and its wire body is
    byte-identical.
    """

    #: RFC 9457 ``params`` this refusal publishes (⊆ ``PROBLEM_PARAM_ALLOWLIST``).
    PROBLEM_PARAM_FIELDS = ('field',)

    def __init__(self, message: str = '', *, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.field = field


def require_object(value, label: str) -> dict:
    """Public wire guard: a JSON body or field must be an object.

    Public because dependent lanes decode wire payloads too, and the only other
    way for them to get this check is to copy it — which is how a one-line
    ``isinstance`` guard becomes two definitions with two error strings. One
    definition, one name: there is deliberately no private alias.
    """
    if not isinstance(value, dict):
        raise ApiContractError(f"{label} must be an object")
    return value


def _optional_text(value) -> str:
    if value is None:
        return ''
    return str(value).strip()
