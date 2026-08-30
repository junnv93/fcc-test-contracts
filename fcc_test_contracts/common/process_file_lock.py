"""프로세스 사이의 배타를 파일 하나로 세우는 원시연산 — 이 저장소에 정의는 하나다.

이 모듈은 2026-08-26 에 :mod:`application.common.instrument_exclusion` 에서 **추출**됐다.
두 번째 소비자가 생겼기 때문이고(:mod:`infrastructure.logging.session_log_custody` —
로그 보존 정리가 살아 있는 세션을 회수하지 못하게 한다), 이 저장소가 반복해서 이름 붙인
규율이 *사본이 둘이 되는 순간이 접는 순간*이기 때문이다.

**무엇이 여기 있고 무엇이 여기 없는가.** 여기 있는 것은 *플랫폼이 잠금을 어떻게 거는가*와
*실패가 보유자 존재인가 환경 문제인가* 둘뿐이다. **누가 무엇을 왜 잠그는가는 소비자의
일**이다 — 계측기 배타는 fail-closed 로 거부하고(통과시키면 조용히 틀린 측정이 나온다)
로그 보관은 fail-safe 로 보존한다(관측 실패로 남의 로그를 지우면 안 된다). 두 방향이
정반대이므로 정책을 여기 넣으면 한쪽이 반드시 틀린 답을 물려받는다.

**errno 로 가르고 예외 클래스로 가르지 않는다.** POSIX ``flock`` 은 충돌을
``BlockingIOError`` 로 내지만 Windows ``msvcrt.locking`` 에 대해 Python 문서가 보장하는
것은 **평범한 ``OSError``** 뿐이다(<https://docs.python.org/3/library/msvcrt.html#msvcrt.locking>).
클래스로 가르면 Windows 충돌이 "환경 문제"로 분류돼 운영자가 있지도 않은 권한 문제를
고치러 간다.

**그리고 그 값은 추론이 아니라 실측이다 (2026-08-16).** 실 Windows 11 (10.0.26200) 에서
두 프로세스를 띄워 프로덕션 경로를 그대로 태우면 ``msvcrt.locking`` 충돌은
``PermissionError`` / ``errno 13 (EACCES)`` / ``winerror`` 없음 이고
``isinstance(exc, BlockingIOError)`` 는 **False** 다 — 즉 클래스로 갈랐다면 실제로
오분류했을 것이다. CPython 3.12.6 · 3.13.0 두 인터프리터에서 같은 값이었다. 증거는
``docs/platform/evidence/2026-08-16-windows-instrument-exclusion-live-proof.json`` 이고
``scripts/windows_instrument_exclusion_live_proof.py`` 로 재생성한다(손으로 쓰지 않는다).
대조는 ``tests/test_instrument_exclusion_axis.py`` 가 **모든 플랫폼에서** 수행하므로,
누가 이 집합을 좁히면 실측이 red 로 알려준다.

⚠️ **락 파일은 지우지 않는다.** OS 파일 락은 핸들이 닫힐 때 풀리므로 비정상 종료 뒤에도
stale 락이 남지 않고, 남는 것은 빈 파일뿐이다. 지우려 들면 다른 프로세스가 방금 만든
파일을 지우는 경합이 새로 생긴다.

Dependency-free — stdlib only (``fcc-test-contracts`` 레인 계약).
"""
from __future__ import annotations

import errno
import os


__all__ = [
    'HELD_ELSEWHERE_ERRNOS',
    'is_conflict',
    'lock_handle_exclusive_nonblocking',
    'unlock_handle',
]


#: "다른 프로세스가 쥐고 있다" 를 뜻하는 errno.
#:
#: 두 플랫폼이 **같은 사실에 같은 값**을 쓰므로 이것으로 가른다. 자세한 사유와 실측 근거는
#: 모듈 docstring 참조.
HELD_ELSEWHERE_ERRNOS = frozenset(
    value for value in (
        getattr(errno, 'EACCES', None),
        getattr(errno, 'EAGAIN', None),
        getattr(errno, 'EWOULDBLOCK', None),
        getattr(errno, 'EDEADLK', None),
        getattr(errno, 'EDEADLOCK', None),
    )
    if value is not None
)


def is_conflict(exc: OSError) -> bool:
    """이 실패가 *보유자 존재* 인가, 아니면 환경 문제인가.

    ``BlockingIOError`` 는 POSIX 의 확실한 신호라 그대로 인정하고, 나머지는 **errno** 로
    가른다. errno 가 없으면(드라이버가 안 채운 경우) 보유자라고 **주장하지 않는다** —
    모르는 것을 "이미 실행 중"으로 답하는 것이 이 판정이 고치려던 결함이다.

    ⚠️ *모른다* 를 어느 쪽으로 접을지는 **소비자가 정한다**. 이 함수는 *충돌이라고 말할 수
    있는가* 에만 답하고, 계측기 배타(거부)와 로그 보관(보존)은 그 답을 반대로 쓴다.
    """
    if isinstance(exc, BlockingIOError):
        return True
    return exc.errno in HELD_ELSEWHERE_ERRNOS


def lock_handle_exclusive_nonblocking(handle) -> None:
    """플랫폼별 비차단 배타 잠금. 실패는 ``OSError`` 로 올라오고 분류는 :func:`is_conflict`.

    ⚠️ 이 저장소에서 ``fcntl.flock`` / ``msvcrt.locking`` 을 부르는 자리는 **여기 하나**다.
    """
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_handle(handle) -> None:
    """잠금을 푼다. 핸들은 닫지 않는다 — 수명은 호출자가 소유한다."""
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
