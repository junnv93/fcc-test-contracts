#!/usr/bin/env python3
"""Mutation-battery machinery, shared by every ``scripts/mutation_*.py`` runner.

A battery answers one question with execution: **what does this seal actually
catch?** Each mutation revives one defect; the seal must go red (KILLED). Green
means that seal cannot see that defect (SURVIVED), and *that* is the output.

⚠️ **This module exists because the machinery is not the interesting part, and
because it is the part that is expensive to get wrong.** Every rule below was
paid for once already, in `mutation_credential_throttle.py`:

* **A mutation that never applied and a mutation that survived print the same
  thing.** So every site asserts the original text occurs exactly the expected
  number of times, and that the write actually changed the file, before any
  verdict is reached. Anything else is reported as ``NOT-APPLIED`` — *"could not
  test"*, never *"the seal caught it"*.
* **A mutation that breaks the syntax was never tested either.** If the mutated
  module no longer parses, every test that imports it fails and the battery reads
  that red as *"the seal saw the defect"*. It did not — it saw a parse error.
  Python targets are parsed after the write and a failure is ``NOT-APPLIED``.
  (2026-08-27; measured: one mutation orphaned an ``except`` and took 33 tests
  down while being tallied ``KILLED``.)
* **Restoration is from an in-memory backup, not ``git checkout``**, which would
  delete uncommitted work in the tree.
* **``SIGTERM`` does not fire ``atexit``.** A long battery that is killed leaves
  mutations in the tree, so signals are handled explicitly.
* **An unmutated tree must be green first.** In a red tree every mutation looks
  KILLED and the battery proves nothing.
* **One defect can need two sites.** ``Mutation.also`` exists because a battery
  that cannot express a cross-file defect reports it as SURVIVED.

⚠️ **Do not copy this file.** A second copy drifts, and the drifting copy is the
one whose ``NOT-APPLIED`` check is missing. Import :func:`run_battery` instead —
that is what the two runners in this directory do.
"""
from __future__ import annotations

import argparse
import ast
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


__all__ = ['Mutation', 'run_battery']


@dataclass(frozen=True)
class Mutation:
    """되살릴 결함 하나.

    ⚠️ ``also`` 는 **한 결함이 두 곳을 동시에 되돌려야 재현되는 경우**를 위한 것이다.
    처음 판은 단일 사이트만 지원했고, 그래서 *"비밀번호 변경이 다시 계정 예산을
    소비한다"* 변이가 라우트 호출만 되살려 **아무것도 바꾸지 못한 채** SURVIVED 로
    보고됐다 — 식별자 출처(화이트리스트)가 함께 돌아오지 않으면 그 호출은 과금하지
    않기 때문이다. 무효 변이와 살아남은 변이는 출력이 같으므로, 표현할 수 없는 결함은
    표현할 수 있게 만들어야 한다.
    """

    axis: str
    defect: str
    path: str
    old: str
    new: str
    occurrences: int = 1
    also: tuple = ()

    @property
    def sites(self) -> tuple:
        return ((self.path, self.old, self.new, self.occurrences),) + tuple(
            (path, old, new, 1) for path, old, new in self.also
        )


#: 봉인 1회 실행에 허용하는 벽시계 상한(초).
#:
#: ⚠️ **매달린 변이는 SURVIVED 도 KILLED 도 아니다 — 배터리를 통째로 멈춘다.** 실측
#: 2026-08-22: 폐기 목록의 보관 장부 갱신을 지우는 변이가 축출 루프를 무한히 돌게 만들어
#: 배터리가 9번에서 영영 서 있었고, 그 모습은 *느린 배터리*와 구분되지 않았다. 상한이
#: 없으면 관측자가 그 둘을 가를 방법이 없다. 값은 넉넉해야 한다 — 빡빡하면 느린 머신에서
#: 정상 봉인이 매달림으로 오분류되고, 그러면 이 배터리는 신뢰를 잃는다.
SEAL_TIMEOUT_SECONDS = 300.0


def _python_syntax_problem(path: str, mutated: str) -> str | None:
    """변이가 파이썬 문법을 깼는가 — 깼다면 그 변이는 **시험되지 않았다**.

    ⚠️ 이 검사가 없으면 문법을 깨는 변이가 **KILLED 로 세어진다**. 모듈이 파싱되지
    않으면 그 모듈을 import 하는 테스트가 전부 실패하고, 배터리는 «봉인이 red 를 냈다»
    를 보므로 «봉인이 그 결함을 보았다» 로 읽는다. 실측(2026-08-27, 독립 평가 R3-5):
    ``try:`` 를 ``if True:`` 로 바꿔 뒤따르는 ``except`` 를 고아로 만든 변이가 33개
    테스트를 실패시켰고 표에는 KILLED 로 적혔다 — **그 결함은 한 번도 시험되지 않았다**.

    이것은 이 모듈 첫 규칙의 미완성 절반이다: *"적용 안 된 변이와 살아남은 변이는
    출력이 같다"*. 문법이 깨진 변이는 «적용되지 않은» 쪽이다 — 되살리려던 결함이 아니라
    **다른 결함**(파싱 불가)을 시험하기 때문이다.

    ⚠️ 파이썬이 아닌 대상은 판정하지 않는다. 변이는 ``.md``·``.ts``·``.json`` 도
    겨냥하고, 그것들에 대해 «문법»을 묻는 것은 이 모듈이 아는 질문이 아니다.
    """
    if not path.endswith('.py'):
        return None
    try:
        ast.parse(mutated, filename=path)
    except SyntaxError as error:
        return (
            f'{path}: 변이가 파이썬 문법을 깼다 ({error.msg} @ line {error.lineno}) — '
            '봉인이 red 를 내더라도 그것은 파싱 실패이지 그 결함을 본 것이 아니다'
        )
    return None


def _run(argv, cwd, timeout=SEAL_TIMEOUT_SECONDS):
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    try:
        return subprocess.run(  # noqa: S603
            argv, cwd=str(cwd), env=env, capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None


def run_battery(*, seal, mutations: tuple, repo_root: Path, doc: str) -> int:
    """Run ``mutations`` against ``seal``. Returns a process exit code.

    ``0`` only when every mutation was both applied and killed — ``NOT-APPLIED``
    is a failure, not a pass, because it means the battery did not get to ask.

    ``seal`` is one path, **or a sequence of them**. The sequence form was added
    2026-08-22 (``peer-axis-trusted-hop``) for a wave whose seals genuinely live
    in two files — a pure-policy module and the deployment-topology module — and
    whose mutations cross both. Without it that battery had two bad options: copy
    this file (the thing its own docstring forbids, because the copy is the one
    whose NOT-APPLIED check goes missing), or drop the mutations it could not
    express — and an unexpressible defect is reported as SURVIVED, which is the
    failure mode ``Mutation.also`` already exists to prevent. Passing a string
    stays byte-identical for the existing runners.
    """
    seal_paths = (seal,) if isinstance(seal, str) else tuple(str(item) for item in seal)
    if not seal_paths:
        raise ValueError('run_battery needs at least one seal path')
    parser = argparse.ArgumentParser(description=doc)
    parser.add_argument('--list', action='store_true', help='표만 출력하고 끝낸다')
    args = parser.parse_args()

    if args.list:
        for index, mutation in enumerate(mutations, 1):
            print(f'{index:2}. [{mutation.axis}] {mutation.defect}')
        return 0

    def _seal_verdict() -> str:
        """``'pass'`` · ``'fail'`` · ``'hang'``. 셋은 서로 다른 사실이다."""
        result = _run([
            sys.executable, '-m', 'pytest', *seal_paths, '-q', '-x',
            '--tb=no', '-p', 'no:randomly',
        ], repo_root)
        if result is None:
            return 'hang'
        return 'pass' if result.returncode == 0 else 'fail'

    def _seal_passes() -> bool:
        return _seal_verdict() == 'pass'

    # ⚠️ 미변이 트리가 먼저 green 이어야 한다. red 인 트리에서는 모든 변이가 "KILLED"
    # 로 보이고 배터리는 아무것도 증명하지 않는다.
    print('baseline: 미변이 트리에서 봉인을 확인한다 …', flush=True)
    if not _seal_passes():
        print('BASELINE RED — 변이를 적용하지 않는다. 봉인부터 고쳐라.')
        return 2
    print('baseline OK\n')

    backups: dict = {}
    interrupted = {'flag': False}

    def _restore_all() -> None:
        for path, text in backups.items():
            (repo_root / path).write_text(text, encoding='utf-8')
        backups.clear()

    def _on_signal(signum, _frame):
        interrupted['flag'] = True
        _restore_all()
        print(f'\nsignal {signum} — 트리를 복원하고 중단한다')
        raise SystemExit(130)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass

    survived = []
    not_applied = []
    hung = []
    try:
        for index, mutation in enumerate(mutations, 1):
            problem = None
            touched: list = []
            for path, old, new, occurrences in mutation.sites:
                target = repo_root / path
                original = target.read_text(encoding='utf-8')
                backups.setdefault(path, original)
                found = original.count(old)
                if found != occurrences:
                    problem = f'{path}: 원문 {found}건 (기대 {occurrences})'
                    break
                mutated = original.replace(old, new, occurrences)
                if mutated == original:
                    problem = f'{path}: 치환이 아무것도 바꾸지 않았다'
                    break
                target.write_text(mutated, encoding='utf-8')
                if target.read_text(encoding='utf-8') == original:
                    problem = f'{path}: 쓰기가 반영되지 않았다'
                    break
                touched.append(path)
                syntax = _python_syntax_problem(path, mutated)
                if syntax is not None:
                    problem = syntax
                    break

            if problem is not None:
                for path in touched:
                    (repo_root / path).write_text(backups[path], encoding='utf-8')
                for path, _o, _n, _c in mutation.sites:
                    backups.pop(path, None)
                not_applied.append((index, mutation, problem))
                print(f'{index:2}. NOT-APPLIED [{mutation.axis}] {mutation.defect} '
                      f'— {problem}')
                continue

            outcome = _seal_verdict()
            for path in touched:
                (repo_root / path).write_text(backups[path], encoding='utf-8')
            for path, _o, _n, _c in mutation.sites:
                backups.pop(path, None)

            if outcome == 'hang':
                # ⚠️ 매달림은 KILLED 가 아니다 — 봉인이 그 결함을 **보았다는 증거가
                # 없다**. 그 변이가 코드를 무한 루프로 만들었다는 사실만 안다.
                hung.append((index, mutation))
                print(f'{index:2}. HUNG     [{mutation.axis}] {mutation.defect} '
                      f'— 봉인이 {int(SEAL_TIMEOUT_SECONDS)}s 안에 끝나지 않았다',
                      flush=True)
                continue
            killed = outcome == 'fail'
            verdict = 'KILLED  ' if killed else 'SURVIVED'
            print(f'{index:2}. {verdict} [{mutation.axis}] {mutation.defect}',
                  flush=True)
            if not killed:
                survived.append((index, mutation))
    finally:
        if not interrupted['flag']:
            _restore_all()

    total = len(mutations)
    killed = total - len(survived) - len(not_applied) - len(hung)
    print(f'\n{killed}/{total} KILLED · {len(survived)} SURVIVED · '
          f'{len(not_applied)} NOT-APPLIED · {len(hung)} HUNG')
    if hung:
        print('\n⚠️ HUNG 은 "봉인이 잡았다" 가 아니다 — 그 변이가 코드를 매달았고, '
              '봉인이 무엇을 보았는지는 알 수 없다:')
        for index, mutation, in ((i, m) for i, m in hung):
            print(f'   {index:2}. [{mutation.axis}] {mutation.defect}')
    if not_applied:
        print('\n⚠️ NOT-APPLIED 는 "봉인이 잡았다" 가 아니라 "시험하지 못했다" 이다:')
        for index, mutation, why in not_applied:
            print(f'   {index:2}. [{mutation.axis}] {mutation.defect} — {why}')
    if survived:
        print('\n⚠️ SURVIVED — 이 결함들은 봉인이 보지 못한다:')
        for index, mutation in survived:
            print(f'   {index:2}. [{mutation.axis}] {mutation.defect}')
    return 0 if not (survived or not_applied or hung) else 1
