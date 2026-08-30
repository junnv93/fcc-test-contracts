"""Operator subject SSOT (FE-P0b, 2026-05-25).

측정 수행자(operator)는 ``measurement_attempts.recorded_by`` (append-only fact)
에 기록되어 프로젝트 단위 중복 방지의 식별자로 쓰인다. operator 식별 출처는
**정확히 두 곳**뿐이다 (매직 리터럴 직접 사용 영구 금지):

- 원격 API 경로 = ``application.common.access_policy.ApiPrincipal.subject``
- local GUI/headless 합성 경로 = 본 모듈의 ``LOCAL_GUI_OPERATOR_SUBJECT``

합성 root 가 어디서 import 하든 동일 식별자를 보장하기 위해 단일 module-level
상수로 SSOT 화한다. ``'local-user'`` / ``'gui-user'`` 같은 임시 리터럴을 코드에
직접 박지 않는다 — AST 가드(``tests/test_operator_provenance.py``)가 src/ 전
트리에서 이 값의 중복 리터럴 + 금지 리터럴 0건을 봉인한다.

dependency-free (stdlib only) — ``application/common`` 순수성 규약
(``TestApplicationCommonPurity``) 준수. FastAPI/PySide6/infrastructure/pandas
import 0.
"""
from __future__ import annotations

__all__ = ['LOCAL_GUI_OPERATOR_SUBJECT']


# local 측정 스테이션(GUI/headless)에서 수행된 측정의 기본 operator subject.
# 단일 워크스테이션 = 단일 operator 식별자. 향후 station 인증(FE-P8)이
# 도입되면 이 상수는 인증된 operator subject 로 대체되는 합성 주입점이 된다.
LOCAL_GUI_OPERATOR_SUBJECT = 'local-gui-operator'
