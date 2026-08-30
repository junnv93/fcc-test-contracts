"""HTTP/WS correlation context SSOT (Deep #1, 2026-05-24 + P1-1 W3C, 2026-05-25
+ P1-A tracestate, 2026-05-22 + P1-D parent_sampled Optional[bool], 2026-05-22).

OBS-1 의 ``X-Request-Id`` / ``connection_id`` 가 단순 log message token 이 아니라
표준 ``contextvars.ContextVar`` 로 propagate 돼야 한다 — middleware/WS handler 가
값을 set 하면 downstream (use case, port adapter, application service) 까지
같은 logical task 에서 자동 노출.

P1-1 (2026-05-25) — W3C Trace Context spec
(https://www.w3.org/TR/trace-context/) 준수 추가. ``traceparent`` 헤더의
``trace_id`` / ``span_id`` 가 ContextVar 로 흐르며, structured JSON sink 가
top-level 필드로 노출 (OTel Log Data Model 표준).

P1-A (2026-05-22) — W3C spec § 3.3 ``tracestate`` vendor extension. vendor-
specific metadata (Datadog ``dd=p:abc``, AWS X-Ray ``aws=Root=...``) 가
``traceparent`` 와 함께 inbound/outbound propagate 된다. ``parse_tracestate`` +
``format_tracestate`` + ``mutate_tracestate`` 가 spec § 3.3.1 "Mutating the
tracestate Field" 정확히 구현한다.

P1-D (2026-05-22) — W3C spec § 3.2 의 "root context = no parent flags"
시멘틱 정공 마이그레이션. ``PARENT_SAMPLED_CTX`` 가 ``ContextVar[Optional[bool]]``
+ default ``None``. ``current_parent_sampled() -> Optional[bool]``.
``bind_trace_context(..., sampled: Optional[bool] = None)`` — None 시
ParentBasedSampler 가 root sampler 위임 (OTel SDK § 6.4 정확). 옛 P1-B 의
``default=True`` (half-migrated bool 잔재) 는 producer/consumer 시멘틱 비대칭
유발 — outbound_http.py 는 이미 ``Optional[bool]`` 어노테이션, ParentBased
SampleR 는 ``if parent_sampled is None: root 위임`` 분기 보유, 그러나
producer 만 ``bool`` 반환으로 None 이 흘러나오지 않던 결함을 본 sprint 봉합.

설계:
- ``REQUEST_ID_CTX`` / ``CONNECTION_ID_CTX`` / ``TRACE_ID_CTX`` /
  ``SPAN_ID_CTX`` / ``TRACESTATE_CTX`` — module-level ContextVar.
- ``bind_request_id`` / ``bind_connection_id`` / ``bind_trace_context`` /
  ``bind_tracestate`` — set 토큰 반환하는 context manager.
- ``parse_traceparent`` / ``parse_tracestate`` — W3C spec 준수 파서.
- ``format_traceparent`` / ``format_tracestate`` — 표준 출력 SSOT.
- ``mutate_tracestate(existing, *, vendor, value)`` — § 3.3.1 vendor entry
  move-to-front semantic.
- ``generate_trace_id`` / ``generate_span_id`` — incoming 헤더 없을 때 random hex.
- ``CorrelatedLoggerAdapter`` — 표준 ``logging.LoggerAdapter`` 확장.

dependency-free: stdlib 만 (``contextvars`` / ``logging`` / ``re`` / ``secrets``).
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import re
import secrets
from functools import lru_cache
from typing import Iterator, Optional, Sequence, Tuple


__all__ = [
    'CONNECTION_ID_CTX',
    'MAX_TRACESTATE_BYTES',
    'PARENT_SAMPLED_CTX',
    'REQUEST_ID_CTX',
    'SPAN_ID_CTX',
    'TRACE_ID_CTX',
    'TRACESTATE_CTX',
    'TRACESTATE_MAX_ENTRIES',
    'CorrelatedLoggerAdapter',
    'bind_connection_id',
    'bind_request_id',
    'bind_trace_context',
    'bind_tracestate',
    'current_connection_id',
    'current_correlation_dict',
    'current_parent_sampled',
    'current_request_id',
    'current_span_id',
    'current_trace_id',
    'current_tracestate',
    'format_traceparent',
    'format_traceparent_unchecked',
    'format_tracestate',
    'generate_trace_and_span_ids',
    'generate_span_id',
    'generate_trace_id',
    'get_correlated_logger',
    'mutate_tracestate',
    'parse_traceparent',
    'parse_tracestate',
]


_UNSET = ''


REQUEST_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar(
    'fcc_request_id', default=_UNSET,
)
CONNECTION_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar(
    'fcc_connection_id', default=_UNSET,
)
# P1-1 (2026-05-25) — W3C Trace Context spec ContextVars.
TRACE_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar(
    'fcc_trace_id', default=_UNSET,
)
SPAN_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar(
    'fcc_span_id', default=_UNSET,
)
# P1-B (2026-05-25) — W3C Trace Context sampled bit ContextVar.
# P1-D (2026-05-22) — ``Optional[bool]`` 시멘틱 정공 마이그레이션. default
# ``None`` = "no parent in scope" (W3C spec § 3.2 root context). 옛 P1-B 의
# ``default=True`` 는 half-migrated — outbound_http.py 는 이미 ``Optional[bool]``
# 어노테이션 보유, ParentBasedSampler 는 ``if parent_sampled is None: root 위임``
# 분기 보유, 그러나 producer (current_parent_sampled) 만 ``bool`` 반환으로
# 송신 시 None 이 흘러나오지 않던 비대칭.
# 정공법: producer→consumer 양쪽 모두 Optional[bool] — root context 시 None,
# middleware 가 W3C traceparent flags sampled bit 추출 시 True/False 명시 bind.
# OTel Log Data Model 권장 — root span 의 log record 는 ``parent_sampled`` 키
# 부재 (``_coerce_json_safe`` 가 None skip).
PARENT_SAMPLED_CTX: contextvars.ContextVar[Optional[bool]] = contextvars.ContextVar(
    'fcc_parent_sampled', default=None,
)
# P1-A (2026-05-22) — W3C spec § 3.3 tracestate vendor extension ContextVar.
# canonical string ("k1=v1,k2=v2") 그대로 저장. parse 비용을 매 호출 발생시키지
# 않으려고 string 형태 보존 — middleware 가 parse + canonical 재출력 후 bind.
# default ``''`` (empty tracestate, spec 상 valid → propagate skip).
TRACESTATE_CTX: contextvars.ContextVar[str] = contextvars.ContextVar(
    'fcc_tracestate', default='',
)


# ── W3C Trace Context — parsing / generation SSOT ──────────────────────────
#
# spec: https://www.w3.org/TR/trace-context/#traceparent-header-field-values
# format: ``{version}-{trace-id}-{parent-id}-{trace-flags}``
#   - version    : 2 hex digits (only ``00`` defined today)
#   - trace-id   : 32 hex digits (16 bytes), NOT all-zero
#   - parent-id  : 16 hex digits (8 bytes), NOT all-zero
#   - trace-flags: 2 hex digits — lowest bit is ``sampled`` (``01`` = sampled)
_TRACEPARENT_PATTERN: re.Pattern[str] = re.compile(
    r'^(?P<version>[0-9a-f]{2})-'
    r'(?P<trace_id>[0-9a-f]{32})-'
    r'(?P<span_id>[0-9a-f]{16})-'
    r'(?P<flags>[0-9a-f]{2})$'
)
_TRACE_ID_ZERO: str = '0' * 32
_SPAN_ID_ZERO: str = '0' * 16


def parse_traceparent(header: str) -> Optional[Tuple[str, str, bool]]:
    """W3C ``traceparent`` 헤더를 ``(trace_id, span_id, sampled)`` 로 분해.

    - invalid 형식 (잘못된 hex, 길이 미달, all-zero trace_id/span_id) → ``None``
    - version ``00`` 외 미지원 → ``None`` (spec 권장: 알려진 version 만 수용)
    - sampled 비트: ``flags & 0x01``

    spec 의 ``"if version is unknown, the receiver MUST treat traceparent as
    if it doesn't exist"`` 조항에 따라 invalid 시 None — caller 는 자체 trace
    를 시작해야 한다.
    """
    if not header:
        return None
    match = _TRACEPARENT_PATTERN.match(header.strip().lower())
    if match is None:
        return None
    if match.group('version') != '00':
        # spec: "When traceparent's version field is greater than 00,
        # implementations MUST NOT use the traceparent value unless they
        # can guarantee the correct interpretation". 안전한 폴백: None.
        return None
    trace_id = match.group('trace_id')
    span_id = match.group('span_id')
    if trace_id == _TRACE_ID_ZERO or span_id == _SPAN_ID_ZERO:
        return None
    flags = int(match.group('flags'), 16)
    sampled = bool(flags & 0x01)
    return trace_id, span_id, sampled


def format_traceparent(
    trace_id: str, span_id: str, *, sampled: bool = True,
) -> str:
    """``(trace_id, span_id, sampled)`` → W3C canonical ``traceparent`` 문자열.

    ``version='00'`` + ``flags='01'`` (sampled) 기본. spec 의 invalid value
    (all-zero / 길이 mismatch) 는 ``ValueError`` raise — silent corruption
    방지.
    """
    if len(trace_id) != 32 or not all(c in '0123456789abcdef' for c in trace_id.lower()):
        raise ValueError(f'invalid trace_id: {trace_id!r} (expect 32 hex chars)')
    if len(span_id) != 16 or not all(c in '0123456789abcdef' for c in span_id.lower()):
        raise ValueError(f'invalid span_id: {span_id!r} (expect 16 hex chars)')
    if trace_id == _TRACE_ID_ZERO or span_id == _SPAN_ID_ZERO:
        raise ValueError('trace_id / span_id must not be all-zero (W3C spec)')
    flags = '01' if sampled else '00'
    return f'00-{trace_id.lower()}-{span_id.lower()}-{flags}'


def format_traceparent_unchecked(
    trace_id: str, span_id: str, *, sampled: bool = True,
) -> str:
    """Fast-path formatter for IDs already validated or locally generated.

    Outbound propagation builds this header on every external HTTP call. The
    public ``format_traceparent`` function remains the validating boundary for
    untrusted input; this helper is for trusted ContextVar values parsed by
    ``parse_traceparent`` or IDs returned by this module's generators.
    """
    flags = '01' if sampled else '00'
    return f'00-{trace_id}-{span_id}-{flags}'


# ── W3C Trace Context — tracestate (§ 3.3) ─────────────────────────────────
#
# spec: https://www.w3.org/TR/trace-context/#tracestate-header-field-values
#
# format:   ``key1=value1,key2=value2`` (comma 구분, OWS 허용 — RFC 7230 § 3.2.3)
# max 32 entries (spec § 3.3.3 "List of Members").
# key syntax (simple-key):
#   - ``[a-z][a-z0-9_\-*/]{0,255}`` (256 char max — spec § 3.3.2)
#   - vendor 별 다중 tenant (예: ``rojo@vendor=...``) 도 spec 에 정의되지만
#     본 SSOT 는 simple-key 만 — multi-tenant-key 는 후속 sprint.
# value syntax:
#   - ``[\x20-\x2b\x2d-\x3c\x3e-\x7e]{0,255}`` (printable ASCII 제외 ',' '=')
#   - trailing space 제거 (spec § 3.3.2 "value rules").
#
# Mutating rules (§ 3.3.1):
#   1. 기존 vendor entry → 맨 앞 이동 + value 갱신.
#   2. 신규 vendor entry → prepend (맨 앞 추가).
#   3. 32 limit 초과 → 마지막 entry 제거.
TRACESTATE_MAX_ENTRIES: int = 32

# spec § 3.3.3 "Combined Header Length" — tracestate 권장 byte 상한.
# 정확한 spec wording:
#   "There might be tracestate headers more than 512 characters but it is
#    recommended to keep them shorter than 512 characters. The receiver MUST
#    accept tracestate header up to 512 characters or any other limit defined
#    by application requirements."
# 정책: outbound generation 시 절대 512 초과하지 않는다 (caller 가 길이 알 필요
# 없도록 ``mutate_tracestate`` 가 overflow drop 책임). inbound parse 는 spec
# "MUST accept" 준수 — byte 합 검사 없음 (32 entries 만 enforce).
# ASCII-only canonical 표현이라 ``len(str) == byte_len``.
MAX_TRACESTATE_BYTES: int = 512

# spec § 3.3.2 — simple-key 정규식. lowercase + digit start + `_-*/` 허용.
_TRACESTATE_KEY_PATTERN: re.Pattern[str] = re.compile(
    r'^[a-z0-9][a-z0-9_\-*/]{0,255}$'
)
# spec § 3.3.2 — value char set: printable ASCII (0x20~0x7E) 제외 ',' (0x2c) '=' (0x3d).
_TRACESTATE_VALUE_PATTERN: re.Pattern[str] = re.compile(
    r'^[\x20-\x2b\x2d-\x3c\x3e-\x7e]{0,255}$'
)


@lru_cache(maxsize=256)
def parse_tracestate(header: str) -> Tuple[Tuple[str, str], ...]:
    """W3C ``tracestate`` 헤더를 ``((key, value), ...)`` tuple 로 분해.

    spec § 3.3 (https://www.w3.org/TR/trace-context/#tracestate-header-field-values)
    준수:
    - 빈 헤더 → ``()`` (empty 는 spec 상 valid → propagate 안 함).
    - 각 entry 는 ``key=value`` (OWS 허용 — `` k = v `` 도 valid → ``k=v`` 로 정규화).
    - invalid entry (잘못된 key/value chars / no '=' / duplicate key) → 해당 entry skip.
    - 32 limit 초과 entries → 33번째 이후 무시 (spec § 3.3.3).
    - 첫 등장 vendor 우선 — duplicate key 는 spec 위반, 두 번째부터 skip.

    Returns:
        tuple of (key, value) tuples, max 32 entries. canonical order
        preserved (incoming order).
    """
    if not header:
        return ()
    trimmed = header.strip()
    if not trimmed:
        return ()
    entries: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    # spec § 3.3 — comma separator. 각 list-member 는 OWS 로 패딩 가능.
    for raw_entry in trimmed.split(','):
        if len(entries) >= TRACESTATE_MAX_ENTRIES:
            break
        entry = raw_entry.strip()
        if not entry:
            continue  # spec § 3.3 — empty list element 는 skip.
        # OWS-stripped entry 가 'key=value' 형태인지 검사.
        eq_idx = entry.find('=')
        if eq_idx <= 0 or eq_idx == len(entry) - 1:
            # '=' 누락, key 빈 문자열, value 빈 문자열 → skip (spec invalid).
            continue
        # spec § 3.3.2 — key 는 lowercase only. uppercase 정규화 금지 (spec
        # 위반이므로 incoming entry skip 해야 한다 — silent lowercase 변환은
        # downstream 시스템이 invalid 를 valid 로 인식하게 만드는 보안 위험).
        key = entry[:eq_idx].strip()
        value = entry[eq_idx + 1:].strip()
        if not _TRACESTATE_KEY_PATTERN.match(key):
            continue
        if not _TRACESTATE_VALUE_PATTERN.match(value):
            continue
        if key in seen_keys:
            continue  # duplicate — spec violation, 첫 등장 보존.
        seen_keys.add(key)
        entries.append((key, value))
    return tuple(entries)


def format_tracestate(entries: Sequence[Tuple[str, str]]) -> str:
    """``((key, value), ...)`` → canonical ``"k1=v1,k2=v2"`` 문자열.

    invalid entry (잘못된 char / key empty / value empty) 는 ``ValueError`` —
    silent corruption 방지. caller 가 잘못된 entry 를 주입하면 즉시 noisy fail.

    32 entry limit 초과 → ``ValueError`` (caller 가 ``mutate_tracestate`` 로
    overflow 처리 후 전달해야 함).

    W3C spec § 3.3.3 — canonical 출력 길이가 ``MAX_TRACESTATE_BYTES`` (512)
    초과 시 ``ValueError``. caller (``mutate_tracestate``) 가 byte-overflow
    drop 책임. ASCII-only 표현이므로 ``len(str) == byte_len``.
    """
    if not entries:
        return ''
    if len(entries) > TRACESTATE_MAX_ENTRIES:
        raise ValueError(
            f'tracestate entries ({len(entries)}) exceeds W3C spec § 3.3.3 '
            f'max ({TRACESTATE_MAX_ENTRIES})',
        )
    parts: list[str] = []
    for key, value in entries:
        if not _TRACESTATE_KEY_PATTERN.match(key):
            raise ValueError(f'invalid tracestate key: {key!r}')
        if not _TRACESTATE_VALUE_PATTERN.match(value):
            raise ValueError(f'invalid tracestate value: {value!r}')
        parts.append(f'{key}={value}')
    result = ','.join(parts)
    if len(result) > MAX_TRACESTATE_BYTES:
        raise ValueError(
            f'tracestate canonical length ({len(result)}) exceeds W3C spec '
            f'§ 3.3.3 byte limit ({MAX_TRACESTATE_BYTES})',
        )
    return result


@lru_cache(maxsize=256)
def mutate_tracestate(existing: str, *, vendor: str, value: str) -> str:
    """W3C spec § 3.3.1 "Mutating the tracestate Field" 정공법 구현.

    - ``existing`` 에 ``vendor`` 가 있으면 → 맨 앞 이동 + value 갱신.
    - 없으면 → prepend (맨 앞 추가).
    - 32 limit 도달 시 → 마지막 entry 제거 (이전 끝 entry 가 가장 오래된 vendor).

    Args:
        existing: canonical "k1=v1,k2=v2" string. 빈 문자열 가능.
        vendor: 추가/갱신할 vendor key (lowercase, spec § 3.3.2 simple-key).
        value: vendor value (spec § 3.3.2 char set).

    Returns:
        canonical 문자열. caller 가 그대로 ``bind_tracestate`` /
        outbound 헤더에 사용 가능.

    Raises:
        ValueError: vendor/value 가 spec syntax 위반 시.
    """
    if not _TRACESTATE_KEY_PATTERN.match(vendor):
        raise ValueError(f'invalid tracestate vendor key: {vendor!r}')
    if not _TRACESTATE_VALUE_PATTERN.match(value):
        raise ValueError(f'invalid tracestate value: {value!r}')
    # 신규 entry 단독이 spec § 3.3.3 byte limit 을 초과하면 caller invariant 위반
    # — entries 0 으로 drop 해도 새 entry 가 들어갈 자리 없음. noisy fail.
    new_entry_len = len(vendor) + 1 + len(value)  # "key=value"
    if new_entry_len > MAX_TRACESTATE_BYTES:
        raise ValueError(
            f'tracestate new entry ({new_entry_len} bytes) alone exceeds '
            f'spec § 3.3.3 limit ({MAX_TRACESTATE_BYTES})',
        )
    entries = list(parse_tracestate(existing))
    # vendor 존재 시 제거 (이후 prepend 로 맨 앞 이동 효과).
    entries = [(k, v) for (k, v) in entries if k != vendor]
    entries.insert(0, (vendor, value))
    # 32 entries limit overflow → 마지막 entry 제거 (가장 오래된).
    if len(entries) > TRACESTATE_MAX_ENTRIES:
        entries = entries[:TRACESTATE_MAX_ENTRIES]
    # spec § 3.3.3 byte limit overflow → 끝에서부터 entry drop 반복.
    # W3C spec § 3.3.1 권장 — 새 vendor 가 맨 앞 보존, oldest (끝) 부터 제거.
    while entries and _canonical_byte_length(entries) > MAX_TRACESTATE_BYTES:
        entries.pop()
    return format_tracestate(entries)


def _canonical_byte_length(entries: Sequence[Tuple[str, str]]) -> int:
    """``join(',', 'k=v')`` 의 byte 길이 — ASCII canonical, ``len(str) == bytes``.

    ``format_tracestate`` 의 byte 검사 전에 caller 가 미리 호출 가능 (zero-alloc
    fast path — 실제 string concat 없이 길이만 계산). entries=0 시 0 반환.
    """
    if not entries:
        return 0
    # n entries: sum(len(k) + 1 + len(v)) + (n-1) commas.
    return sum(len(k) + 1 + len(v) for k, v in entries) + (len(entries) - 1)


def generate_trace_id() -> str:
    """W3C-compliant random 16-byte trace_id (32 hex chars).

    ``secrets.token_hex(16)`` 는 cryptographic random — collision 가능성
    무시할 수 있는 수준. all-zero 충돌은 1/2^128 — 실질적으로 0.
    """
    return secrets.token_hex(16)


def generate_span_id() -> str:
    """W3C-compliant random 8-byte span_id (16 hex chars)."""
    return secrets.token_hex(8)


def generate_trace_and_span_ids() -> Tuple[str, str]:
    """Generate a root trace_id and child span_id with one entropy call.

    Root outbound calls need 24 random bytes total: 16 for ``trace_id`` and 8
    for ``span_id``. A single ``token_hex(24)`` call avoids doubling the CSPRNG
    boundary cost while preserving the same W3C identifier sizes.
    """
    token = secrets.token_hex(24)
    return token[:32], token[32:]


# ── ContextVar accessors ───────────────────────────────────────────────────


def current_request_id() -> str:
    """현재 logical task 의 X-Request-Id (없으면 빈 문자열)."""
    return REQUEST_ID_CTX.get()


def current_connection_id() -> str:
    """현재 WS session 의 connection_id (없으면 빈 문자열)."""
    return CONNECTION_ID_CTX.get()


def current_trace_id() -> str:
    """현재 logical task 의 W3C trace_id (없으면 빈 문자열)."""
    return TRACE_ID_CTX.get()


def current_span_id() -> str:
    """현재 logical task 의 W3C span_id (없으면 빈 문자열)."""
    return SPAN_ID_CTX.get()


def current_parent_sampled() -> Optional[bool]:
    """현재 logical task 의 W3C trace flags sampled bit.

    P1-B (2026-05-25) — OTel ParentBasedSampler 가 outbound 시점에 parent
    decision 보존을 위해 조회.

    P1-D (2026-05-22) — return type ``Optional[bool]`` 로 정공 마이그레이션.
    middleware 가 ``bind_trace_context(..., sampled=True/False)`` 로 명시
    bind 한 경우 그 값, 미명시 또는 root context 시 ``None``. OTel
    ParentBasedSampler 가 None 시 root sampler 위임 (W3C spec § 3.2 정확).
    """
    return PARENT_SAMPLED_CTX.get()


def current_tracestate() -> str:
    """현재 logical task 의 W3C ``tracestate`` canonical string (default ``''``).

    P1-A (2026-05-22) — middleware 가 incoming ``tracestate`` parse 후
    canonical 재출력 결과를 bind. outbound HTTP propagation
    (``outbound_http.build_outbound_traceparent_headers``) 이 동일 string 을
    헤더에 inject — vendor metadata (Datadog ``dd=p:abc``, AWS ``aws=Root=...``)
    가 inbound→outbound 양방향 보존.
    """
    return TRACESTATE_CTX.get()


def current_correlation_dict() -> dict[str, object]:
    """LoggerAdapter / structured-log builder 가 사용하는 표준 dict.

    P1-1 (2026-05-25) — W3C trace_id/span_id 추가. 기존 키 (request_id /
    connection_id) 는 보존 — caller 가 dict 키 누락 가정 0.
    P1-B (2026-05-25) — ``parent_sampled`` 키 추가. structured backend 가
    sampled/not-sampled facet 으로 필터링 가능.
    P1-D (2026-05-22) — ``parent_sampled`` 값 type 이 ``Optional[bool]`` —
    root context 시 ``None`` (``_coerce_json_safe`` 가 None skip → 최종 JSON
    log record 에 키 부재, OTel Log Data Model 권장).
    P1-A (2026-05-22) — ``tracestate`` string 키 추가. vendor extension 도
    backend 에서 indexable.
    """
    return {
        'request_id': REQUEST_ID_CTX.get(),
        'connection_id': CONNECTION_ID_CTX.get(),
        'trace_id': TRACE_ID_CTX.get(),
        'span_id': SPAN_ID_CTX.get(),
        'parent_sampled': PARENT_SAMPLED_CTX.get(),
        'tracestate': TRACESTATE_CTX.get(),
    }


@contextlib.contextmanager
def bind_request_id(value: str) -> Iterator[str]:
    """``with bind_request_id(rid):`` — try/finally 로 reset.

    빈 문자열을 받아도 ContextVar 에 set 한다 (override 의도 보존).
    """
    token = REQUEST_ID_CTX.set(value)
    try:
        yield value
    finally:
        REQUEST_ID_CTX.reset(token)


@contextlib.contextmanager
def bind_connection_id(value: str) -> Iterator[str]:
    token = CONNECTION_ID_CTX.set(value)
    try:
        yield value
    finally:
        CONNECTION_ID_CTX.reset(token)


@contextlib.contextmanager
def bind_trace_context(
    trace_id: str,
    span_id: str,
    *,
    sampled: Optional[bool] = None,
    tracestate: Optional[str] = None,
) -> Iterator[Tuple[str, str]]:
    """``with bind_trace_context(trace_id, span_id, sampled=..., tracestate=...):`` — 4 ContextVar 동시 bind.

    middleware 가 W3C traceparent 헤더 parse 후 한 번에 bind 하는 진입점.
    빈 문자열 입력도 set 한다 (override 의도 보존, 옛 값으로 새기지 않음).

    P1-B (2026-05-25) — ``sampled`` kwarg 추가. OTel ParentBasedSampler 가
    outbound 시점에 parent decision 보존을 위해 ``current_parent_sampled()``
    로 조회한다.

    P1-D (2026-05-22) — ``sampled`` 의 type/default 를 ``Optional[bool] = None``
    으로 정공 마이그레이션. W3C spec § 3.2 의 "root context = no parent flags"
    시멘틱 정확. middleware 가 traceparent flags 의 sampled bit 추출 시
    ``True/False`` 명시 전달, root context 시 ``None`` (= ParentBasedSampler
    root 위임).

    P1-A (2026-05-22) — ``tracestate`` kwarg 추가. W3C spec § 3.3 vendor
    extension propagation. caller 는 이미 canonical 정규화된 문자열을
    전달해야 한다 (``parse_tracestate`` + ``format_tracestate`` round-trip
    결과).

    P1-D-α (2026-05-23) — ``tracestate`` 의 type/default 를 ``Optional[str] = None``
    으로 정공 대칭화 (``sampled`` 와 동일 시멘틱 패턴). None 은 "no vendor
    metadata to propagate" 의미 — TRACESTATE_CTX 에 빈 문자열 ``''`` 로
    set (옛 행동 100% 보존, JSON formatter 가 빈 문자열 verbatim 보존, OBS-3
    typed extras spec). 명시 빈 문자열 ``''`` 도 동일 처리 (override 의도
    보존). 비어 있지 않은 string 은 그대로 set.

    옛 ``tracestate: str = ''`` 시그니처 영구 폐기 — bool 1급 시멘틱
    (``Optional[bool]``) 과 string 1급 시멘틱 (``Optional[str]``) 의 비대칭
    봉합.
    """
    trace_token = TRACE_ID_CTX.set(trace_id)
    span_token = SPAN_ID_CTX.set(span_id)
    sampled_token = PARENT_SAMPLED_CTX.set(sampled)
    # P1-D-α — None 은 "no vendor metadata" 의미. TRACESTATE_CTX 의 default
    # ('') 와 정합 — 빈 문자열로 set 하여 옛 behaviour 보존, JSON formatter
    # verbatim spec (OBS-3) 와 일관 처리.
    tracestate_token = TRACESTATE_CTX.set(tracestate if tracestate is not None else '')
    try:
        yield trace_id, span_id
    finally:
        # LIFO reset — 마지막 set 이 가장 먼저 reset.
        TRACESTATE_CTX.reset(tracestate_token)
        PARENT_SAMPLED_CTX.reset(sampled_token)
        SPAN_ID_CTX.reset(span_token)
        TRACE_ID_CTX.reset(trace_token)


@contextlib.contextmanager
def bind_tracestate(value: str) -> Iterator[str]:
    """``with bind_tracestate(canonical):`` — TRACESTATE_CTX 만 bind.

    P1-A (2026-05-22) — ``bind_trace_context`` 와 별도로 tracestate 만
    override 하고 싶을 때 (예: trace_id/span_id 는 보존, vendor entry 추가
    + outbound 호출 한 번만).

    caller 는 canonical 문자열을 전달해야 한다 (parse + format round-trip).
    빈 문자열도 set (override 의도 보존).
    """
    token = TRACESTATE_CTX.set(value)
    try:
        yield value
    finally:
        TRACESTATE_CTX.reset(token)


class CorrelatedLoggerAdapter(logging.LoggerAdapter):
    """모든 record 에 ``extra={'request_id': ..., 'connection_id': ...}`` 부착.

    structured logging backend (JSON formatter / Datadog / Loki) 가 그대로
    indexable 필드로 노출한다. 호출 시점의 ContextVar 값을 읽으므로 asyncio
    task / thread 간 자동 격리.
    """

    def process(self, msg, kwargs):
        extra = dict(kwargs.get('extra') or {})
        merged = current_correlation_dict()
        merged.update(extra)
        kwargs['extra'] = merged
        return msg, kwargs


def get_correlated_logger(name: str) -> CorrelatedLoggerAdapter:
    """Factory — 호출자가 ``get_correlated_logger(__name__)`` 한 줄로 받음."""
    return CorrelatedLoggerAdapter(logging.getLogger(name), {})
