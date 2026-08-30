"""한 챔버 PC 에서 계측기를 만지는 프로세스는 하나다 (PC 단위 모드 배타 ③).

운영자 판정 2026-08-16: 챔버 PC 는 웹 세션을 받는 PC 이거나 받지 않는 PC 이며 한 PC 가
둘 다일 수 없다. 배타의 **1차 수단은 설치**(웹 PC 에 로컬 프로그램을 깔지 않는다 — 코드 0,
가장 강력)이고, 이 모듈은 **실수 보험**이다: 둘 다 깔린 PC 에서 실수로 둘 다 뜨는 것이
**조용한 오측정**이 아니라 **뜨는 쪽의 거부**가 되게 한다.

**왜 필요한가 — 계측기는 공유 자원이다.** 두 프로세스가 같은 분석기를 열면 SCPI 가 섞인다.
그리고 실해는 측정 실패가 아니라 **조용히 틀린 값**이다: 한쪽의 ``SYST:PRES``(연결 시
무조건 나간다)가 다른 쪽이 방금 세운 설정을 지우고, 그 측정은 정상 완료되며 verdict 도
나온다. VISA ``ResourceManager`` 공유 규칙(P0)은 *한 프로세스 안*의 이야기라 이 경우를
보호하지 못하고, ``SessionUseCaseSupervisor`` 의 측정 슬롯도 **프로세스 내부**다.

⚠️ **이 모듈이 provider 중립 자리에 있는 것이 요점이다.** FCC 의 GUI · KC 의 MPTool ·
mmWave 의 자기 프로그램은 서로 다른 물건이고, 배타는 그 셋 **모두**에 걸려야 한다. 로컬
프로그램 쪽 진입점에만 넣으면 FCC 전용이 되어 나머지 둘에 적용되지 않고, **그것이 이 정책이
막으려던 바로 그것이다**. 그래서 판정·획득은 여기 한 곳이고, 각 provider 의 진입점은
그것을 **부르기만** 한다.

**키는 PC 전역이다** (운영자 확정: 챔버 PC 는 데스크탑이고 PC ↔ 챔버 1:1).

⚠️ 기각 사유는 단순함이 아니라 **실패 형태**다. 챔버 id 나 계측기 주소로 키잉하면 양쪽이
서로 다른 값을 볼 수 있고(로컬 프로그램에서 챔버 id 는 선택 설정이라 비어 있을 수 있다),
그러면 **락 파일이 둘 생겨 아무도 아무것도 막지 않는데 양쪽 다 락을 잡았다고 믿는다** —
이 저장소가 반복해서 이름 붙인 *"보호처럼 읽히는 죽은 코드"*. 과잉 배타는 **시끄럽게
거부**하고 잘못된 키는 **조용히 통과**시킨다. 훗날 한 PC 가 두 챔버를 몰면 그때 키를
**좁히면** 되고, 그 방향이 안전하다.

**fail-open 하지 않는다.** 이 저장소의 위생 훅들은 fail-open 이 옳지만(오탐이 결함보다
비싸다) 이 락은 반대다 — 통과시키면 조용히 틀린 측정이 나온다. 그래서 거부는 **둘**이고
서로 다른 말을 한다:

- :class:`InstrumentAccessHeldElsewhere` — 다른 프로세스가 쥐고 있다. 운영자가 할 일은
  *그쪽을 닫는 것*이다.
- :class:`InstrumentExclusionUnavailable` — 락 자체를 세울 수 없다(권한·경로·I/O).
  운영자가 할 일은 *환경을 고치는 것*이고, 그것을 "이미 실행 중"으로 접으면 있지도 않은
  프로세스를 찾아 헤맨다. 옛 ``_ProcessLock`` 이 정확히 그렇게 접고 있었다.

**프로세스 안에서는 멱등이다.** 한 프로세스가 두 번 물으면 같은 보유를 돌려준다 — 이것은
*프로세스 간* 배타이지 재진입 방지가 아니고, 진입점과 합성 루트가 둘 다 물을 수 있어야 한다.

⚠️ **알려진 한계 — 락 자리는 아직 사용자별일 수 있다.** ``tempfile.gettempdir()`` 는 배포
환경에 따라 사용자별로 해소될 수 있고(Windows 에서 흔하다), 그러면 **계정이 다른 두
프로세스는 서로 다른 파일을 잡아 배타가 성립하지 않는다**. 오늘은 노드와 로컬 프로그램이
**같은 시험원 계정**에서 돌므로 드러나지 않는다(운영자 확정 2026-08-16). 머신 전역 자리
(Windows named kernel mutex 또는 ``C:\\ProgramData``)로 옮기는 것은 ACL·설치 스크립트가
딸리고 실환경 검증이 필요해 **서비스 이관의 차단 선행 조건**으로 장부에 있다. 값싼 보험으로
:func:`describe_exclusion_scope` 가 **해소된 경로를 이름으로** 답하고 양쪽 진입점이 그것을
로그에 남긴다 — 두 로그를 비교하면 갈라진 것이 보인다. 이 문단이 사라지면 다음 세션이
계정 교차 배타를 성립한다고 믿는다.

⚠️ **무엇이 참여하고 무엇이 일부러 참여하지 않는가** (codex 교차 검증 2026-08-16 이
지적한 우회 둘에 대한 답):

* **참여** — 챔버 PC 에 **배포되는 두 진입점**: ``main_entry``(provider 로컬 프로그램)와
  ``session_node_entry``(웹 노드). 이 둘이 계측기에 닿는 유일한 배포 경로다.
* **불참 (dev stack)** — ``apps/web/scripts/dev-stack-local.sh`` 등이 ``session_api_app:
  create_app`` 을 uvicorn 으로 **직접** 띄운다. 그 경로는 개발자 머신 도구이고 챔버에
  배포되지 않는다(배포물은 패키징된 exe). 거기서 락을 잡게 하면 개발자 머신의 로컬
  서비스들이 서로를 막고, **얻는 것은 없다**(개발 머신에 계측기가 없다). 그래서 이것은
  결함이 아니라 **범위**이고, 범위는 적혀 있어야 범위다.
* **불참 (진단 도구)** — ``scripts/diagnose_visa_latency.py`` 는 **앱이 도는 중에 붙으라고
  만든 읽기 전용 프로브**다(자기 docstring: *"본 앱이 느려진 상태일 때, 앱 끄지 말고"* ·
  *"상태 변경 명령 0건 — ``*IDN?`` 만"*). 락을 걸면 그 도구는 **자기 목적을 잃는다**.
  ⚠️ 이 예외가 성립하는 근거는 *편의*가 아니라 **그 스크립트가 설정을 바꾸지 않는다**는
  것이다 — 상태를 바꾸는 도구가 생기면 그것은 참여해야 한다.

Dependency-free — stdlib only (``fcc-test-contracts`` 레인 계약).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from fcc_test_contracts.common.process_file_lock import (
    HELD_ELSEWHERE_ERRNOS as _HELD_ELSEWHERE_ERRNOS,
    is_conflict as _is_conflict,
    lock_handle_exclusive_nonblocking as _lock_handle,
    unlock_handle as _unlock_handle,
)


__all__ = [
    'EXCLUSION_LOCK_BASENAME',
    'InstrumentAccessHeldElsewhere',
    'InstrumentExclusionError',
    'InstrumentExclusionUnavailable',
    'acquire_instrument_exclusion',
    'describe_exclusion_scope',
    'release_instrument_exclusion',
    'resolve_exclusion_lock_path',
]


class InstrumentExclusionError(RuntimeError):
    """이 PC 의 계측기 배타를 확보하지 못했다 (두 사유의 공통 조상)."""


class InstrumentAccessHeldElsewhere(InstrumentExclusionError):
    """다른 프로세스가 이 PC 의 계측기를 이미 쥐고 있다.

    운영자가 할 일: **그쪽을 닫는다**. 웹 세션을 받는 PC 에 로컬 프로그램이 떠 있거나
    그 반대라면, 그것이 이 배타가 잡으려는 실수다.
    """


class InstrumentExclusionUnavailable(InstrumentExclusionError):
    """락 자체를 세울 수 없다 — 권한·경로·I/O.

    ⚠️ 이것을 "이미 실행 중"으로 접으면 안 된다. 운영자가 할 일이 완전히 다르고
    (환경을 고친다 vs 다른 프로세스를 닫는다), 접으면 있지도 않은 프로세스를 찾아
    헤맨다. 옛 ``_ProcessLock`` 은 ``except (BlockingIOError, OSError)`` 하나로 둘을
    같은 메시지로 접고 있었다.

    ⚠️ 그래도 **통과시키지는 않는다**. 배타를 확인할 수 없는 것과 배타가 성립하는 것은
    다르고, 여기서 통과시키면 조용히 틀린 측정이 나온다.
    """


#: PC 전역 락 파일 이름. **포트도 챔버 id 도 들어가지 않는다** — 그것이 PC 전역의 내용이다.
#:
#: ⚠️ 옛 노드 락은 ``fcc-session-node-{port}.lock`` 이었다. 포트가 다르면 두 노드가 서로를
#: 못 보고, 포트가 없는 로컬 프로그램은 애초에 참여할 수 없었다. PC 전역 이름은 그 둘을
#: 동시에 닫는다(그리고 옛 포트-키 배타를 **포함**한다 — 같은 PC 의 두 노드도 걸린다).
EXCLUSION_LOCK_BASENAME = 'fcc-instrument-access.lock'


def resolve_exclusion_lock_path() -> Path:
    """이 프로세스가 쓸 락 파일 경로.

    ``tempfile.gettempdir()`` 는 ``TMPDIR``/``TMP``/``TEMP`` 와 시스템 폴백을 거치므로
    **배포 환경에 따라 달라진다**. 그 불확실성이 곧 위 §알려진 한계이고, 그래서 이 값은
    숨기지 않고 :func:`describe_exclusion_scope` 로 **밖에 내보낸다**.
    """
    return Path(tempfile.gettempdir()) / EXCLUSION_LOCK_BASENAME


def describe_exclusion_scope() -> str:
    """양쪽 진입점이 로그에 남길 한 줄 — *어느 자리에서* 배타가 성립하는가.

    두 프로세스의 로그를 비교하면 자리가 갈라진 것이 **보인다**. 계정 교차 배타를
    실환경에서 시험할 수 없는 동안(위 §알려진 한계) 이것이 값싼 대체 증거다.
    """
    return f'instrument exclusion scope: {resolve_exclusion_lock_path()}'


class _Holder:
    """열린 핸들 하나. 잠금은 OS 가 하고, 해제는 핸들이 닫힐 때 일어난다.

    ``claims`` 는 이 프로세스 안에서 **몇 번 요청됐는가**다. 멱등 획득이 참조 계수를
    올리고 해제가 내리며, **0 에서만 실제로 푼다**.

    ⚠️ 계수가 없으면 두 번째 해제가 첫 번째 보유까지 풀어 버린다 — 진입점과 어댑터가
    둘 다 물을 수 있다는 계약(멱등)이 곧 그 결함의 입구다. codex 교차 검증(2026-08-16)이
    노드 어댑터에서 정확히 그 경로를 짚었다.
    """

    __slots__ = ('handle', 'path', 'claims')

    def __init__(self, handle, path: Path) -> None:
        self.handle = handle
        self.path = path
        self.claims = 1


#: 프로세스 안의 단일 보유. 진입점과 합성 루트가 **둘 다** 물을 수 있어야 하므로 멱등이다
#: (이것은 프로세스 *간* 배타이지 재진입 방지가 아니다).
_HELD: Optional[_Holder] = None


#: "다른 프로세스가 쥐고 있다" 를 뜻하는 errno — 그리고 플랫폼별 잠금·해제.
#:
#: **2026-08-26 — 정의는 :mod:`application.common.process_file_lock` 로 옮겼다.**
#: 두 번째 소비자(:mod:`infrastructure.logging.session_log_custody`)가 생겼고, 사본이
#: 둘이 되는 순간이 접는 순간이다. 여기 남는 것은 그 원시연산의 **이름**뿐이고 이 모듈이
#: 소유하는 것은 여전히 *정책* 이다 — 이 축은 fail-closed 로 거부하고, 형제 로그 보관 축은
#: 같은 원시연산 위에서 fail-safe 로 보존한다. 방향이 정반대라 정책은 접히지 않는다.
#:
#: ⚠️ **예외 클래스로 가르면 안 된다**는 사유와 실 Windows 11 실측 근거는 그 모듈의
#: docstring 이 소유한다. 대조는 ``tests/test_instrument_exclusion_axis.py`` 가 **모든
#: 플랫폼에서** 수행하므로, 누가 그 집합을 좁히면 실측이 red 로 알려준다.


def acquire_instrument_exclusion() -> str:
    """이 PC 의 계측기 접근을 이 프로세스가 갖는다. 이미 가졌으면 그대로 답한다.

    Returns:
        :func:`describe_exclusion_scope` 문자열 — 호출자가 로그에 남긴다.

    Raises:
        InstrumentAccessHeldElsewhere: 다른 프로세스가 쥐고 있다.
        InstrumentExclusionUnavailable: 락 자체를 세울 수 없다.

    ⚠️ **두 예외를 하나로 접지 마라.** 운영자가 할 일이 다르다.
    """
    global _HELD
    if _HELD is not None:
        _HELD.claims += 1
        return describe_exclusion_scope()

    path = resolve_exclusion_lock_path()
    try:
        handle = path.open('a+')
    except OSError as exc:
        # ⚠️ 파일을 **열지 못한 것**은 보유자가 있다는 뜻이 아니다. 옛 형상은 이 자리가
        # try 밖에 있어 평범한 OSError 로 샜고, 안으로 넣으면서 "이미 실행 중"으로
        # 접는 것이 더 나쁜 수리다 — 이름을 나눈다.
        raise InstrumentExclusionUnavailable(
            f'cannot open the instrument exclusion lock at {path}: {exc}. '
            'This is an environment problem (permissions, path, I/O) — no other '
            'process is claimed to hold it.'
        ) from exc

    try:
        _lock_handle(handle)
    except OSError as exc:
        handle.close()
        if _is_conflict(exc):
            raise InstrumentAccessHeldElsewhere(
                'another process on this PC already owns instrument access '
                f'(lock: {path}). A chamber PC either takes web sessions or runs the '
                "provider's local program — not both. Close the other one first."
            ) from exc
        raise InstrumentExclusionUnavailable(
            f'cannot lock the instrument exclusion file at {path}: {exc}. '
            'This is an environment problem — no other process is claimed to hold it.'
        ) from exc

    _HELD = _Holder(handle, path)
    return describe_exclusion_scope()


def _forget_inherited_holding() -> None:
    """fork 로 태어난 자식은 부모의 보유를 **물려받지 않는다**.

    ⚠️ 모듈 전역 ``_HELD`` 는 fork 로 그대로 복제된다. 그대로 두면 자식이 *자기가 쥐고
    있다*고 믿고 :func:`acquire_instrument_exclusion` 이 조기 반환하는데, 실제로는 부모의
    핸들을 공유할 뿐이라 **배타를 한 번도 확인하지 않은 프로세스가 계측기를 만진다**.
    자식은 잊게 하고, 정말 필요하면 다시 물어 **정직하게 거부당하게** 한다
    (codex 교차 검증 2026-08-16).

    핸들 자체는 닫지 않는다 — 부모와 공유된 열린 파일 기술자라 자식이 닫으면 부모의
    잠금 수명에 손대는 셈이고, 그 방향이 더 위험하다.
    """
    global _HELD
    _HELD = None


if hasattr(os, 'register_at_fork'):  # pragma: no branch — POSIX only
    os.register_at_fork(after_in_child=_forget_inherited_holding)


def release_instrument_exclusion() -> None:
    """보유를 내려놓는다 (안 가졌으면 아무것도 하지 않는다).

    ⚠️ 파일은 **지우지 않는다**. OS 파일 락은 핸들이 닫힐 때 풀리므로 비정상 종료 뒤에도
    stale 락이 남지 않고, 남는 것은 빈 파일뿐이다. 지우려 들면 다른 프로세스가 방금
    만든 파일을 지우는 경합이 새로 생긴다.
    """
    global _HELD
    held = _HELD
    if held is None:
        return
    held.claims -= 1
    if held.claims > 0:
        # 아직 다른 요청자가 있다 — 푸는 것은 마지막 하나다.
        return
    _HELD = None
    try:
        _unlock_handle(held.handle)
    finally:
        held.handle.close()
