"""이 레인이 발행하는 OpenAPI 문서가 **자기 SSOT 와 일치하는가**.

⚠️ **이 축이 없던 동안 다섯 사본이 다 같이 낡았다.** 실측 2026-09-04: 계약이
``v0.1.17`` 인데 ``headless-api.openapi.json`` 다섯 벌(모노레포 1 · 이 레인 2 ·
플랫폼 2)이 **byte 동일하게** ``v0.1.12`` 시절 내용이었다.

⚠️ **사본이 서로 어긋난 것이 아니다** — 다섯이 완전히 같았다. 어긋난 것은
**생산자와 SSOT** 다. 조립기가 모노레포에 있었고 그 레포는 계약 ``v0.1.12`` 를
핀했으므로, 계약이 다섯 번 릴리스되는 동안 아무도 그 문서를 다시 내지 않았다.
사본 사이의 일치를 보는 검사였다면 **끝까지 초록**이었을 것이다.

그래서 이 축은 **사본끼리 비교하지 않는다.** SSOT 에서 문서를 **다시 만들어** 발행본과
비교한다. 그것만이 「생산자가 따라가지 못했다」를 볼 수 있는 축이다.

## 왜 여기여야 하나

조립기가 필요로 하는 것은 전부 이 레인 소유였다(``openapi_schema_builder`` ·
``api_contracts`` 표 아홉 · ``api_error_codes``). 모노레포 의존은 ``TYPE_CHECKING``
아래 타입 힌트 하나뿐, 런타임 의존 0. 그런데 **발행 진입점만** 저쪽에 있어서 SSOT 와
변환기를 가진 레인이 자기 발행물을 재생성하지 못했다 —
``check_headless_provider_registry.py`` 가 2026-08-31 에 이사한 것과 같은 형태다
(KC 판정문 §6.4: *"체커가 contracts 로 이사 — 그 move 가 fix 다"*).
"""
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from fcc_test_contracts.headless.api_contracts import (  # noqa: E402
    HEADLESS_API_ROUTES,
    HEADLESS_API_SCHEMAS,
)
import export_headless_openapi as publisher  # noqa: E402


class TestThePublishedDocumentMatchesTheSsot(unittest.TestCase):
    def test_every_published_copy_is_what_the_ssot_produces(self):
        """⚠️ **사본끼리가 아니라 SSOT 대비로 비교한다** — 위 docstring 참조."""
        canonical = publisher.canonical_document()
        stale = [
            str(path) for path in publisher.published_paths()
            if not path.is_file() or path.read_text(encoding='utf-8') != canonical
        ]
        self.assertEqual(
            stale, [],
            '발행본이 SSOT 에서 다시 만든 문서와 다르다:\n  ' + '\n  '.join(stale)
            + '\n\n  fix: python3 scripts/export_headless_openapi.py',
        )

    def test_at_least_one_copy_is_declared(self):
        """비-공허성 팔.

        ⚠️ *이 검사가 성공하면 이 팔이 red 가 되는가?* → 아니오. 발행 자리가 몇이든
        초록이고 0일 때만 red 다. 이 팔이 없으면 ``PUBLISHED_RELATIVE_PATHS`` 가 비는
        날 위 검사가 **0회 돌고 초록**이 된다 — 그것이 이 축이 끝내려는 침묵과 같은
        모양이다.
        """
        self.assertTrue(publisher.PUBLISHED_RELATIVE_PATHS)
        self.assertTrue(publisher.published_paths())


class TestTheDocumentIsDerivedNotTranscribed(unittest.TestCase):
    """⚠️ 발행본이 SSOT 와 같다는 것만으로는 **둘 다 손으로 적혔을 수** 있다.

    이 클래스는 문서가 계약 표에서 **파생**됐음을 본다 — 표를 바꾸면 문서가 따라
    움직이는가. 위 검사만 있으면 조립기가 상수 dict 를 돌려주도록 퇴화해도 초록이다.
    """

    def test_the_document_follows_a_change_in_the_schema_table(self):
        probe = '_PublicationAxisProbeSchema'
        self.assertNotIn(probe, HEADLESS_API_SCHEMAS, '탐침 이름이 이미 쓰이고 있다')
        HEADLESS_API_SCHEMAS[probe] = {'type': 'object', 'properties': {}}
        try:
            rebuilt = json.loads(publisher.canonical_document())
        finally:
            HEADLESS_API_SCHEMAS.pop(probe, None)
        self.assertIn(
            probe, rebuilt['components']['schemas'],
            '스키마 표에 더한 것이 문서에 안 나타났다 — 문서가 파생물이 아니라 사본이다',
        )

    def test_every_route_reaches_the_document(self):
        """경로 표 전체가 문서에 도달하는가 — 개수가 아니라 **집합**으로 본다."""
        document = json.loads(publisher.canonical_document())
        # ⚠️ 값은 dict 가 아니라 ``(method, path)`` 튜플이다. 첫 판이 ``r['path']``
        # 로 읽어 red 였고, 그것은 계약의 결함이 아니라 이 검사의 가정이 틀린 것이었다.
        self.assertEqual(
            sorted({path for _method, path in HEADLESS_API_ROUTES.values()}),
            sorted(document['paths']),
            '계약의 경로 집합과 발행 문서의 경로 집합이 다르다',
        )


if __name__ == '__main__':
    unittest.main()
