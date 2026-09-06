"""`@fcc/api-artifacts` 의 거울이 정본과 갈라지지 않는가 (2026-09-06).

■ 왜 pytest 인가

이 상자의 실질 게이트는 `scripts/lane_check.py` 이고 그것은 **pytest 만** 부른다
(`[sys.executable, '-m', 'pytest', ...]`). 그래서 node 로만 도는 검사는 이 레포에서
아무도 보지 않는다 — `packages/api-artifacts/README.md` 는 그 검사가
`frontend-build.yml` 에서 돈다고 적었지만 **이 레포에 그런 워크플로가 없다.**
같은 README 가 이 파일(`tests/test_api_artifacts_package.py`)도 이름으로 댔는데
그것 역시 **없었다.** 두 봉인을 이름으로 약속하고 둘 다 없는 상태였다.

■ 왜 「다시 구현」하지 않고 「불러서」 판정하는가

거울 판정 규칙을 여기 다시 적으면 그 순간 게이트가 둘이 되고, 둘은 갈라진다.
`sync.mjs` 가 SSOT 이므로 그것을 **실행**해서 종료코드로 판정한다.
(같은 규율: `scripts/lane_check.py` 가 pytest 명령을 워크플로에 인라인하지 않는 이유.)

■ 이 검사가 오래 «거짓 빨강» 이었다 (2026-09-06 실측)

`sync.mjs` 는 `REPO_ROOT + docsSource` 를 조립해 정본을 찾았다. 그런데 이 트리는
**이사한 트리**다 — 추출 패키저가 `docs/api/*.openapi.json` 을
`fcc_test_contracts/artifacts/` 로 옮기고 그 사실을 `.extraction-layout.json` 에
적어 두었다. 그래서:

    session-api    "canonical source missing"   ← 거짓. 옮긴 자리에 있다
    headless-api   "canonical source missing"   ← 거짓. 옮긴 자리에 있다
    platform-api   "canonical source missing"   ← 거짓. 옮긴 자리에 있다
    central-db     DRIFT                        ← 참

레포의 파이썬 쪽(`scripts/export_headless_openapi.py`)은 `resolve_repo_artifact` 에게
**물어서** 같은 파일을 잘 찾고 있었다. 산술을 한 쪽만 못 찾았다.

⚠️ **그리고 그 거짓 빨강 뒤에 진짜 드리프트 둘이 숨어 있었다** — `platform-api`(860줄)
와 `central-db-schema`(29줄). 고칠 수 없는 빨강은 고칠 수 있는 빨강을 가린다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = PROJECT_ROOT / 'packages' / 'api-artifacts'
SYNC = PKG_ROOT / 'scripts' / 'sync.mjs'
MANIFEST = PKG_ROOT / 'manifest.json'
LAYOUT = PROJECT_ROOT / '.extraction-layout.json'


def _relocations() -> dict[str, str]:
    """이 트리가 무엇을 어디로 옮겼는지. 기록이 없으면 아무것도 안 옮긴 것이다."""
    if not LAYOUT.is_file():
        return {}
    return json.loads(LAYOUT.read_text(encoding='utf-8')).get('paths', {})


def _canonical_path(docs_source: str) -> Path:
    return PROJECT_ROOT / _relocations().get(docs_source, docs_source)


class TheManifestNamesFilesThatExistHere(unittest.TestCase):
    """⚠️ 집합을 매니페스트에서 파생한다 — 항목이 늘면 이 검사가 따라 늘어야 한다."""

    def setUp(self) -> None:
        self.entries = json.loads(MANIFEST.read_text(encoding='utf-8'))['artifacts']

    def test_the_manifest_is_not_empty(self) -> None:
        """공집합형 봉인의 함정 — 매니페스트가 비면 아래 전부가 조용히 초록이 된다."""
        self.assertGreater(len(self.entries), 0, '매니페스트에 아티팩트가 0개다')

    def test_every_canonical_source_resolves_and_exists(self) -> None:
        missing = [
            f"{e['name']}: {e['docsSource']} → {_canonical_path(e['docsSource'])}"
            for e in self.entries
            if not _canonical_path(e['docsSource']).is_file()
        ]
        self.assertEqual(
            [], missing,
            '매니페스트가 이 트리에 없는 정본을 가리킨다. 이사 기록'
            f'({LAYOUT.name})을 거친 뒤에도 없다면 그것은 진짜 부재다:\n  '
            + '\n  '.join(missing),
        )

    def test_every_mirror_is_byte_identical_to_its_canonical(self) -> None:
        drifted = []
        for e in self.entries:
            src = _canonical_path(e['docsSource'])
            dest = PKG_ROOT / 'artifacts' / e['file']
            if not src.is_file():
                continue  # 위 시험이 이미 red 다
            if not dest.is_file():
                drifted.append(f"{e['name']}: 거울이 없다 ({dest.name})")
            elif src.read_bytes() != dest.read_bytes():
                drifted.append(f"{e['name']}: {dest.name} != {src}")
        self.assertEqual(
            [], drifted,
            '거울이 정본과 갈라졌다. **손으로 고치지 마라** — 거울의 유일한 writer 는 '
            '`node packages/api-artifacts/scripts/sync.mjs` 다:\n  ' + '\n  '.join(drifted),
        )


class TheGateItselfRuns(unittest.TestCase):
    """규칙을 다시 적지 않고 SSOT 를 실행해 판정한다."""

    def test_sync_check_exits_zero(self) -> None:
        node = shutil.which('node')
        if node is None:
            self.skipTest('node 가 없다 — 위 두 시험이 같은 질문에 파이썬으로 답한다')
        result = subprocess.run(
            [node, str(SYNC), '--check'],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(
            0, result.returncode,
            'sync.mjs --check 가 거부했다:\n' + (result.stdout + result.stderr),
        )


if __name__ == '__main__':
    unittest.main()
