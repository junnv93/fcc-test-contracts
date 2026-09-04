"""Publish (or verify) this lane's headless OpenAPI 3.1 artifact.

⚠️ **이 진입점이 없어서 다섯 사본이 다 같이 낡았다.** 실측 2026-09-04: 계약은
``v0.1.17`` 인데 ``headless-api.openapi.json`` 다섯 벌(모노레포 1 · 이 레인 2 ·
플랫폼 2)이 byte 동일하게 ``v0.1.12`` 시절 내용이었다. 사본이 **서로 어긋난 것이
아니라** 생산자가 SSOT 를 따라가지 못한 것이다 — 조립기
(:mod:`fcc_test_contracts.headless.openapi_document`)가 모노레포에 있었고, 이 레인은
SSOT 와 변환기를 다 가지고도 **자기 발행물을 다시 낼 수 없었다.**

``check_headless_provider_registry.py`` 가 2026-08-31 에 이사한 것과 같은 형태다
(KC 판정문 §6.4). 그때와 같이 **이사가 수리다.**

Usage::

    python3 scripts/export_headless_openapi.py            # 다시 쓴다
    python3 scripts/export_headless_openapi.py --check    # 드리프트만 보고, 쓰지 않는다

⚠️ 직렬화 규약은 모노레포 ``export_session_api_schemas.py`` 와 **같아야 한다**
(``indent=2, sort_keys=True, ensure_ascii=False`` + 끝 개행). 다르면 두 생산자가 같은
문서를 두 가지 바이트로 쓰고, 그 차이가 드리프트로 보인다 — 실측이 아니라 서식 차이가.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fcc_test_contracts.common.tree_artifacts import resolve_repo_artifact  # noqa: E402
from fcc_test_contracts.headless.openapi_document import (  # noqa: E402
    build_headless_openapi_schema,
)

#: 이 레인이 발행하는 자리들. **손 목록이 아니라 레포 어휘**로 부르고, 배송 트리에서는
#: 레이아웃 기록이 답한다. npm 사본은 프론트엔드가 소비하는 같은 문서의 두 번째 배포
#: 채널이라 함께 쓴다 — 하나만 쓰면 그 둘이 갈라진다.
PUBLISHED_RELATIVE_PATHS = (
    'docs/api/headless-api.openapi.json',
    'packages/api-artifacts/artifacts/headless-api.openapi.json',
)


def canonical_document() -> str:
    """직렬화 규약 한 자리. 두 생산자가 같은 바이트를 내야 한다."""
    return json.dumps(
        build_headless_openapi_schema(), indent=2, sort_keys=True, ensure_ascii=False,
    ) + '\n'


def published_paths() -> list[Path]:
    return [resolve_repo_artifact(__file__, rel) for rel in PUBLISHED_RELATIVE_PATHS]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check_only = '--check' in args

    canonical = canonical_document()
    drifted: list[str] = []
    written: list[str] = []

    for path in published_paths():
        current = path.read_text(encoding='utf-8') if path.is_file() else None
        if current == canonical:
            continue
        if check_only:
            drifted.append(str(path))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical, encoding='utf-8')
        written.append(str(path))

    if check_only and drifted:
        print(json.dumps({
            'drifted': drifted,
            'fix': 'python3 scripts/export_headless_openapi.py',
        }, indent=2, ensure_ascii=False))
        return 1
    if written:
        print(json.dumps({'written': written}, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
