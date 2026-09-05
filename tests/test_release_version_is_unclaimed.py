"""선언한 버전 번호를 **다른 배송이 이미 가져가지 않았는가** (2026-09-05).

**왜 이 봉인이 있는가 — 실측 2026-09-05.** 두 배송(PR #28 · #29)이 각자 독립적으로
`0.1.18 → 0.1.19` 로 올렸다. 두 브랜치가 **같은 줄**을 썼으므로 git 은 깨끗이 병합했고
**아무 게이트도 붉지 않았다** — 버전 충돌은 병합 충돌과 모양이 다르다.

먼저 머지된 쪽이 `v0.1.19` 를 자기 머지 커밋에 붙여 push 했고, 그래서 그 태그에는 나중에
머지된 변경이 **들어 있지 않다.** 소비 레인이 그 번호로 pin 하면 받는 것은 자기가
기대한 것이 아니다 — 그리고 그 상태는 「pin 이 맞다」와 **같은 모양**이다.

⭐ **이 봉인이 묻는 것은 「태그가 있는가」가 아니다.** 그렇게 물으면 이 저장소의 두 배포판
중 하나가 항상 빨갛다: `fcc-test-kernel` 은 자기 트리가 안 바뀐 동안 같은 번호를 유지하고,
그 태그는 이후의 (자기와 무관한) 커밋을 당연히 담지 않는다.

묻는 것은 **「그 태그가 이 배포판의 변경을 전부 담았는가」**다:

    git log <tag>..HEAD -- <이 배포판의 트리>   가 비어 있어야 한다

* 태그가 없다 → 아직 아무도 그 번호를 안 썼다. 초록.
* 태그가 있고 그 트리에 새 커밋이 없다 → 같은 내용에 같은 번호다. 초록.
* 태그가 있는데 그 트리에 새 커밋이 있다 → **그 번호는 이미 다른 내용을 뜻한다.** red.

⚠️ 「이 배포판의 트리」를 손으로 적지 않는다. `fcc_test_contracts.common.supply_closure`
가 `pyproject.toml` 에서 파생한 배포판 정의를 그대로 쓴다 — 목록을 적어 두는 순간 그
목록이 다음에 낡을 자리가 된다.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest

from fcc_test_contracts.common.supply_closure import discover_distributions


PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: 배포판 → 그 릴리스 축의 태그 접두사. **원장**이고 정확한 일치를 요구한다.
#:
#: ⚠️ 이 대응은 파생할 수 없다 — 태그 이름 규약은 기계가 읽을 수 있는 곳에 선언돼 있지
#: 않다. 그래서 적되, 아래 `test_every_release_line_is_recorded` 가 **저장소가 실제로 든
#: 접두사 집합**과 양방향으로 대조한다: 새 릴리스 축이 생기면 red, 사라져도 red.
_TAG_PREFIXES = {
    'fcc-test-contracts': 'v',
    'fcc-test-kernel': 'kernel-v',
}

_VERSION_TAG = re.compile(r'^(?P<prefix>.*?)(?P<version>\d+\.\d+\.\d+)$')


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git', '-C', str(PROJECT_ROOT), *args], capture_output=True, text=True,
    )


def _tags() -> list[str]:
    completed = _git('tag', '--list')
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


class _TagBearingCheckout(unittest.TestCase):
    """⚠️ **태그가 하나도 안 보이면 통과가 아니라 skip 이다.**

    얕은 체크아웃(`fetch-depth: 1`, 태그 미포함)에서는 「그 번호는 아무도 안 썼다」와
    「여기서는 태그가 안 보인다」가 같은 값이 된다. 그 둘을 구별하지 않으면 이 봉인은
    가장 필요한 자리(CI)에서 조용히 꺼진다.
    """

    @classmethod
    def setUpClass(cls):
        if not (PROJECT_ROOT / '.git').exists():
            raise unittest.SkipTest(
                '이 트리에 .git 이 없다 — 배송된 상자다. 릴리스 번호 판정은 저장소의 축이다.'
            )
        cls.tags = _tags()
        if not cls.tags:
            raise unittest.SkipTest(
                '태그가 하나도 보이지 않는다(얕은 체크아웃일 수 있다) — 이 축을 잴 수 없다. '
                '통과가 아니다. CI 라면 `fetch-depth: 0` 또는 `fetch tags` 가 필요하다.'
            )
        cls.distributions = {d.name: d for d in discover_distributions(PROJECT_ROOT)}


class TestEveryReleaseLineIsRecorded(_TagBearingCheckout):
    def test_the_observed_tag_prefixes_match_the_ledger(self):
        """릴리스 축의 원장 — 새 축이 조용히 생기거나 사라지지 않게 한다."""
        observed = set()
        for tag in self.tags:
            match = _VERSION_TAG.match(tag)
            if match:
                observed.add(match.group('prefix'))
        self.assertEqual(
            observed, set(_TAG_PREFIXES.values()),
            f'이 저장소가 든 릴리스 축(태그 접두사)이 원장과 다르다. 관측 {sorted(observed)}, '
            f'원장 {sorted(set(_TAG_PREFIXES.values()))}. 새 축이 생겼으면 어느 배포판의 '
            '것인지 원장에 적고, 사라졌으면 그 배포판의 번호를 이제 아무도 안 지킨다는 뜻이다.',
        )

    def test_every_distribution_has_a_release_line(self):
        self.assertEqual(
            set(self.distributions), set(_TAG_PREFIXES),
            '배포판 집합과 릴리스 축 원장이 어긋난다 — 태그 축이 없는 배포판은 소비 레인이 '
            'pin 할 이름이 없고, 배포판 없는 축은 아무것도 봉인하지 않는다.',
        )


class TestTheDeclaredVersionIsNotAlreadyClaimed(_TagBearingCheckout):
    def test_no_distribution_reuses_a_tag_that_lacks_its_changes(self):
        offenders: list[str] = []
        for name, prefix in sorted(_TAG_PREFIXES.items()):
            distribution = self.distributions.get(name)
            if distribution is None:  # 위 시험이 이미 red 다
                continue
            version = _declared_version(distribution.pyproject_path)
            tag = f'{prefix}{version}'
            if tag not in self.tags:
                continue  # 아직 아무도 그 번호를 안 썼다

            # ⚠️ 「이 배포판의 트리」는 파생이다 — 실리는 패키지 + 최상위 모듈 + 자기 선언.
            paths = [
                str(p.relative_to(PROJECT_ROOT))
                for p in (*distribution.package_roots, *distribution.module_files)
            ]
            paths.append(str(distribution.pyproject_path.relative_to(PROJECT_ROOT)))
            completed = _git('log', '--oneline', f'{tag}..HEAD', '--', *paths)
            if completed.returncode != 0:  # pragma: no cover — 태그 객체 문제
                offenders.append(f'  · {name}: {tag} 를 읽지 못했다 — {completed.stderr.strip()}')
                continue
            newer = [line for line in completed.stdout.splitlines() if line.strip()]
            if newer:
                offenders.append(
                    f'  · {name} 이 {version!r} 을 선언하는데 {tag} 는 그 이후 이 배포판의 '
                    f'변경 {len(newer)}건을 담지 않는다:\n'
                    + '\n'.join(f'      {line}' for line in newer[:5])
                )

        self.assertEqual(
            offenders, [],
            '선언한 버전 번호를 **다른 배송이 이미 가져갔다**:\n' + '\n'.join(offenders)
            + '\n\n고치는 법: 번호를 올려라. ⚠️ 태그를 옮기지 마라 — 이미 그 이름으로 설치한 '
            '소비자가 있고, 같은 이름이 다른 내용을 뜻하게 되는 것이 이 봉인이 막으려는 바로 '
            '그 상태다. 실측 2026-09-05: 두 배송이 같은 줄을 써서 git 이 깨끗이 병합했고, '
            '먼저 머지된 쪽의 태그에 나중 변경이 들어 있지 않았다.',
        )


def _declared_version(pyproject_path: Path) -> str:
    import tomllib
    return tomllib.loads(pyproject_path.read_text(encoding='utf-8'))['project']['version']


if __name__ == '__main__':
    unittest.main()
