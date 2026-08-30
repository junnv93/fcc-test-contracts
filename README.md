# fcc-test-contracts

> ## ⚠️ 이 레포는 **읽기 전용 납품물**입니다
>
> 여기 있는 파일은 이 레포에서 작성되지 않았습니다. 비공개 모노레포
> `junnv93/FCC_mobile_test_automation` 에서 추출 매니페스트를 따라 **생성**되어 배송됩니다.
>
> **여기서 고친 것은 다음 배송에서 조용히 덮어써집니다.** 배송은 이 트리를 병합하지 않고
> *다시 만들기* 때문입니다 — merge 가 아니라 replace 라서 충돌도, 경고도 나지 않습니다.
> 고칠 곳은 원본입니다 → [§변경은 어디로 보내나](#변경은-어디로-보내나)

---

## 이 레포는 무엇인가

세 레인이 공유하는 **의존성 없는 웹 경계 커널(dependency-free shared web-boundary kernel)** 입니다.
provider API DTO, 라우트/operation/스키마 계약, 호환성 검사기와 그 export/check 스크립트,
그리고 모든 웹 표면이 HTTP 뒤에 앉기 위해 필요한 원시 요소들 — 접근 정책, 인증 설정과
OIDC principal 해소, correlation 과 trace 컨텍스트 — 을 담습니다.

**이 레인의 서드파티 하드 의존은 0 입니다.** 그것이 이 레인의 P0 이고, 모노레포의 게이트가
별도 인터프리터 실행으로 판정합니다. `PyJWT` 는 `oidc` extra 로만 들어오며, 그것 없이도
패키지는 설치되고 import 됩니다(OIDC principal 해소가 함수 안에서 lazy import 하기 때문).

의존 방향은 **단방향**입니다. 이 레인은 아무에게도 의존하지 않고, `fcc-test-platform` 이
이 레인에 의존합니다.

---

## 받아가기

```bash
git clone https://github.com/junnv93/fcc-test-contracts.git
cd fcc-test-contracts
```

⚠️ **HTTPS 를 쓰세요.** 이 레포들은 private 이고, 배송 머신에서는 SSH 키가 등록돼 있지
않습니다(실측 2026-08-30: `Permission denied (publickey)`). `gh auth login` 후
`gh auth setup-git` 을 한 번 돌리면 HTTPS 자격증명이 붙습니다.

---

## 지금 이 사본이 정확히 무엇인가 → `EXTRACTED_FROM.md`

원본 SHA · 추출 시각 · 매니페스트 버전 · 파일 수 · 알려진 실패 수는 **`EXTRACTED_FROM.md`** 에
있고 배송할 때마다 새로 생성됩니다.

⚠️ **이 README 에는 그 숫자를 적지 않습니다.** 배송마다 바뀌는 값을 두 곳에 적으면
반드시 어긋나고, 어긋난 쪽을 읽은 사람은 틀린 것을 믿게 됩니다. 숫자가 필요하면
`EXTRACTED_FROM.md` 를 보세요.

---

## ⚠️ 처음 clone 한 사람이 먼저 알아야 할 것 셋

### 1. 여기서 고치지 마세요 (위 §읽기 전용)

### 2. git history 가 없습니다 — 그리고 그건 결함이 아닙니다

운영자 판정으로 **history 를 이전하지 않습니다.** 첫 커밋이 이 레포의 전부입니다.
"누가 왜 이 줄을 썼나"가 필요하면 **모노레포를 직접 조회**하세요 — 그쪽에 전부 있습니다.
`git log` / `git blame` 이 비어 보이는 것은 정상입니다.

### 3. 테스트가 전부 통과하지 않습니다 — 그리고 그것도 알려진 상태입니다

이 상자는 자기 테스트 suite 를 싣고 있고, 그중 **일부는 실패한 채로 배송됩니다.**
그 실패는 **node id 집합으로 모노레포 매니페스트에 등재돼** 있고
(`governance.delivered_test_run_baseline`), 한 방향으로만 줄어듭니다.

> **당신이 무언가를 깨뜨린 것이 아닙니다.** 정확한 개수는 `EXTRACTED_FROM.md` 에 있습니다.

⚠️ 개수가 아니라 **이름 집합**으로 판정하는 이유: 개수는 *고쳐진 실패*와 *새로 깨진 실패*를
맞바꾼 것을 구분하지 못합니다. 통과 개수가 그대로여도 다른 것이 깨져 있을 수 있습니다.

---

## 어떻게 돌리나

### 설치

```bash
python3 -m pip install -e .            # 런타임 (서드파티 의존 0)
python3 -m pip install -e '.[test]'    # + pytest
python3 -m pip install -e '.[oidc]'    # + PyJWT — auth_mode=oidc_jwt 배포에서만 필요
```

Python **3.11 이상**이 필요합니다(중앙 API 컨테이너 베이스 이미지에서 파생된 하한).

### 테스트

이 레인은 형제 레인이 없으므로 상자 하나로 돕니다.

```bash
PYTHONPATH="$PWD:$PWD/scripts" \
python3 -m pytest -q -p no:randomly -p no:cacheprovider \
        --tb=no -ra --continue-on-collection-errors
```

⚠️ **`--continue-on-collection-errors` 는 장식이 아닙니다.** pytest 는 기본적으로 모듈 하나가
import 실패하면 수집 전체를 중단합니다. 그러면 상자가 **0개를 수집하고**, 0개는 "새 실패 없음"을
완벽하게 만족합니다 — 실패가 성공과 같은 모양이 됩니다. 이 플래그가 그 모듈을 하나의 `ERROR`
노드로 남겨서 다른 실패와 똑같이 판정되게 합니다.

⚠️ **`scripts/` 는 이 상자에서 의도적으로 패키지가 아닙니다**(`__init__.py` 없음).
그 모듈들은 최상위 이름으로만 도달 가능하므로 `PYTHONPATH` 에 `scripts/` 가 따로 들어갑니다.
그래서 `pip install` 은 `scripts/` 를 담지 않습니다.

---

## ⚠️ 세션 노드 배포 자산은 이 상자에 없습니다

이 상자는 `packages/` 를 싣지만 `packages/session-node-artifacts/` 는 **없습니다.**
그것은 매니페스트에 실재하는 별도 레인 `fcc-chamber-node` 의 소유이고, 그 레인은 오늘
**어느 상자에도 배송되지 않습니다**(`extraction_target: false`).

`packages/` 가 있는데 그 하위 하나만 없으므로 찾다 보면 빠뜨린 것처럼 보입니다.
빠뜨린 것이 아닙니다. `fcc-chamber-node` 가 배송되기 시작하면 이 문단을 요구하는 봉인이
스스로 꺼집니다.

---

## 무엇이 아직 없나 — 이 배송의 완료명은 「첫 배송 + 리허설」입니다

「레포 분리 완료」가 **아닙니다.** 다음이 아직 없습니다:

| 없는 것 | 뜻 |
|---|---|
| **CI** | 이 레포에서 게이트가 돌지 않습니다. 판정은 아직 모노레포에서만 납니다 |
| **lockfile** | 두 배포물을 담을 인덱스가 아직 없어 해석기가 비교할 대상이 없습니다 |
| **설치 검증** | 휠이 빌드된다는 것과 설치된 배포물이 돈다는 것은 다른 명제입니다 |
| **태그된 릴리스** | `pyproject.toml` 의 `version` 은 형제 npm 배포물에서 파생된 값이고, 이 레포에는 아직 대응하는 태그가 없습니다 |

---

## 변경은 어디로 보내나

읽기 전용 고지가 만드는 질문에 답이 없으면 그 고지는 막다른 길입니다. 답은 이렇습니다.

1. **모노레포 접근 권한이 있다면** — `junnv93/FCC_mobile_test_automation` 에서 고치세요.
   이 트리의 각 파일이 모노레포의 어느 경로에서 왔는지는 추출 매니페스트
   `docs/api/headless_contract_extraction_manifest.v1.json` 의 `entries` 가 갖고 있습니다
   (`current_path` → `future_path`).
2. **접근 권한이 없다면** — 이 레포에 **이슈**를 여세요. PR 은 병합될 수 없습니다.
   원본이 여기가 아니므로, 여기 머지된 커밋은 다음 배송에서 사라집니다.

⚠️ **이것은 불편이 아니라 설계입니다.** 이 분리의 목적은 아키텍처가 아니라 **공개 범위**입니다 —
측정 코드·GUI·EUT 제어·Excel 은 비공개로 남고, 그 나머지가 여기서 팀과 함께 개발됩니다.
사본에서 편집을 허용하면 그 경계가 바로 무너집니다.

---

## 레이아웃

| 경로 | 내용 |
|---|---|
| `fcc_test_contracts/` | 레인의 런타임 코드. 최상위 import 패키지 |
| `tests/` | 이 레인의 테스트 suite (귀속 ∪ import 폐포 ∪ `conftest.py`) |
| `scripts/` | 운영자 CLI. **패키지가 아닙니다** — 최상위 이름으로 도달 |
| `artifacts/` · `packages/` | 계약 아티팩트(OpenAPI 스키마 등)와 npm 배포물 |
| `docs/` | 이 레인이 소유한 계약 문서 |
| `pyproject.toml` | 설치 선언. 모노레포 `packaging/fcc-test-contracts/` 에서 리뷰되고 여기 루트로 배송됩니다 |
| `.extraction-layout.json` | ⚠️ **지우지 마세요.** 패키저가 *무엇을 어디로 옮겼는지* 남긴 기록이고, 런타임 아티팩트 해소기가 이것을 읽습니다. 빌드 잔여물이 아닙니다 |
