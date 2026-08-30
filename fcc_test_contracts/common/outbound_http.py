"""W3C Trace Context outbound HTTP propagation SSOT (P0-3, 2026-05-25).

직전 sprint P1-1 (https://www.w3.org/TR/trace-context/) 는 *inbound* HTTP/WS 만
처리했다. 본 모듈이 **outbound** 호출(외부 IdP JWKS / Microsoft Teams webhook /
미래 platform-provider HTTP client) 시 W3C 표준 ``traceparent`` 헤더를 자동
빌드하여 distributed tracing cross-service propagation 을 양방향으로 완성한다.

설계 (W3C spec § 3.2 "Mutating the traceparent Field" 준수):

- **부모 trace 존재** (``TRACE_ID_CTX`` 가 비어 있지 않음): 부모 ``trace_id`` 그대로
  유지하면서 새 ``span_id`` 생성 — outbound 호출이 부모 span 의 child span 으로
  레지스터됨. backend (Loki/Datadog/ELK) 가 inbound→outbound 를 한 trace 로 묶음.
- **root 시점** (``TRACE_ID_CTX`` 비어 있음 — outbound-first scheduled job 등):
  새 ``trace_id`` + ``span_id`` 동시 생성 → 본 호출이 trace 의 root.
- **caller explicit override**: ``existing`` mapping 에 이미 ``traceparent`` 가
  포함되어 있으면 우선 — drift 디버깅 / 외부 시스템과의 manual trace
  reconciliation 시나리오 지원.
- **existing 헤더 손실 0**: ``Accept`` / ``Authorization`` / ``Content-Type`` 등
  caller 헤더는 그대로 merge.

P1-B (2026-05-25) sampler 위임 — ``sampled`` 인자 default ``None`` 으로 변경.
None 시 ``application.common.trace_sampler.current_sampler()`` 위임 (OTel SDK
``ParentBased(root=AlwaysOn)`` default). 명시 ``True`` / ``False`` caller
override 는 그대로 보존 (debugging / forced sampling). parent decision 은
``current_parent_sampled()`` 로 조회 (root 시점은 None).

dependency-free — stdlib 만 사용 (``application.common.correlation`` +
``application.common.trace_sampler`` 동일 layer).
TestApplicationCommonPurity invariant 봉인 대상.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from fcc_test_contracts.common.correlation import (
    current_parent_sampled,
    current_trace_id,
    current_tracestate,
    format_traceparent_unchecked,
    format_tracestate,
    generate_trace_and_span_ids,
    generate_span_id,
    generate_trace_id,
    parse_tracestate,
)
from fcc_test_contracts.common.trace_sampler import current_sampler


__all__ = [
    'TRACEPARENT_HEADER',
    'TRACESTATE_HEADER',
    'build_outbound_traceparent_headers',
]


# HTTP 헤더 이름은 case-insensitive 이지만 W3C spec 은 lower-case 권장.
TRACEPARENT_HEADER: str = 'traceparent'
TRACESTATE_HEADER: str = 'tracestate'


def build_outbound_traceparent_headers(
    *,
    existing: Mapping[str, str] | None = None,
    trace_id_generator: Callable[[], str] = generate_trace_id,
    span_id_generator: Callable[[], str] = generate_span_id,
    sampled: Optional[bool] = None,
    tracestate: str | None = None,
) -> dict[str, str]:
    """W3C-compliant outbound ``traceparent`` 헤더 SSOT.

    Args:
        existing: caller 가 보존하고 싶은 헤더 (예: ``Accept`` / ``Content-Type``).
            이 mapping 안에 이미 ``traceparent`` (case-insensitive) 가 있으면
            그 값을 우선 — caller override SSOT. None 이면 빈 dict 시작.
        trace_id_generator: root 시점에서 새 trace_id 생성기. 테스트에서 결정성
            확보 위해 monkey-patch 가능. 기본 ``correlation.generate_trace_id``.
        span_id_generator: 항상 새 span 생성기 (W3C spec: outbound 시 항상 새
            span 으로 부모 span 의 child 등록). 기본 ``correlation.generate_span_id``.
        sampled: W3C trace flags 의 sampled bit. P1-B (2026-05-25) — default
            ``None`` 시 ``trace_sampler.current_sampler()`` 위임 (OTel SDK
            ``ParentBased(root=AlwaysOn)`` default — root 시 AlwaysOn → True,
            parent 있으면 parent decision 보존). ``True`` / ``False`` 명시 시
            caller override 보존 (debugging / forced).

    Returns:
        새 dict — caller 가 mutate 해도 다음 호출 영향 0 (defensive copy).
        반드시 ``traceparent`` 키 1개 포함. 기존 헤더가 있으면 모두 보존.

    부모 trace 분기 (W3C spec § 3.2):

    1. ``TRACE_ID_CTX`` 비어 있지 않음 (inbound middleware 가 이미 bind):
       부모 ``trace_id`` 유지 + 새 ``span_id`` 생성. backend 에서 같은 trace 의
       child span 으로 자동 인식. parent_sampled 는 ``current_parent_sampled()``
       조회.
    2. ``TRACE_ID_CTX`` 비어 있음 (root 시점):
       새 ``trace_id`` + ``span_id`` 동시 생성. 본 호출이 trace 의 root.
       parent_sampled = None 으로 sampler 호출.

    Note:
        format_traceparent 는 invalid input (all-zero / 길이 mismatch) 시
        ``ValueError`` raise — silent corruption 방지. caller 가 잘못된
        generator 를 주입하면 즉시 noisy fail.
    """
    headers: dict[str, str] = dict(existing) if existing else {}

    # caller explicit override — case-insensitive 검색.
    has_traceparent_override = False
    has_tracestate_override = False
    for key in headers:
        if key.lower() == TRACEPARENT_HEADER:
            has_traceparent_override = True
        if key.lower() == TRACESTATE_HEADER:
            has_tracestate_override = True

    if not has_tracestate_override:
        effective_tracestate = current_tracestate() if tracestate is None else tracestate
        if effective_tracestate:
            canonical_tracestate = format_tracestate(parse_tracestate(effective_tracestate))
            if canonical_tracestate:
                headers[TRACESTATE_HEADER] = canonical_tracestate

    if has_traceparent_override:
        return headers

    parent_trace_id = current_trace_id()
    if parent_trace_id:
        # W3C spec § 3.2 — parent trace 안의 새 child span.
        # 부모 span_id 는 사용하지 않는다 (그건 부모의 식별자 — outbound 의
        # 자신은 새 span 으로 등록되어야 함).
        trace_id = parent_trace_id
        span_id = span_id_generator()
        parent_sampled: Optional[bool] = current_parent_sampled()
    elif (
        trace_id_generator is generate_trace_id
        and span_id_generator is generate_span_id
    ):
        trace_id, span_id = generate_trace_and_span_ids()
        parent_sampled = None
    else:
        # root outbound with caller-supplied deterministic generators.
        trace_id = trace_id_generator()
        span_id = span_id_generator()
        parent_sampled = None

    if sampled is None:
        # P1-B (2026-05-25) — OTel ParentBased(AlwaysOn) default 위임.
        effective_sampled = current_sampler().should_sample(
            trace_id, parent_sampled,
        )
    else:
        # caller explicit override — debugging / forced sampling.
        effective_sampled = sampled

    headers[TRACEPARENT_HEADER] = format_traceparent_unchecked(
        trace_id, span_id, sampled=effective_sampled,
    )
    return headers
