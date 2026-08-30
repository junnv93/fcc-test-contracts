"""W3C Trace Context sampler decision policy SSOT (P1-B + P1-C, 2026-05-25).

P0-3 (`outbound_http.build_outbound_traceparent_headers`) 의 ``sampled: bool = True``
하드코딩을 산업 표준 OpenTelemetry SDK Sampling Spec
(https://opentelemetry.io/docs/specs/otel/trace/sdk/#sampling) 의
``ParentBased(root=AlwaysOn)`` default sampler 정공법으로 대체한다.

P1-C (2026-05-25) — ``TraceIdRatioBased(ratio)`` probabilistic sampler (OTel
SDK Sampling Spec § 6.2) + OTel SDK 표준 env vars ``OTEL_TRACES_SAMPLER`` /
``OTEL_TRACES_SAMPLER_ARG`` 정공법 통합. Datadog Agent / Jaeger / OTLP
collector 등 산업 표준 ecosystem 과 동일 env 인식.

P1-D (2026-05-22) — P1-C 도입 시점에 1차 ``sampler_from_env`` /
``install_sampler_from_env`` (간이 구현) + 2차 정의 (``_VALID_SAMPLER_TOKENS``
frozenset SSOT 구현) 가 동시 잔존하던 Python 함수 shadowing dead code 영구
폐기. 본 모듈 단일 정의만 SSOT — ``_VALID_SAMPLER_TOKENS`` /
``_TOKENS_REQUIRING_RATIO_ARG`` frozenset 기반 명시 noisy fail 패턴.

설계 (OTel Sampling Spec § 6.1 ~ 6.4 + W3C Trace Context § 3.2 준수):

- ``Sampler`` Protocol — ``should_sample(trace_id, parent_sampled) -> bool``
  단일 method. OTel 의 `Sampler.shouldSample` 시그니처 (parent_context, trace_id,
  name, kind, attributes, links) 에서 FCC 미활용 인자 (name/kind/attributes/links)
  를 제거한 단순화. bool 반환은 W3C ``traceparent`` flags 의 단일 sampled bit
  (01 / 00) 와 직접 매핑.
- ``AlwaysOnSampler`` — OTel ``ALWAYS_ON`` (모든 trace sample).
- ``AlwaysOffSampler`` — OTel ``ALWAYS_OFF`` (모든 trace drop).
- ``TraceIdRatioBased(ratio)`` — OTel ``TraceIdRatioBased`` probabilistic
  sampler. ``ratio`` (0.0~1.0) 가 trace_id 의 상위 16 hex (64-bit) 기반 정수
  threshold 비교로 결정. parent_sampled 무시 (*root* sampler — parent decision
  보존은 ``ParentBasedSampler(root=TraceIdRatioBased(ratio))`` 합성).
- ``ParentBasedSampler(root)`` — OTel ``ParentBased`` 단순화. parent 가 있으면
  parent decision 보존, 없으면 ``root`` sampler 위임. OTel 의 4-way 분기
  (remote_parent_sampled / remote_parent_not_sampled / local_parent_sampled /
  local_parent_not_sampled) 는 모두 default (AlwaysOn / AlwaysOff / AlwaysOn /
  AlwaysOff) 와 동치 — FCC 는 remote/local 구분 없음으로 단순화.
- ``DEFAULT_SAMPLER`` — ``ParentBasedSampler(root=AlwaysOnSampler())`` 인스턴스.
  OTel SDK spec default 와 동일. 기존 P0-3 행동 (1.0 sampling rate root +
  parent decision 보존) 정확히 보존.
- ``TRACEPARENT_SAMPLER_CTX`` — ``ContextVar[Optional[Sampler]]`` (default
  ``None``). 테스트 / 런타임 policy switching 진입점.
- ``current_sampler()`` — ContextVar override 시 그 값, 아니면
  ``DEFAULT_SAMPLER`` fallback. outbound_http SSOT 가 매 호출에서 1회 조회.
- ``bind_sampler(sampler)`` — try/finally 로 reset 하는 context manager.
- ``sampler_from_env(environ)`` — OTel SDK 표준 env spec 6 토큰 매핑 SSOT.
- ``install_sampler_from_env(environ=None)`` — composition root entry-point.
  app boot 시 1회 호출 → process-wide ContextVar bind.

Sampler Protocol 은 hexagonal 정공법으로 ``src/domain/ports/output/trace_sampler_port.py``
에 위치 (TestProtocolPlacement invariant 봉인). 본 모듈은 구현체 (AlwaysOn /
AlwaysOff / TraceIdRatioBased / ParentBased) + DEFAULT_SAMPLER 인스턴스 +
ContextVar override + env factory 만 보유.

dependency-free — stdlib ``typing`` / ``contextvars`` / ``contextlib`` /
``os`` (env default) +
``domain.ports.output.trace_sampler_port.Sampler`` (Protocol).
TestApplicationCommonPurity invariant 봉인 대상.
"""
from __future__ import annotations

import contextlib
import contextvars
import math
import os
from typing import Iterator, Mapping, Optional

from fcc_test_contracts.common.trace_sampler_port import Sampler


__all__ = [
    'AlwaysOffSampler',
    'AlwaysOnSampler',
    'DEFAULT_SAMPLER',
    'OTEL_TRACES_SAMPLER',
    'OTEL_TRACES_SAMPLER_ARG',
    'ParentBasedSampler',
    'Sampler',
    'TRACEPARENT_SAMPLER_CTX',
    'TraceIdRatioBased',
    'bind_sampler',
    'current_sampler',
    'install_sampler_from_env',
    'sampler_from_env',
]


# ── OTel SDK 표준 env spec (https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/#general-sdk-configuration) ──
OTEL_TRACES_SAMPLER: str = 'OTEL_TRACES_SAMPLER'
OTEL_TRACES_SAMPLER_ARG: str = 'OTEL_TRACES_SAMPLER_ARG'


# ════════════════════════════════════════════════════════════════════════════
# TraceIdRatioBased threshold SSOT 상수 (2026-05-23, follow-up byte-identity)
# ════════════════════════════════════════════════════════════════════════════
#
# OTel Python SDK byte-identity 정합 SSOT — W3C Trace Context § 3.2.2.3 +
# OTel SDK Sampling Spec § 6.2 정공법.
#
# **본 sprint 자평 결함 #4 follow-up (2026-05-23)** — 초기 commit 0b53fa0
# 에서 self-reported "산업 표준 64-bit" 주장을 산업 표준 source 직접 fetch
# 검증한 결과, 실제 OTel Python SDK 는 **하위 64-bit AND mask** 사용 (FCC
# 의 옛 ``trace_id[:16]`` 상위 16 hex 슬라이스와 byte-identity 불일치).
# 정공법: OTel Python SDK 공식 구현과 정확 byte-identity 정합 채택.
#
# **OTel Python SDK 공식 source 인용 (verified 2026-05-23)**:
#   https://github.com/open-telemetry/opentelemetry-python/blob/main/
#   opentelemetry-sdk/src/opentelemetry/sdk/trace/sampling.py
#
#   ```
#   TRACE_ID_LIMIT = (1 << 64) - 1
#   ...
#   return round(rate * (cls.TRACE_ID_LIMIT + 1))   # bound 산정
#   ...
#   if trace_id & self.TRACE_ID_LIMIT < self.bound:  # 하위 64-bit AND mask
#   ```
#
# **W3C spec § 3.2.2.3**: ``trace-id`` 는 32 hex (128-bit pseudo-random).
# 모든 16 bytes 가 uniform random — sampling 비트 선택은 spec 미명시 (구현체
# 선택). OTel ecosystem 정합화 우선 → 하위 64-bit AND mask 채택.
#
# **byte-identity 정합 효과**: 같은 trace_id 입력에 대해 OTel Python SDK 와
# 본 구현체가 정확히 동일한 sample/drop 결정 도출 (FCC 와 OTel collector
# downstream ingestion 결정 일관성 보장).
#
# **향후 정책 변경 시 단일 변경 지점**: ``_TRACE_ID_BITS_USED = 64`` (W3C
# spec full 128-bit 채택 또는 다른 비트 폭 마이그레이션 시 본 상수만 변경).
#
# 회귀 가드: ``tests/test_trace_sampler_p1_c.py::TestTraceSamplerSsotConstants``
# 6 case (상수 값 + derived 산식 + AST `1 << 64` literal 폐기 + AST `& mask`
# 패턴 + OTel Python SDK byte-identity smoke + verified line 동치성).
_TRACE_ID_BITS_USED: int = 64
_TRACE_ID_LIMIT: int = (1 << _TRACE_ID_BITS_USED) - 1  # OTel Python SDK TRACE_ID_LIMIT byte-identity


class AlwaysOnSampler:
    """OTel ``ALWAYS_ON`` — 모든 trace sample.

    부모 sampled bit 무시 (record-everything policy).
    """

    __slots__ = ()

    def should_sample(
        self, trace_id: str, parent_sampled: Optional[bool],
    ) -> bool:
        return True


class AlwaysOffSampler:
    """OTel ``ALWAYS_OFF`` — 모든 trace drop.

    부모 sampled bit 무시 (record-nothing policy — 운영자가 backend ingestion
    비용 0 으로 떨어뜨리고 싶을 때).
    """

    __slots__ = ()

    def should_sample(
        self, trace_id: str, parent_sampled: Optional[bool],
    ) -> bool:
        return False


class TraceIdRatioBased:
    """OTel ``TraceIdRatioBased`` — probabilistic sampler.

    Spec: https://opentelemetry.io/docs/specs/otel/trace/sdk/#traceidratiobased

    설계 (OTel Python SDK byte-identity 정합 + W3C Trace Context § 3.2.2.3):

    - ``ratio`` (0.0 ≤ ratio ≤ 1.0) → ``threshold = round(ratio * (_TRACE_ID_LIMIT + 1))``
      정수 변환 (OTel Python SDK 의 ``round(rate * (TRACE_ID_LIMIT + 1))`` 동치).
    - ``should_sample(trace_id, _)`` → ``(int(trace_id, 16) & _TRACE_ID_LIMIT) < threshold``
      정수 비교. 하위 64-bit AND mask — OTel Python SDK 의 ``trace_id &
      TRACE_ID_LIMIT < bound`` byte-identity 동치.
    - W3C spec § 3.2.2.3: trace-id 는 32 hex (128-bit pseudo-random). 모든
      16 bytes uniform random — sampling 비트 선택은 spec 미명시. OTel
      ecosystem 정합 우선 → 하위 64-bit AND mask 채택 (OTel Python SDK 공식
      구현 byte-identity, FCC ↔ OTel collector downstream 결정 일관성 보장).
    - boundary 정확:
        - ``ratio=0.0`` → threshold=0 → 모든 64-bit 값 < 0 False → **100% drop**
        - ``ratio=1.0`` → threshold=2^64 (= _TRACE_ID_LIMIT+1) → 64-bit 최대값
          (= _TRACE_ID_LIMIT) < 2^64 True → **100% sample**
    - parent_sampled 인자는 **무시** — TraceIdRatioBased 는 *root* sampler.
      parent decision 보존은 ``ParentBasedSampler(root=TraceIdRatioBased(ratio))``
      합성으로 표현 (OTel 표준 패턴).

    Args:
        ratio: sampling probability. 0.0 ≤ ratio ≤ 1.0 범위 외 / NaN 시
            ``ValueError`` 즉시 noisy fail (silent corruption 차단).

    Raises:
        ValueError: ratio 가 [0.0, 1.0] 범위 외 또는 NaN.
    """

    __slots__ = ('_ratio', '_threshold')

    def __init__(self, ratio: float) -> None:
        # noisy fail — production boot 시 잘못된 env 즉시 발견.
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            raise ValueError(
                f'TraceIdRatioBased ratio MUST be a float in [0.0, 1.0]: {ratio!r}'
            )
        ratio = float(ratio)
        if math.isnan(ratio):
            raise ValueError(f'TraceIdRatioBased ratio MUST NOT be NaN: {ratio!r}')
        if not (0.0 <= ratio <= 1.0):
            raise ValueError(
                f'TraceIdRatioBased ratio MUST be in [0.0, 1.0]: {ratio!r}'
            )
        self._ratio = ratio
        # OTel Python SDK byte-identity: bound = round(rate * (TRACE_ID_LIMIT + 1))
        # = round(rate * 2^_TRACE_ID_BITS_USED). round() 사용으로 OTel Python
        # SDK 공식 구현 정확 일치 — 동일 ratio 입력 시 동일 threshold 산정.
        self._threshold = round(ratio * (_TRACE_ID_LIMIT + 1))

    @property
    def ratio(self) -> float:
        return self._ratio

    @property
    def threshold(self) -> int:
        return self._threshold

    def should_sample(
        self, trace_id: str, parent_sampled: Optional[bool],
    ) -> bool:
        # parent_sampled 무시 — root sampler.
        # OTel Python SDK byte-identity: trace_id & TRACE_ID_LIMIT < bound.
        # 하위 64-bit AND mask (W3C spec uniform random 가정 → 통계적 동치 +
        # OTel collector ecosystem byte-identity 보장).
        return (int(trace_id, 16) & _TRACE_ID_LIMIT) < self._threshold


class ParentBasedSampler:
    """OTel ``ParentBased`` — parent decision 보존, root 는 위임.

    OTel SDK Spec § 6.4 의 ``ParentBased`` 단순화. OTel 의 4-way 분기는 모두
    default (remote_parent_sampled=AlwaysOn / remote_parent_not_sampled=AlwaysOff
    / local_parent_sampled=AlwaysOn / local_parent_not_sampled=AlwaysOff) 와
    동치 — FCC 는 remote/local 구분 없음.

    Args:
        root: parent 가 없을 때 (root 시점) 결정할 sampler. OTel SDK default 는
            ``AlwaysOnSampler``.
    """

    __slots__ = ('_root',)

    def __init__(self, root: Sampler) -> None:
        self._root = root

    @property
    def root(self) -> Sampler:
        """root sampler getter (테스트 / introspection)."""
        return self._root

    def should_sample(
        self, trace_id: str, parent_sampled: Optional[bool],
    ) -> bool:
        if parent_sampled is None:
            # root 시점 — root sampler 위임.
            return self._root.should_sample(trace_id, None)
        # parent decision 보존 (W3C spec § 3.2 권장: child span 은 parent flags
        # 를 그대로 propagate 해야 trace 정합성 유지).
        return parent_sampled


# OTel SDK spec default — ParentBased(root=AlwaysOn).
# 기존 P0-3 의 ``sampled=True`` 행동 정확히 보존: root 시 AlwaysOn → True,
# parent 있으면 parent decision 보존 (그동안 inbound middleware 가 sampled bit
# 를 ContextVar 에 bind 하지 않아서 default True 와 같은 결과를 냈음).
DEFAULT_SAMPLER: Sampler = ParentBasedSampler(root=AlwaysOnSampler())


TRACEPARENT_SAMPLER_CTX: contextvars.ContextVar[Optional[Sampler]] = (
    contextvars.ContextVar('fcc_traceparent_sampler', default=None)
)


def current_sampler() -> Sampler:
    """현재 logical task 의 sampler — ContextVar override 또는 DEFAULT_SAMPLER.

    outbound_http.build_outbound_traceparent_headers 가 매 호출 시 1회 조회.
    스레드 / asyncio task 별로 자동 격리 (ContextVar 시맨틱).
    """
    override = TRACEPARENT_SAMPLER_CTX.get()
    if override is not None:
        return override
    return DEFAULT_SAMPLER


@contextlib.contextmanager
def bind_sampler(sampler: Sampler) -> Iterator[Sampler]:
    """``with bind_sampler(custom_sampler):`` — try/finally 로 reset.

    테스트 결정성 + 런타임 policy switching (예: 운영자가 특정 endpoint 만
    AlwaysOff 로 측정 비용 절감) 진입점.
    """
    token = TRACEPARENT_SAMPLER_CTX.set(sampler)
    try:
        yield sampler
    finally:
        TRACEPARENT_SAMPLER_CTX.reset(token)


# ════════════════════════════════════════════════════════════════════════════
# P1-C (2026-05-25) — OTel SDK 표준 env spec factory + composition root
# ════════════════════════════════════════════════════════════════════════════
#
# spec: https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/#general-sdk-configuration
#
# OTEL_TRACES_SAMPLER 의 6 표준 값:
#   - always_on / always_off / traceidratio
#   - parentbased_always_on (default) / parentbased_always_off / parentbased_traceidratio
# OTEL_TRACES_SAMPLER_ARG: traceidratio / parentbased_traceidratio 시 float ratio (필수).
#
# 다른 SDK 값 (jaeger_remote, xray 등) 은 본 sprint scope 외 — 별 SDK 확장.


_DEFAULT_SAMPLER_TOKEN: str = 'parentbased_always_on'

# 6 표준 token 명시 set — silent fallback 차단을 위해 명시 매핑.
_VALID_SAMPLER_TOKENS: frozenset = frozenset({
    'always_on',
    'always_off',
    'traceidratio',
    'parentbased_always_on',
    'parentbased_always_off',
    'parentbased_traceidratio',
})

_TOKENS_REQUIRING_RATIO_ARG: frozenset = frozenset({
    'traceidratio',
    'parentbased_traceidratio',
})


def sampler_from_env(environ: Mapping[str, str]) -> Sampler:
    """OTel SDK 표준 env spec → Sampler 인스턴스 SSOT.

    Args:
        environ: Mapping ``os.environ`` 호환. 테스트 결정성을 위해 명시 인자
            — 본 함수는 ``os.environ`` 직접 접근 0 (caller 가 결정).

    Returns:
        Sampler 인스턴스. 미설정 시 default ``ParentBasedSampler(root=AlwaysOn)``
        (== ``DEFAULT_SAMPLER`` 동치 구성). silent 무시 / fallback 차단.

    Raises:
        ValueError: 알려지지 않은 token, 또는 ratio 가 필요한 token 에서
            ``OTEL_TRACES_SAMPLER_ARG`` 미설정 / non-numeric.
    """
    token = (environ.get(OTEL_TRACES_SAMPLER) or _DEFAULT_SAMPLER_TOKEN).strip().lower()
    if token not in _VALID_SAMPLER_TOKENS:
        raise ValueError(
            f'{OTEL_TRACES_SAMPLER}={token!r} is not a valid OTel SDK sampler '
            f'token. Expected one of: {sorted(_VALID_SAMPLER_TOKENS)}'
        )

    # ratio token 처리
    if token in _TOKENS_REQUIRING_RATIO_ARG:
        raw_arg = environ.get(OTEL_TRACES_SAMPLER_ARG)
        if raw_arg is None or not raw_arg.strip():
            raise ValueError(
                f'{OTEL_TRACES_SAMPLER}={token!r} requires '
                f'{OTEL_TRACES_SAMPLER_ARG} (float ratio in [0.0, 1.0])'
            )
        try:
            ratio = float(raw_arg.strip())
        except ValueError as exc:
            raise ValueError(
                f'{OTEL_TRACES_SAMPLER_ARG}={raw_arg!r} is not a valid float: {exc}'
            ) from exc
        ratio_sampler = TraceIdRatioBased(ratio)  # ratio boundary check 위임
        if token == 'traceidratio':
            return ratio_sampler
        # parentbased_traceidratio
        return ParentBasedSampler(root=ratio_sampler)

    # ratio 미사용 token 분기
    if token == 'always_on':
        return AlwaysOnSampler()
    if token == 'always_off':
        return AlwaysOffSampler()
    if token == 'parentbased_always_on':
        return ParentBasedSampler(root=AlwaysOnSampler())
    if token == 'parentbased_always_off':
        return ParentBasedSampler(root=AlwaysOffSampler())
    # _VALID_SAMPLER_TOKENS 가드로 도달 불가 — defensive.
    raise ValueError(f'unhandled sampler token: {token!r}')  # pragma: no cover


def install_sampler_from_env(
    environ: Optional[Mapping[str, str]] = None,
) -> Sampler:
    """app boot 진입점 — env 기반 sampler 를 process-wide ContextVar 에 설치.

    composition root 가 1회 호출. middleware / use case 가 ``current_sampler()``
    조회 시 본 함수가 설치한 sampler 가 노출됨.

    Args:
        environ: ``None`` 시 ``os.environ`` 위임. 테스트는 명시 dict 주입 권장.

    Returns:
        설치된 Sampler — caller 가 분기 결정 시 사용 가능 (예: AlwaysOff 설치
        시 metrics emit skip).

    Note:
        ``TRACEPARENT_SAMPLER_CTX.set(...)`` 직접 호출 — token reset 없음
        (process-wide 영구 설치 의도). 테스트는 ``bind_sampler`` context
        manager 를 통해 일시 override 권장.
    """
    if environ is None:
        environ = os.environ
    sampler = sampler_from_env(environ)
    TRACEPARENT_SAMPLER_CTX.set(sampler)
    return sampler
