"""Deep #1 (2026-05-24) — contextvars correlation 표준 패턴 invariant.

Locks in:
- REQUEST_ID_CTX / CONNECTION_ID_CTX module-level ContextVar
- bind_request_id / bind_connection_id context manager 가 try/finally reset
- current_request_id / current_connection_id 가 ContextVar 값 노출
- CorrelatedLoggerAdapter 가 모든 record 의 extra 에 correlation dict 부착
- session_router middleware/WS handler 가 bind_*_id 사용 (AST 봉인)
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))


def test_context_vars_default_empty_string():
    from fcc_test_contracts.common.correlation import (
        current_connection_id,
        current_request_id,
    )
    assert current_request_id() == ''
    assert current_connection_id() == ''


def test_bind_request_id_sets_and_resets():
    from fcc_test_contracts.common.correlation import (
        bind_request_id,
        current_request_id,
    )
    assert current_request_id() == ''
    with bind_request_id('rid-abc'):
        assert current_request_id() == 'rid-abc'
    assert current_request_id() == '', 'Deep #1: context manager exit reset 실패'


def test_bind_connection_id_sets_and_resets():
    from fcc_test_contracts.common.correlation import (
        bind_connection_id,
        current_connection_id,
    )
    with bind_connection_id('cid-xyz'):
        assert current_connection_id() == 'cid-xyz'
    assert current_connection_id() == ''


def test_nested_bindings_restore_previous_value():
    from fcc_test_contracts.common.correlation import (
        bind_request_id,
        current_request_id,
    )
    with bind_request_id('outer'):
        with bind_request_id('inner'):
            assert current_request_id() == 'inner'
        assert current_request_id() == 'outer'
    assert current_request_id() == ''


def test_request_id_isolated_per_thread():
    """ContextVar 표준 의미 — thread 간 자동 격리."""
    from fcc_test_contracts.common.correlation import (
        bind_request_id,
        current_request_id,
    )
    captured = {}

    def _worker():
        with bind_request_id('thread-A'):
            captured['inside'] = current_request_id()
        captured['after'] = current_request_id()

    with bind_request_id('main-thread'):
        t = threading.Thread(target=_worker)
        t.start()
        t.join()
        captured['main'] = current_request_id()

    assert captured['inside'] == 'thread-A'
    assert captured['after'] == ''
    # Main thread's ContextVar 는 worker 영향 0.
    assert captured['main'] == 'main-thread'


def test_correlated_logger_attaches_correlation_extra():
    from fcc_test_contracts.common.correlation import (
        bind_connection_id,
        bind_request_id,
        get_correlated_logger,
    )
    logger = get_correlated_logger('deep1_test_logger')

    records: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _CaptureHandler(level=logging.DEBUG)
    logger.logger.addHandler(handler)
    logger.logger.setLevel(logging.DEBUG)
    try:
        with bind_request_id('rid-1'), bind_connection_id('cid-2'):
            logger.info('hello')
    finally:
        logger.logger.removeHandler(handler)

    assert len(records) == 1
    rec = records[0]
    assert getattr(rec, 'request_id', None) == 'rid-1', (
        'Deep #1: log record extra 에 request_id 자동 부착되지 않음.'
    )
    assert getattr(rec, 'connection_id', None) == 'cid-2', (
        'Deep #1: log record extra 에 connection_id 자동 부착되지 않음.'
    )


def test_session_router_middleware_binds_request_id_via_contextvar():
    """AST 봉인 — session_router 의 middleware 가 bind_request_id 사용.

    P1-1 (2026-05-25): import 형식이 multi-line W3C TraceContext 통합으로
    변경 — substring 매칭 (``bind_request_id``) 으로 일반화. middleware 가
    ``with bind_request_id(...)`` + ``bind_trace_context(...)`` 사용함을 봉인.
    """
    src = (project_root / 'src' / 'infrastructure' / 'adapters' / 'driving'
           / 'api' / 'session_router.py').read_text(encoding='utf-8')
    assert 'bind_request_id' in src, (
        'Deep #1: session_router HTTP middleware 가 bind_request_id 미사용.'
    )
    assert 'with bind_request_id(request_id):' in src, (
        'Deep #1: HTTP middleware 가 bind_request_id context manager 사용 안 함.'
    )
    assert 'bind_connection_id' in src, (
        'Deep #1: WS handler 가 bind_connection_id 미사용.'
    )
    assert 'bind_connection_id(connection_id)' in src, (
        'Deep #1: WS handler 가 bind_connection_id 사용 안 함.'
    )
    # P1-1 (2026-05-25) — W3C TraceContext 통합 봉인.
    assert 'bind_trace_context' in src, (
        'P1-1: HTTP middleware 가 bind_trace_context 미사용 (W3C TraceContext).'
    )


def test_current_correlation_dict_combines_both():
    """P1-1 (2026-05-25) extension — W3C trace_id/span_id 키 추가 ratchet.
    P1-B (2026-05-25) extension — ``parent_sampled`` 키 추가 ratchet.
    P1-D (2026-05-22) — ``parent_sampled`` Optional[bool] 시멘틱 마이그레이션.

    기존 ``request_id`` / ``connection_id`` 키 보존 + W3C ``trace_id`` /
    ``span_id`` 키 + sampler decision ``parent_sampled`` 키 + P1-A (2026-05-22)
    W3C spec § 3.3 ``tracestate`` 키. 외부 bind 없으면 trace/span 두 키는 빈
    문자열, parent_sampled 는 default ``None`` (W3C spec § 3.2 "root context =
    no parent flags"), tracestate 는 빈 문자열.
    """
    from fcc_test_contracts.common.correlation import (
        bind_connection_id,
        bind_request_id,
        current_correlation_dict,
    )
    with bind_request_id('r1'), bind_connection_id('c1'):
        d = current_correlation_dict()
    assert d == {
        'request_id': 'r1',
        'connection_id': 'c1',
        'trace_id': '',
        'span_id': '',
        'parent_sampled': None,
        'tracestate': '',
    }
