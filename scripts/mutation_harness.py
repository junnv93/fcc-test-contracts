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
* **Neither was a mutation the seal could not run.** The rule above is about
  *syntax*, and it is enforced by parsing — but a mutation that renames the very
  symbol the seal imports still parses, and then ``pytest`` exits **2**
  (collection error) having run no test at all. Every non-zero exit read as
  ``KILLED``, so *"the seal cannot even load"* and *"the seal caught it"* had one
  value. Only exit **1** means tests ran and failed; everything else is now
  ``NO-RUN``, which is neither killed nor survived. The codes are not recited
  here — :func:`verdict_for` carries them and
  ``tests/test_a_seal_that_could_not_run_is_not_a_verdict.py`` **produces each
  situation and reads the real exit code back**, so a change in ``pytest`` turns
  that red instead of leaving a sentence here quietly wrong. (It already was:
  the first draft attributed a typo in a seal path to exit ``5``. Measured, that
  is ``4``; ``5`` is ``-k`` matching nothing. The verdict was the same either
  way, which is exactly why nobody would have caught it.) (2026-09-06; measured here, and independently in the KC
  provider lane, where a stubbed interpreter returned a constant non-zero code
  and a whole battery reported ``1/1 red`` without ``pytest`` running once.)
* **Restoration is from an in-memory backup, not ``git checkout``**, which would
  delete uncommitted work in the tree.
* **Restoring the source is not restoring the module.** CPython validates a
  ``.pyc`` against ``(source mtime truncated to whole seconds, source size)``,
  so writing a file back does not invalidate bytecode compiled from the
  mutation when both conditions still hold — and they hold for every battery
  whose seal runs in under a second, which is most of them. The second
  condition is met by *good practice*: a length-preserving mutation is the
  recommended shape and it is exactly the one that keeps the size equal.
  Measured 2026-09-06: a two-mutation battery reported both verdicts correctly,
  ``git status`` was clean, the source was byte-identical to HEAD — and the
  seal still failed in that tree, because the module answered with the mutated
  constant. Every write of a Python target now drops its cached bytecode.
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
import importlib.util
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


__all__ = ['Mutation', 'run_battery', 'verdict_for']


@dataclass(frozen=True)
class Mutation:
    """되살릴 결함 하나.

    ⚠️ ``also`` 는 **한 결함이 두 곳을 동시에 되돌려야 재현되는 경우**를 위한 것이다.
    처음 판은 단일 사이트만 지원했고, 그래서 *"비밀번호 변경이 다시 계정 예산을
    소비한다"* 변이가 라우트 호출만 되살려 **아무것도 바꾸지 못한 채** SURVIVED 로
    보고됐다 — 식별자 출처(화이트리스트)가 함께 돌아오지 않으면 그 호출은 과금하지
    않기 때문이다. 무효 변이와 살아남은 변이는 출력이 같으므로, 표현할 수 없는 결함은
    표현할 수 있게 만들어야 한다.

    ⚠️ ``expect`` exists so a battery can carry its own **control** — a mutation
    nothing observes, which must come back ``SURVIVED``. Without it the control
    can only be run by hand, once, and a hand-run control answers only about the
    day it was run.

    The control does not test the seal. It tests **this battery**: if a mutation
    that changes nothing observable comes back ``KILLED``, then something is
    killing the seal for reasons unrelated to any mutation, and every other
    ``KILLED`` on the run means nothing. The baseline check answers the same
    question once, before the first write; a control answers it *under the same
    conditions the mutations run in* — which is where the KC provider lane's
    battery diverged, its new probes behaving differently inside the battery
    environment than outside and turning the whole run red for a reason no
    mutation caused (measured there 2026-09-06: every mutation "killed", and the
    control killed too).

    ⚠️ A control is not a place to park a mutation the seal fails to catch.
    ``SURVIVED`` where ``KILLED`` was expected is still a failure and still
    named; ``expect='SURVIVED'`` is a claim that **nothing could observe this**,
    and it is refused the moment something does.
    """

    axis: str
    defect: str
    path: str
    old: str
    new: str
    occurrences: int = 1
    also: tuple = ()
    expect: str = 'KILLED'

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


def verdict_for(returncode: int) -> str:
    """``'pass'`` · ``'fail'`` · ``'no-run'`` — from ``pytest``'s exit code alone.

    Public and module-level so it can be exercised against **real** exit codes
    rather than a table someone typed. The distinction it draws is the whole
    point: ``1`` is *the tests ran and failed*, which is the only evidence that
    a seal saw anything. Every other non-zero code says the run did not happen,
    and a battery that counts those as kills reports seals it never exercised.

    ⚠️ **The codes are deliberately not enumerated in prose anywhere.** They were
    once, and the sentence was wrong within a day — a typo in a seal path was
    attributed to ``5`` when it is ``4`` (``5`` is ``-k`` matching nothing). The
    verdict is identical for both, so nothing would ever have contradicted it.
    ``tests/test_a_seal_that_could_not_run_is_not_a_verdict.py`` instead *creates*
    each situation and feeds the code ``pytest`` actually returned through this
    function.
    """
    if returncode == 0:
        return 'pass'
    if returncode == 1:
        return 'fail'
    return 'no-run'


def _write(target: Path, text: str) -> None:
    """Write ``text`` to ``target`` **and** drop any bytecode compiled from it.

    Every write in a battery goes through here — the mutation and both restore
    paths — because the hazard is symmetric and only one half of it is loud:

    * a **restore** that leaves stale bytecode hands back a tree whose source is
      byte-identical to HEAD and whose behaviour is the mutation's; the next
      thing anyone runs there is red for a reason nothing in the tree explains;
    * a **mutation** that leaves stale bytecode never applies, and an
      unapplied mutation and a surviving mutation print the same thing — which
      is the first rule this module's own header states, defeated one layer
      below where that rule looks.

    The check above (*"the write actually changed the file"*) reads the source,
    so it is satisfied in both cases. Only removing the cache answers.

    ⚠️ **This removes a file from the tree it is pointed at.** Here that is safe —
    neither this repository nor the monorepo tracks a single ``.pyc`` (measured
    2026-09-06) — but ``scripts/`` travels with the delivered box, so a provider
    can run a battery inside *their* checkout. A tree that tracks its compiled
    files would see this delete tracked content, and a tool that dirties the
    tree breaks its own *"commit before running"* rule. The KC provider lane hit
    exactly that and redirected the child's ``PYTHONPYCACHEPREFIX`` instead;
    if this lane ever ships into such a tree, that is the repair — with a
    **fresh prefix per seal run**, since one prefix for a whole battery carries
    the same staleness outside the tree instead of removing it.
    """
    target.write_text(text, encoding='utf-8')
    if target.suffix != '.py':
        return
    try:
        cached = Path(importlib.util.cache_from_source(str(target)))
    except (NotImplementedError, ValueError):
        return
    try:
        cached.unlink()
    except OSError:
        # Absent, unwritable, or a directory in the way — all of which mean the
        # next import reads the source, which is the outcome this wants.
        pass


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

    def _seal_verdict() -> tuple:
        """``('pass'|'fail'|'hang'|'no-run', detail)``. 넷은 서로 다른 사실이다.

        ⚠️ **`fail` 은 pytest 종료 코드 1 «만» 이다.** 옛 판은 0 이 아니면 전부
        `fail` 이었고, 그래서 *"봉인이 결함을 보았다"* 와 *"봉인을 돌리지 못했다"* 가
        한 값이었다. 어느 코드가 어느 쪽인지는 :func:`verdict_for` 가 답하고, 그
        답은 봉인이 **실제 pytest 를 그 상황에 몰아넣어** 확인한다 — 여기에 표를
        다시 적으면 그 사본이 먼저 낡는다(실제로 한 번 낡았다).

        실측 2026-09-06: 봉인이 import 하는 이름을 바꾸는 변이(문법은 멀쩡하므로 위
        AST 가드를 통과한다)가 `KILLED` 로 집계됐다. 테스트는 한 번도 돌지 않았다.
        """
        result = _run([
            sys.executable, '-m', 'pytest', *seal_paths, '-q', '-x',
            '--tb=no', '-p', 'no:randomly',
        ], repo_root)
        if result is None:
            return ('hang', '')
        verdict = verdict_for(result.returncode)
        if verdict != 'no-run':
            return (verdict, '')
        tail = (result.stdout or result.stderr or '').strip().splitlines()
        return (verdict, f'pytest exit {result.returncode}'
                         + (f' — {tail[-1][:120]}' if tail else ''))

    def _seal_passes() -> bool:
        return _seal_verdict()[0] == 'pass'

    # ⚠️ 미변이 트리가 먼저 green 이어야 한다. red 인 트리에서는 모든 변이가 "KILLED"
    # 로 보이고 배터리는 아무것도 증명하지 않는다.
    print('baseline: 미변이 트리에서 봉인을 확인한다 …', flush=True)
    baseline, detail = _seal_verdict()
    if baseline != 'pass':
        # ⚠️ 「봉인이 빨갛다」와 「봉인을 돌리지 못했다」는 처방이 다르다. 전자는
        # 봉인을 고치는 일이고 후자는 배터리를 고치는 일이다 — 한 문구로 적으면
        # 읽는 사람이 없는 결함을 찾으러 간다.
        if baseline == 'no-run':
            print(f'BASELINE NO-RUN — 봉인을 실행조차 하지 못했다 ({detail}). '
                  '변이를 적용하지 않는다. 봉인 «경로»부터 확인하라.')
        elif baseline == 'hang':
            print(f'BASELINE HUNG — 봉인이 {int(SEAL_TIMEOUT_SECONDS)}s 안에 끝나지 '
                  '않았다. 변이를 적용하지 않는다.')
        else:
            print('BASELINE RED — 변이를 적용하지 않는다. 봉인부터 고쳐라.')
        return 2
    print('baseline OK\n')

    backups: dict = {}
    interrupted = {'flag': False}

    def _restore_all() -> None:
        for path, text in backups.items():
            _write(repo_root / path, text)
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

    not_applied = []
    hung = []
    no_run = []
    unexpected = []
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
                _write(target, mutated)
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
                    _write(repo_root / path, backups[path])
                for path, _o, _n, _c in mutation.sites:
                    backups.pop(path, None)
                not_applied.append((index, mutation, problem))
                print(f'{index:2}. NOT-APPLIED [{mutation.axis}] {mutation.defect} '
                      f'— {problem}')
                continue

            outcome, detail = _seal_verdict()
            for path in touched:
                _write(repo_root / path, backups[path])
            for path, _o, _n, _c in mutation.sites:
                backups.pop(path, None)

            if outcome == 'no-run':
                # ⚠️ KILLED 가 아니다 — 봉인이 그 결함을 **보았다는 증거가 없다**.
                # 테스트가 한 번도 돌지 않았다는 사실만 안다.
                no_run.append((index, mutation, detail))
                print(f'{index:2}. NO-RUN   [{mutation.axis}] {mutation.defect} '
                      f'— {detail}', flush=True)
                continue
            if outcome == 'hang':
                # ⚠️ 매달림은 KILLED 가 아니다 — 봉인이 그 결함을 **보았다는 증거가
                # 없다**. 그 변이가 코드를 무한 루프로 만들었다는 사실만 안다.
                hung.append((index, mutation))
                print(f'{index:2}. HUNG     [{mutation.axis}] {mutation.defect} '
                      f'— 봉인이 {int(SEAL_TIMEOUT_SECONDS)}s 안에 끝나지 않았다',
                      flush=True)
                continue
            killed = outcome == 'fail'
            observed = 'KILLED' if killed else 'SURVIVED'
            expected = observed == mutation.expect
            label = f'{observed:8}' if expected else f'{observed:8}⚠️'
            if mutation.expect != 'KILLED':
                label += f' (expected {mutation.expect})'
            print(f'{index:2}. {label} [{mutation.axis}] {mutation.defect}',
                  flush=True)
            if not expected:
                unexpected.append((index, mutation, observed))
    finally:
        if not interrupted['flag']:
            _restore_all()

    total = len(mutations)
    controls = sum(1 for m in mutations if m.expect != 'KILLED')
    as_expected = total - len(unexpected) - len(not_applied) - len(hung) - len(no_run)
    print(f'\n{as_expected}/{total} 기대대로 · {len(unexpected)} 어긋남 · '
          f'{len(not_applied)} NOT-APPLIED · {len(hung)} HUNG · '
          f'{len(no_run)} NO-RUN'
          + (f'  (대조군 {controls})' if controls else ''))
    if no_run:
        print('\n⚠️ NO-RUN 은 "봉인이 잡았다" 가 아니다 — 봉인이 **실행되지 않았다**. '
              'pytest 종료 코드 1 만이 "테스트가 돌았고 실패했다" 이다:')
        for index, mutation, why in no_run:
            print(f'   {index:2}. [{mutation.axis}] {mutation.defect} — {why}')
    if hung:
        print('\n⚠️ HUNG 은 "봉인이 잡았다" 가 아니다 — 그 변이가 코드를 매달았고, '
              '봉인이 무엇을 보았는지는 알 수 없다:')
        for index, mutation, in ((i, m) for i, m in hung):
            print(f'   {index:2}. [{mutation.axis}] {mutation.defect}')
    if not_applied:
        print('\n⚠️ NOT-APPLIED 는 "봉인이 잡았다" 가 아니라 "시험하지 못했다" 이다:')
        for index, mutation, why in not_applied:
            print(f'   {index:2}. [{mutation.axis}] {mutation.defect} — {why}')
    for index, mutation, observed in unexpected:
        if observed == 'SURVIVED':
            # ⚠️ 이것은 **그 봉인 하나**에 대한 진술이다. 아래 대조군 문구와 접으면
            # 안 된다 — 평범한 생존마다 「이 실행의 모든 판정이 뜻을 잃는다」가
            # 찍히고, 매번 나오는 경고는 아무도 읽지 않으며, 그러면 대조군을 둔
            # 이유가 사라진다.
            print(f'\n⚠️ SURVIVED — 이 결함을 봉인이 보지 못한다:'
                  f'\n   {index:2}. [{mutation.axis}] {mutation.defect}'
                  f'\n   (이 실행의 다른 판정은 그대로 유효하다 — 고칠 곳은 그 봉인이다.)')
        else:
            # ⚠️ 대조군이 죽었다 = 이 실행의 «모든» KILLED 가 뜻을 잃는다. 변이와
            # 무관한 무언가가 봉인을 죽이고 있고, 그 무언가는 다른 변이들 아래에도
            # 있었다. 개별 결과가 아니라 실행 전체에 대한 진술이다.
            print(f'\n🔴 대조군이 KILLED 다 — 이 실행의 모든 판정이 뜻을 잃는다.'
                  f'\n   {index:2}. [{mutation.axis}] {mutation.defect}'
                  f'\n   관측하지 못해야 할 변이를 봉인이 죽였다. 이 실행의 다른'
                  f' KILLED 도 같은 것으로 설명될 수 있다.'
                  f'\n'
                  f'\n   ⚠️ 원인이 둘이고 **② 를 먼저** 확인하라:'
                  f'\n     ① 변이와 무관한 무언가가 봉인을 죽인다 (기계가 오염시켰다).'
                  f'\n     ② 이 대조군이 애초에 무관측이 아니다 — 봉인이 정당하게 봤다.'
                  f'\n   실측 2026-09-06: 이 저장소의 첫 대조군 후보가 주석 «한 줄'
                  f' 추가»였는데,\n   줄 수 래칫이 124 > 123 으로 «정당하게» 관측했다.'
                  f' 배터리는 멀쩡했고\n   대조군이 틀렸다. ② 가 먼저인 이유다.')
    return 0 if not (unexpected or not_applied or hung or no_run) else 1
