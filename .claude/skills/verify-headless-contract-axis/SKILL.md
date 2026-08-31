---
name: verify-headless-contract-axis
description: headless 계약 표면의 분해 축 봉인 (2026-08-29). 이 표면은 **이미 분해돼 있었는데, 어제 central 에서 실측이 기각한 축(표 종류)으로** 나뉘어 있었다 — schemas 1309 / dtos 1072 / operations 532 / constants 263 / facade 111. 축은 발명이 아니라 실측이고, 이번엔 그 측정을 **버리지 않았다**(`scripts/measure_contract_decomposition_axis.py`). 같은 도구로 두 표면을 같은 모집단(operation 을 만진 **진화** 커밋 — 표면을 만들거나 통째로 옮긴 커밋은 어느 축으로 잘라도 전부를 만지므로 「그 커밋 시점 operation 의 절반 이상」으로 **기계적 제외**)에서 대조하면: CENTRAL(오늘=표면축) 49건 중 **95.9%** 가 한 파일 · 모듈 중앙값 1, HEADLESS(오늘=표축) 21건 중 **38.1%** · 중앙값 **3**, 표면 축이면 **85.7%**. ⚠️ **결정적 증거는 비율이 아니라 목록이다** — 여러 모듈을 만진 진화 커밋 13건 중 **10건이 route family 를 정확히 하나만** 만졌다(대부분 `/headless/projects`). 흩어짐의 원인이 *변경이 횡단적*이어서라면 어느 축이든 같고 재분해가 무의미한데, 원인이 *배치*이므로 재분해가 정확히 그것을 없앤다. 묶음도 공변 병합으로 파생하고 **과적합 경계에서 멈춘다** — 첫 병합(`/headless/projects`+`/headless/test-plan`, 공변 2)만 신호이고 혼자 +9.5pp, 그 다음은 전부 공변 1 이며 6→5→4 에서 비율이 **평평하다**. 봉인 아홉 — ① **분할이 총이고 서로소**(39 route 가 전부 정확히 한 표면에 **최장 일치**, 중복 prefix·죽은 prefix red), ② **소속이 파생**(operation 은 자기 경로가 지목하는 표면에 선언 + ROUTES↔PERMISSIONS↔OPERATIONS 키 상등 + 병합 = 합집합), ③ **스키마 소유가 `$ref` 폐포 파생**(78 중 76 이 단일 표면, 공용은 `/headless/status` 가 집계하는 2개뿐이고 **공용 표에 있는 것이 정말 둘 이상에 닿는지** 역방향도 단언), ④ **사문 스키마 0**(어느 operation 도 도달 못 하는 스키마는 red — 이 표면은 오늘 0 이다), ⑤ **병합이 중복 키를 조용히 덮어쓰지 않는다**(`DuplicateContractKeyError` 가 두 소유자를 이름으로 대고, 공용 표도 다른 출처와 똑같이 충돌한다), ⑥ **레지스트리가 패키지를 덮는다**(등록 안 된 `surface_*.py` 는 아무것도 병합되지 않은 채 조용히 기여 0 — central 이 남긴 구멍), ⑦ **facade 는 조립만 한다**(top-level 선언 0 + 공개 이름은 `__all__` 이 아니라 **저장소가 실제로 import 하는 이름**을 AST 전수로 대조), ⑧ **모듈 크기가 래칫**(표면 축은 최대 모듈을 1309→1837 로 **키운다** — `surface_test_plan` 이 39 op 중 18 을 갖고 central 표면과 달리 DTO 까지 진다. 줄이는 절단은 전부 측정으로 기각됐다: generation 분리는 85.7%→71.4%, DTO 분리는 표/DTO 를 함께 만진 커밋이 28 중 17. 그러므로 크기는 **측정된 대가**이고 상향 드리프트만 막는다), ⑨ **측정이 노후화하지 않는다**(도구가 커밋되고 그 자신이 봉인된다 — 표 이름을 **형태로** 알아보지 리터럴로 알아보지 않으며, 판정은 docstring 을 제외한 AST 다: 산문은 두 표면을 예시로 들어도 되고 로직은 안 된다). ⚠️ **눈금이 이 축의 일부다** — 이 도구는 **답이 이미 알려진 대상(어제의 central)에서 먼저 쟀고 거기서 세 번 실패**했다(표면 축 분해의 관용구인 모듈별 동명 로컬 표가 「이름→선언」을 단사가 아니게 만들어 9 중 8 을 삼킴 / hunk 는 커밋 시점 AST 에 매핑하면서 표 이름·route 경로는 오늘 것을 씀 / 「routes 표 없으면 거부」 가드가 표를 **조립**하는 facade 를 거부). 셋 다 headless 를 먼저 쟀으면 보이지 않았다. src/application/headless/api_contract*.py · surface_*.py 변경 시 실행.
version: 2026-08-31
source: FCC pytest invariants wrapper (AD-1)
disable-model-invocation: false
trigger_patterns:
  - scripts/measure_contract_decomposition_axis.py
  - scripts/mutation_headless_contract_axis.py
  - src/application/headless/api_contracts.py
  - src/application/headless/api_contract_surfaces.py
  - src/application/headless/api_contract_constants.py
  - src/application/headless/api_contract_primitives.py
  - src/application/headless/api_contract_operation_factory.py
  - src/application/headless/api_contract_shared_schemas.py
  - src/application/headless/api_contract_snapshot.py
  - src/application/headless/api_contract_checker.py
  - src/application/headless/surface_meta.py
  - src/application/headless/surface_provider.py
  - src/application/headless/surface_jobs.py
  - src/application/headless/surface_sessions.py
  - src/application/headless/surface_reports.py
  - src/application/headless/surface_test_plan.py
mapped_invariants:
  - tests/test_headless_contract_axis.py
---

# verify-headless-contract-axis

> ⚠️ **2026-08-31 — 모노레포에서 왔다.** 이 축이 검사하는 코드가 이 레포로
> 이사했으므로 스킬도 따라왔다. 모노레포에 두면 아무것도 실행하지 않는
> 스킬이 된다 — 「검사가 없다」와 「검사가 통과한다」가 같은 값이 되는 자리다.

`tests/test_headless_contract_axis.py` 를 실행하는 얇은 래퍼. 규칙 본문은 그
파일과 `fcc_test_contracts/headless/api_contract_surfaces.py` 가 소유한다 (AD-1).

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_headless_contract_axis.py -q
```

## 이 축이 답하는 질문

**「이 표면은 어느 축으로 잘려 있어야 하는가」는 취향이 아니라 이력의 성질이다.**
파일 목록을 봐서는 알 수 없고, 그 표면을 만진 커밋들이 무엇을 함께 만졌는지가
답한다. 이 저장소는 그 질문을 두 표면에서 물었고 **두 번 다 이미 있던 모양을
뒤집었다** — 그래서 답보다 **절차**가 자산이다.

```bash
# 어느 표면이든 같은 질문을 다시 물을 수 있다
python scripts/measure_contract_decomposition_axis.py \
  --repo . --glob 'src/application/<lane>/<surface>*.py' --json /tmp/axis.json

# 제안한 분할이 실제로 얼마나 좋은지 채점 (오늘의 route 표가 아니라 커밋 시점 경로로)
python scripts/measure_contract_decomposition_axis.py \
  --repo . --glob '...' --grouping proposal.json
```

⚠️ **`--grouping` 을 쓰고 손으로 세지 마라.** 손 계산은 오늘의 route 표로
operation 을 조회하게 되고, **그 사이 삭제된 operation 은 자기 커밋에서 조용히
사라진다.** 이 세션에서 실제로 그렇게 한 번 틀렸다(`test_plan_scope_options`,
85.7% 를 81.0% 로 잘못 읽음).

## 변이 배터리

```bash
python scripts/mutation_headless_contract_axis.py            # 9 변이 전량
python scripts/mutation_headless_contract_axis.py --anchors-only
```

⚠️ **커밋한 뒤에 돌려라.** 신규 모듈이 untracked 이면 `git checkout --` 는
**exit 0 으로 성공하고 아무것도 되돌리지 않는다.** 배터리는 원본을 메모리에 들고
복원하지만, 그 사이 다른 레인을 돌리거나 커밋하면 안 된다.

## 함께 보는 것

- `.claude/evaluations/headless-contract-axis.md` — 측정·눈금·기각된 분할
- `.claude/contracts/headless-contract-axis.md` — MUST 표
- `/verify-central-contract-decomposition` — 같은 절차를 먼저 통과한 표면
- `.claude/rules/check-axis-blindness.md` — 눈금 순서 처방이 사는 곳
