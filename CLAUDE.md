# CLAUDE.md — fcc-test-contracts

<!--
  이 파일에는 **모든 세션에 참인 것만** 남긴다. 200줄을 넘기면 내용을
  `.claude/rules/` 의 `paths:` 규칙으로 내릴 신호다.
  근거(code.claude.com/docs/en/memory): "target under 200 lines per CLAUDE.md file.
  Longer files consume more context and reduce adherence."

  ⚠️ 이 파일이 생기기 전(2026-09-07 이전) 이 레인에는 세션 시작 시 도달하는
     프로젝트 규칙이 **하나도 없었다.** `.claude/rules/` 가 비어 있었고
     (파일 0개), `CLAUDE.md` 도 없었다. 형제 레인(platform)은 규칙 셋이
     있었지만 전부 `paths:` 조건부라 결과는 같았다.
-->

## 이 레포는 무엇인가

세 레인이 공유하는 **의존성 없는 웹 경계 커널**. provider API DTO · 라우트/
operation/스키마 계약 · 호환성 검사기 · 접근 정책 · 인증 설정과 OIDC principal
해소 · correlation/trace 컨텍스트.

의존 방향은 **단방향**: 이 레인은 아무에게도 의존하지 않고, `fcc-test-platform`
이 이 레인에 의존한다.

---

## P0 — 모든 세션이 지켜야 하는 것

### 1. 서드파티 하드 의존은 **0** 이다

`pyproject.toml` 의 `dependencies = []` 가 그것이다(실측). `PyJWT` 는 `oidc`
extra 로만 들어오며, 그것 없이도 패키지는 설치되고 import 된다 — OIDC principal
해소가 **함수 안에서 lazy import** 하기 때문이다.

⚠️ **이것이 이 레인의 존재 이유다.** 모듈 최상단에 서드파티 import 를 하나
추가하는 것은 기능 추가가 아니라 **이 레인의 계약을 깨는 것**이다.

### 2. 이 레포는 태그를 **두 종류** 발행하고, platform 이 그것을 핀으로 소비한다

| 태그 | 무엇 | 소비하는 곳 |
|---|---|---|
| `v0.1.x` | `fcc-test-contracts` (레포 루트 패키지) | platform `pyproject.toml` · `requirements-central.txt` |
| `kernel-v0.x.y` | `packages/fcc-test-kernel` (subdirectory) | 같음 |

⚠️ **핀은 platform 쪽 «두 파일»에 있다.** 한쪽만 올리면 조용히 갈라진다.
그리고 **커널 변경은 태그가 먼저 나가야** platform 이 그것을 쓸 수 있다 —
즉 2-레포 작업이고 **순서가 있다.**

⚠️ **태그 push 는 사람의 승인 지점이다.** 되돌릴 수 없고, 형제 레포의 핀이
그것을 가리키게 된다. 「진행해라」 하나로 다른 작업과 묶지 마라.

### 3. 검사 게이트는 «이름 집합» 으로 판정한다 — 그리고 여기 기준선은 «비어 있지 않다»

`python3 scripts/lane_check.py --root .` 는 관측된 실패 **이름 집합**이
`delivered_test_run_baseline.json` 의 선언과 같은지 본다.

⚠️ **이 레인의 선언된 실패는 29건이다** (2026-09-07 실측).
형제 레인 platform 은 **0건**이다. 두 레인의 기준선 의미가 다르므로,
platform 의 「실패를 보면 그것은 네 환경 문제이거나 새로 깨진 것」을
여기 그대로 옮기면 틀린다. **여기서는 29건이 정상이다.**

* 개수가 아니라 **이름**이다 — 하나 고치고 하나 깨뜨리면 개수는 같다.
* 고쳐진 실패도 **red** 다 — 선언이 낡았다는 사실이고 그것도 소식이다.
* **새 실패를 기준선에 추가하지 마라.** 그것은 부채 등재이고 별도 승인 사항이다.

### 4. 훅은 **`pre-push` 하나뿐**이다 — platform 과 다르다

| | contracts (여기) | platform |
|---|---|---|
| `pre-push` (레인 검사 차단) | ✅ | ✅ |
| `commit-msg` (17항목 자가점검) | ❌ **없다** | ✅ |
| `pre-commit` (브랜치·claim, 혼합 커밋) | ❌ **없다** | ✅ |

⚠️ 그래서 **여기 커밋 메시지에는 17항목 자가점검이 요구되지 않는다.**
platform 의 관행을 그대로 옮기지 마라 — 그리고 그 반대도 마찬가지다.

설치는 clone 마다 opt-in: `git config core.hooksPath githooks`.

### 5. 의도는 **platform 에 적는다**

새 기능·동작 변경은 `fcc-test-platform/intent/<slug>/intent.md` 에서 시작한다.
**이 레포에는 `intent/` 폴더를 만들지 않는다.**

근거: 커널 변경은 대개 platform 의 필요에서 나오고, 의도를 두 곳에 나누면
반드시 갈라진다. 실행이 이쪽에서 일어나는 비대칭은 그쪽 `spec.md` §4
「영향받는 경계」가 흡수한다 — 거기에 「contracts 도」라고 적으면 **커널 태그가
먼저 나가야 한다**는 것이 계획에 들어온다.

규칙 본문 SSOT → `fcc-test-platform/intent/README.md`

---

## 명령

```bash
# 레인 게이트 (pre-push 와 CI 가 부르는 것과 같은 진입점)
python3 scripts/lane_check.py --root .

# 테스트
python3 -m pytest tests/ -q
```

`FCC_LANE_CHECK_PYTHON` 이 없으면 pre-push 가 시스템 python3 로 돌아
「pytest 가 없다」로 막힐 수 있다 — venv 인터프리터를 가리켜라.

---

## 이 레포 문서에서 «오늘 거짓인» 서술

<!-- 낡은 문장을 믿고 잘못된 판정을 내린 사례가 반복해서 있었다. -->

| 어디 | 뭐라고 적혀 있나 | 실측 (2026-09-07) |
|---|---|---|
| `README.md` 옛 판 | 이 레인은 **읽기 전용 납품물** | **거짓.** 배송 기계는 2026-08-31 퇴역. 여기서 고친다 |
| `README.md` | git history 가 **없다**, 첫 커밋이 전부 | **거짓.** 이 레포는 자기 이력을 갖고 개발이 여기서 일어난다 |
| `checks.yml` 계열 | Actions 가 러너를 **못 받는다** | **거짓.** 최근 런 전부 `success` |

구조·품질 판정은 **이 레포에 직접 도구를 돌려서** 하라.

---

## `main` 보호 — 값과 «platform 과 다른 이유»

2026-09-07 운영자 위임으로 켰습니다. 되읽기로 검증한 값:

| 값 | 설정 | 왜 |
|---|---|---|
| PR 필수 | 켬 | 실측: 최근 40 착지 중 39 가 PR 머지, 직접 push 1건(2026-09-01) |
| 필수 검사 | `lane-check` | 실측한 check run **이름** |
| 필수 승인 수 | **0** | 협업자 1명 + GitHub 은 자기 PR 자기 승인 금지 |
| `require_code_owner_reviews` | **끔** | 켜면 협업자 1명이라 그 경로를 아무도 못 고친다. 그리고 이 레포의 `CODEOWNERS` 는 **팀 핸들이 없는 초안**이다 |
| `strict` | **끔** | `lane-check` 이 «합친 트리»를 본다 — 실증: `HEAD is now at fd08072 Merge f8992ee… into 50d7edb…` |
| `required_linear_history` | **끔** | 머지 커밋을 쓴다(실측: 최근 5 착지 전부 부모 2개). 켜면 **전부 막힌다** |
| force push · 삭제 | 금지 | ⚠️ **`main` 에만** 걸린다. 기능 브랜치 삭제는 그대로 된다 |

### 🔴 `enforce_admins` 는 **꺼 두었습니다** — platform 과 «다릅니다»

platform 은 `true` 입니다. 여기만 `false` 이고, 그 이유를 적어 둡니다.

**이 레인은 태그를 내는 레인입니다.** platform 의 핀(`v0.1.x` · `kernel-v0.x.y`)이
여기서 나옵니다. 그런데 이 계정의 Actions 는 **할당량 때문에 러너를 못 받은 전례가
있고**(2026-08), 그 건에 대한 2026-09-07 판정은 **「지금은 그대로 둔다」**입니다 —
즉 **원인이 해소되지 않았습니다.**

`enforce_admins: true` 였다면 그날 이 레인의 머지가 **전면 정지**하고, 그것은
지역적 불편이 아니라 **공급 사슬이 멈추는 것**입니다. platform 은 소비 레인이라
멈춰도 여기서 끝나지만, 여기가 멈추면 두 레포가 함께 멈춥니다.

> **그래서 여기서 `lane-check` 은 「관리자에게는 권고」입니다.**
> 「red 면 서버가 막는다」는 **관리자에게 참이 아닙니다.** 이 문장을 지우지 마십시오 —
> 지우면 다음 사람이 틀린 보장을 믿습니다.

⚠️ **할당량이 다시 차면** 원인은 `lane-check` 의 red 가 아니라 **러너 부재**입니다.
「도구가 없다」와 「위반이 있다」가 같은 빨강으로 보이므로, 그날 먼저 확인할 것은
`gh api repos/junnv93/fcc-test-contracts/actions/runs/<id>/jobs` 의 `runner_name` 입니다.

되돌리기: `gh api -X DELETE repos/junnv93/fcc-test-contracts/branches/main/protection`
(적용 전 값은 **없었습니다** — `404`. 적용값 사본: `.git/branch-protection-applied-20260907.json`)

⚠️ **선언 ↔ 실제 대조 검사는 아직 여기 없습니다.** platform 에는
`scripts/check_gate_declaration.py` + `.claude/contracts/branch-protection-declaration.json`
이 있지만, 그것을 여기 복사하면 사본이 갈라집니다. 위 표는 **손으로 쓴 산문**이고,
이 저장소가 하루에 다섯 번 틀린 것이 정확히 그 종류입니다. 후속 과제입니다.

## 참조

* `fcc-test-platform/intent/README.md` — 의도 흐름의 규칙 본문
* `EXTRACTED_FROM.md` — 이 사본이 정확히 무엇인가 (숫자는 여기에만 있다)
* `.claude/skills/verify-headless-contract-axis/` — 계약 축 검증 스킬
