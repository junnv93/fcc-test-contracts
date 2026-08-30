"""W3C Trace Context sampler decision port (P1-B, 2026-05-25).

Hexagonal output port — sampler 가 W3C ``traceparent`` flags 의 sampled bit
를 결정하는 cross-cutting observability concern. 구현체는
``application.common.trace_sampler`` 의 AlwaysOn/AlwaysOff/ParentBased 3 종.

OTel Sampling Spec § 6.1 의 ``Sampler.shouldSample`` 단순화 — FCC 는
attributes / links / span name / kind 기반 sampling 미활용으로 trace_id +
parent_sampled 만으로 결정한다 (YAGNI). bool 반환은 W3C ``traceparent`` flags
의 단일 sampled bit (01 / 00) 와 직접 매핑.

dependency-free — stdlib ``typing`` 만 (domain layer purity 보장).
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


__all__ = ['Sampler']


@runtime_checkable
class Sampler(Protocol):
    """W3C trace flags sampled bit decision policy.

    Args:
        trace_id: 32 hex char trace identifier. ratio-based sampler 가 hash
            decision 시 사용. AlwaysOn / AlwaysOff 는 무시.
        parent_sampled: 부모 span 의 sampled bit. ``None`` 이면 root 시점
            (parent 없음). ParentBased sampler 는 이 값을 보존.

    Returns:
        ``True`` 시 W3C ``traceparent`` flags = ``01`` (sampled).
        ``False`` 시 W3C ``traceparent`` flags = ``00`` (not sampled).
    """

    def should_sample(
        self, trace_id: str, parent_sampled: Optional[bool],
    ) -> bool:
        ...
