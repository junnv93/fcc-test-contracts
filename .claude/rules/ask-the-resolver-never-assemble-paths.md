---
paths:
  - "scripts/**/*.py"
  - "tests/**/*.py"
  - "packages/api-artifacts/**"
  - ".extraction-layout.json"
  - "fcc_test_contracts/common/tree_artifacts.py"
---

# 이 트리는 «이사한» 트리다 — 경로를 조립하지 말고 **해소기에게 물어라**

> 이 규칙이 여기 있는 이유: 파일을 찾는 코드를 쓰는 순간에만 참이다.
> 산문으로 읽으면 당연해 보이고, 코드를 쓸 때는 `ROOT / 'docs/api/x.json'` 이
> 손에 먼저 잡힌다.

## 무슨 일이 일어났나 (실측 2026-09-06, `77c593e`)

추출 패키저가 `docs/api/*.openapi.json` 을 `fcc_test_contracts/artifacts/` 로 옮기고
그 사실을 루트 `.extraction-layout.json` 에 적었다. 그런데
`packages/api-artifacts/scripts/sync.mjs` 만 그 기록을 **안 읽고**
`REPO_ROOT + docsSource` 를 **직접 조립**했다. 그래서 그 게이트는
**이 레포에서 구조적으로 초록이 될 수 없었다** — 정본 셋을 「없다」고 보고했다.

같은 레포의 파이썬 쪽은 같은 파일을 잘 찾고 있었다.
**산술을 하는 쪽만 못 찾았다.**

## ⭐ 그리고 그 거짓 빨강이 «진짜 빨강»을 가리고 있었다

기록을 읽게 하자마자 진짜 드리프트 둘이 나왔다 — `platform-api` 860줄,
`central-db-schema` 29줄. **고칠 수 없는 빨강은 고칠 수 있는 빨강을 가린다.**

## 처방

```python
from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact
resolve_repo_artifact(__file__, 'docs/api/headless-api.openapi.json')
#  → fcc_test_contracts/artifacts/headless-api.openapi.json
```

* 저장소가 부르는 이름(`docs/platform/migrations`)으로 **부르고**, 자리는 **묻는다.**
* 모노레포에서는 기록이 없어 「합친 경로 그대로」를 돌려준다 — 그래서 **이 함수를
  채택해도 모노레포 결과는 바이트 단위로 같다.**
* 기록에 없는 경로는 **자기 자신으로** 해소된다. 그것은 조용한 성공이 아니라,
  없는 경로를 «이름으로» 대고 실패하는 것이다.

⚠️ **`.extraction-layout.json` 의 값을 손으로 고치지 마라.** 디렉터리 이사는 파일
기록에서 **파생**된다. 값을 고치면 디렉터리 해소기가 거부한다.

⚠️ **진단 메시지에도 「실제로 본 자리」를 대라.** 매니페스트 이름만 찍으면 읽는 사람이
**이 트리에 없는 경로**를 찾으러 간다.

> ### 🧭 스스로 묻는 질문
> **「이 코드가 파일의 자리를 «계산»하는가, «묻는»가?」**
> 계산한다면, 그 답은 이 트리에서 틀릴 수 있고 **틀린 답은 「없음」과 같은 모양**이다.
