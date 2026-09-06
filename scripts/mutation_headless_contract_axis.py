"""Mutation battery for the headless contract surface axis.

A seal that nothing has ever broken is indistinguishable, from its output, from
a seal that cannot break. This battery breaks it on purpose — nine ways, each
aimed at one property ``tests/test_headless_contract_axis.py`` claims — and
:func:`mutation_harness.run_battery` requires every one to be both **applied**
and killed.

## The machinery is shared, on purpose

``scripts/mutation_harness.py`` owns apply/revert, the NOT-APPLIED verdict, the
syntax check and the hang timeout. The first draft of this file re-implemented
that loop and was missing two of the four — which is exactly what
``TestTheHarnessStaysSingle`` exists to catch: *the copy is the one whose
NOT-APPLIED check goes missing.*

## Targets are derived, never listed

Every anchor is computed from the LIVE modules at import time: the surface to
misplace an operation into, the operation to move, the schema to duplicate, the
module to unregister, even the measurement tool's first ``def``. A frozen anchor
rots the first time the split changes shape, and it rots *silently* — the anchor
stops matching, nothing is mutated, and the battery reports a kill it never
made. The harness calls that NOT-APPLIED and fails, and
``TestTheMutationBatteryCanStillFire`` asserts the same property from outside.

## ⚠️ Two of the nine are NO-RUN, and that is the honest answer (2026-09-06)

Until 2026-09-06 this battery reported **9/9 KILLED**. Two of those kills were
never made: the harness read every non-zero ``pytest`` exit as *"the seal went
red"*, and these two exit **2** — a collection error, with no test run at all.

They are the two that duplicate a contract key on a **real** surface module
(``the merge refuses to lose a contract`` and ``schema ownership is derived from
reachability``). ``merge_surface_table`` raises ``DuplicateContractKeyError``
while the registry is being **imported**, so ``tests/test_headless_contract_axis.py``
cannot load and nothing in it observes anything.

⚠️ **The defence works — that is what the import error is.** What did not happen
is a *seal* seeing it, and this battery measures seals. The distinction is the
same one this repository already drew for parse errors: *"it did not see the
defect, it saw a parse error."*

The property those two aim at (**the guard sits on the path the real modules
take**) is worth measuring and is not measured by
``test_two_surfaces_declaring_the_same_key_raise`` /
``test_the_shared_table_collides_like_any_other_source``, which build synthetic
surfaces. Re-expressing them so a test can observe the refusal — rather than
being taken down by it — is open work, deliberately not done in the change that
merely stopped miscounting them. Until then this battery exits non-zero, and it
should: two of its nine entries do not measure a seal.

## Order

⚠️ **Commit before running.** The battery edits tracked files, and the surface
modules were untracked when it was first written — ``git checkout --`` on an
untracked path exits 0 having done nothing.
"""
from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
# ⚠️ REPO_ROOT itself, first. It came from the monorepo where the contract lived
# under ``src/``; here it lives in the package at the tree root, so the two
# lines below reached the sibling entry points and the (absent) src tree but
# NOT the package this battery is supposed to mutate — the process fell back to
# the installed ``fcc_test_contracts``. A mutation battery that mutates an
# installed copy reports on a build nobody is editing.
# Measured 2026-09-05 by ``tests/test_scripts_resolve_this_tree.py``.
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'src'))

from mutation_harness import Mutation, run_battery  # noqa: E402

# ⚠️ 2026-08-31 — 이 배터리는 모노레포에서 왔다. 거기서는 소스가
#    `src/application/headless` 였고 여기서는 패키지 안에 있다.
PACKAGE = 'fcc_test_contracts/headless'
SEAL = 'tests/test_headless_contract_axis.py'
TOOL = 'scripts/measure_contract_decomposition_axis.py'


def _tool_anchor() -> str:
    """The measurement tool's first top-level ``def``, read from the tool.

    Quoting a signature here would make this mutation quietly NOT-APPLIED the
    day that function is renamed.
    """
    for line in (REPO_ROOT / TOOL).read_text(encoding='utf-8').splitlines():
        if line.startswith('def '):
            return line
    raise SystemExit('the measurement tool declares no top-level function')


def build_mutations() -> tuple[Mutation, ...]:
    """Derive every anchor from the modules as they are right now."""
    from fcc_test_contracts.headless import api_contract_surfaces as registry
    from fcc_test_contracts.headless import api_contracts as facade

    modules = registry.SURFACE_MODULES
    # Smallest surface is the cheapest donor, largest the least likely to be
    # empty — both derived, so a reshaped split moves the targets with it.
    donor = min(modules, key=lambda m: len(getattr(m, 'ROUTES', {}) or {}))
    host = max(modules, key=lambda m: len(getattr(m, 'ROUTES', {}) or {}))
    donor_leaf = donor.__name__.rsplit('.', 1)[-1]
    host_leaf = host.__name__.rsplit('.', 1)[-1]
    donor_path = f'{PACKAGE}/{donor_leaf}.py'
    host_path = f'{PACKAGE}/{host_leaf}.py'
    facade_path = f'{PACKAGE}/api_contracts.py'
    registry_path = f'{PACKAGE}/api_contract_surfaces.py'

    moved_op = sorted(donor.ROUTES)[0]
    host_op = sorted(host.ROUTES)[0]
    host_schema = sorted(getattr(host, 'SCHEMAS', {}) or {})[0]
    merged_table = next(n for n in facade.__all__ if n.startswith('HEADLESS_API_'))

    donor_text = (REPO_ROOT / donor_path).read_text(encoding='utf-8')
    route_line = next(
        line for line in donor_text.splitlines()
        if line.strip().startswith(f'{moved_op!r}:')
    )
    host_prefix = host.SURFACE_PREFIXES[0]
    donor_prefix = donor.SURFACE_PREFIXES[0]
    prefix_anchor = f'SURFACE_PREFIXES = (\n    {host_prefix!r},'

    return (
        # ⚠️ 대조군이 첫 자리에 있다. 이 배터리가 무엇을 잡는지가 아니라 **이 배터리를
        # 믿어도 되는지**를 묻는다: 봉인이 관측할 수 없는 변이(주석 한 단어, 줄 수
        # 불변 — 크기 래칫도 안 움직인다)가 KILLED 로 오면, 변이와 무관한 무언가가
        # 봉인을 죽이고 있고 그 실행의 다른 KILLED 는 전부 뜻을 잃는다.
        #
        # 손으로 한 번 넣어 보는 것으로는 그날에 대해서만 답한다. KC provider 레인이
        # 2026-09-06 에 정확히 그 차이로 하루를 잃었다 — 새 검사 둘이 배터리 «안»의
        # 환경에서 다르게 동작해 모든 변이가 KILLED 였고, 대조군이 명세에 없어서
        # 그 균일함을 아무도 읽지 않았다.
        Mutation(
            axis='CONTROL',
            defect='주석 한 단어 — 어떤 봉인도 관측하지 않는다',
            path=host_path,
            old='#: Route prefixes this surface owns.',
            new='#: Route prefixes this surface owns!',
            expect='SURVIVED',
        ),
        Mutation(
            axis='membership is derived from the path',
            defect='a surface claims another surface\'s prefix',
            path=host_path,
            old=prefix_anchor,
            new=f'SURFACE_PREFIXES = (\n    {donor_prefix!r},\n    {host_prefix!r},',
        ),
        Mutation(
            axis='a declared prefix owns at least one operation',
            defect='a dead prefix silently widens the surface it sits on',
            path=host_path,
            old=prefix_anchor,
            new=f"SURFACE_PREFIXES = (\n    '/headless/nothing-owns-this',\n"
                f'    {host_prefix!r},',
        ),
        Mutation(
            axis='the merge refuses to lose a contract',
            defect='two surfaces declare one operation key',
            path=donor_path,
            old=route_line,
            new=f'{route_line}\n    {host_op!r}: {host.ROUTES[host_op]!r},',
        ),
        Mutation(
            axis='every schema is reachable from some operation',
            defect='a schema no operation reaches is declared and serialized',
            path=host_path,
            old='SCHEMAS = {',
            new="SCHEMAS = {\n    'NothingReachesThisSchema': {'type': 'object'},",
        ),
        Mutation(
            axis='schema ownership is derived from reachability',
            defect='a schema is declared where its operations cannot reach it',
            path=donor_path,
            old='SCHEMAS = {',
            new=f'SCHEMAS = {{\n    {host_schema!r}: {{"type": "object"}},',
        ),
        Mutation(
            axis='the facade only assembles',
            defect='the facade declares a contract entry of its own',
            path=facade_path,
            old='from __future__ import annotations',
            new='from __future__ import annotations\n\nEXTRA_CONTRACT_ENTRY = {}',
        ),
        Mutation(
            axis='the registry covers the package',
            defect='a surface module on disk is not registered, so it merges nothing',
            path=registry_path,
            old=f'    {donor_leaf},\n',
            new='',
        ),
        Mutation(
            axis='the recorded module size ratchets down only',
            defect='a surface grows past its recorded size unwatched',
            path=host_path,
            old='from __future__ import annotations',
            new='from __future__ import annotations\n' + '\n'.join(
                f'#: ratchet probe line {n}' for n in range(600)
            ),
        ),
        Mutation(
            axis='the measurement derives table names',
            defect='the measurement names one surface\'s table, so it can measure only that surface',
            path=TOOL,
            old=_tool_anchor(),
            new=f'_NAMED_TABLE = {merged_table!r}\n\n\n' + _tool_anchor(),
        ),
    )


MUTATIONS = build_mutations()


if __name__ == '__main__':
    raise SystemExit(run_battery(
        seal=SEAL, mutations=MUTATIONS, repo_root=REPO_ROOT, doc=__doc__,
    ))
