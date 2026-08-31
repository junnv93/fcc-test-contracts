# 열린 질문 — 답이 없는 것을 답이 있는 것처럼 적지 않기 위해

이 레인이 **오늘 답할 수 없는** 설계 질문을 이름으로 둔다. 산문 경고는 검사가 아니므로,
답이 서면 그것을 **실행되는 검사**로 옮기고 여기서 지운다.

---

## 1. 외부 provider 의 계약 아티팩트는 어디에 사는가 (2026-08-31, 미해결)

`scripts/check_headless_provider_registry.py` 는 레지스트리의 `contract_artifact` 를
**이 트리 기준**(`artifacts/`)으로 해소한다. 그것이 성립하는 이유는 오늘 등록된 셋이
전부 **우리가 발행한** 것이기 때문이다:

| provider | 아티팩트 | 누가 발행하나 |
|---|---|---|
| `fcc-unlicensed-conducted` | `artifacts/headless_api_contract.v1.json` | 우리 (SSOT 자신) |
| `fcc-mmwave-headless` | `artifacts/mmwave_..._api_contract.example.json` | 우리 (**예시**, 구현 아님) |
| `fcc-licensed-headless` | `artifacts/licensed_..._api_contract.example.json` | 우리 (**예시**, 구현 아님) |

⚠️ **뒤의 둘이 예시라는 사실이 이 질문을 지금까지 가려 왔다.** 셋 다 여기 있으니 해소가
성립했고, 배치 검사는 초록이었다 — 그런데 그 초록은 **아티팩트가 SSOT 의 byte-copy 라
구조적으로 통과할 수밖에 없어서** 나온 것이다(`provider` 블록을 떼고 비교한다).

**진짜 provider 가 붙으면 그 전제가 사라진다.** KC(`kc-unlicensed-headless`,
운영자 확정 2026-08-31)는 자기 저장소에서 자기 구현으로부터 아티팩트를 export 한다.
그러면 레지스트리는 **이 트리에 없는 파일**을 가리켜야 하고, 오늘의 해소 규칙에는
그 답이 없다.

**후보 셋. 셋 다 대가가 다르고, 아직 아무도 고르지 않았다:**

| 안 | 형태 | 대가 |
|---|---|---|
| 가 | provider 가 자기 아티팩트를 **URL** 로 발행하고 레지스트리가 그것을 가리킨다 | 검사가 네트워크에 의존한다 — 오프라인·재현성이 깨진다 |
| 나 | provider 가 **자기 레포에서** 자기 계약을 검사하고, 중앙은 그 결과만 받는다 | 검사가 provider 마다 흩어진다. 대신 아티팩트는 발행처에 머문다 |
| 다 | provider 아티팩트를 이 트리로 **복사**한다 | ⚠️ **가장 쉽고 가장 나쁘다** — 사본은 갈라지고, 갈라진 것을 아무것도 말해 주지 않는다 |

⚠️ **다안을 조용히 고르지 마라.** 지금 `.example.json` 둘이 정확히 그 형태이고, 그것들이
초록을 만들어 내는 방식이 이 문서의 첫 문단이다. 실제 provider 아티팩트를 복사해 오는
순간, *"KC 가 계약을 만족한다"* 는 보고는 **KC 의 코드가 아니라 우리가 둔 사본**에 대한
보고가 된다.

**소유 웨이브**: KC 등재 웨이브(§4 = 39 operation 구현 완료 시점). 근거·판정 →
FCC 모노레포 `.claude/exec-plans/active/2026-08-31-kc-provider-identity-결정문.md`.
