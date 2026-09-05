#!/usr/bin/env python3
"""`fcc_test_contracts.extraction_import_boundaries` 의 진입점 — 로직은 그쪽이 갖는다.

⚠️ 이 파일이 **짧은 것이 요점**이다. `scripts/` 는 패키지가 아니라 휠이 나르지
못하므로 이 레인을 소비하는 레포마다 사본이 필요한데, 사본이 이만큼이면
**갈라질 것이 없다.** 알맹이가 바뀌면 휠이 나른다.

형제 진입점 `prepare_headless_extraction_package.py` 와 같은 형태다 — 그쪽이
2026-08-31 에 먼저 갔고, 이쪽이 남아 있던 동안 소비 레인의 추출 러너가 배송 상자에서
import 되지 않았다(공급 폐포 게이트 계급 B, 실측 2026-09-04).

⚠️ `sys.path` 한 줄은 **설치 전에도 돌기 위한 것**이다.
"""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fcc_test_contracts.extraction_import_boundaries import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
