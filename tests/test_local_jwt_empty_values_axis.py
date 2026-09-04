"""빈 `local_jwt` 값이 **「정합」으로 읽히면 안 된다**.

⚠️ 실측 2026-09-04(중앙 PC 최초 구축). `deployment_auth_defects` 가 `OK` 를 냈고, 운영자가
그 뒤에 `LOCAL_JWT_ISSUER` 가 platform·headless **양쪽 다 빈 값**인 것을 따로 발견했다.
그대로 재기동했으면 `ValueError: local_jwt auth requires local_jwt_issuer` 로 부팅 거부였다.

**상태가 셋인데 축이 둘이었다:**

===================  ==============================================
도달하지 않는다       봉인이 본다 (`test_auth_mode_pairing.py`)
**도달했으나 비었음**  ⚠️ **아무도 안 봤다** — 이 파일이 그 자리다
도달하고 값이 있다    정상
===================  ==============================================

compose 는 이 필드를 `${FCC_PLATFORM_LOCAL_JWT_ISSUER:-}` 로 넘긴다. **도달은 하므로**
봉인은 만족되고, 짝 검사는 platform 과 headless 를 **상등**으로만 보므로 `'' == ''` 이
「일치」로 통과한다. 두 축 모두 참인데 배포는 뜨지 않는다.

⚠️ **필수 필드 목록을 이 축이 소유하지 않는다.** `LocalJwtConfig.validate` 가 소유하고
그것이 **부팅이 실제로 도는 검증**이다. 여기서 재표현하면 둘이 갈라지는 날 게이트가
「정합」이라고 말하면서 부팅은 거부된다 — 지금 닫는 결함과 같은 모양이다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fcc_test_contracts.common.auth_config import deployment_auth_defects  # noqa: E402
from fcc_test_contracts.common.local_identity import LocalJwtConfig  # noqa: E402

_MODES = dict(
    platform_auth_mode='local_jwt',
    web_auth_mode='local',
    headless_auth_mode='local_jwt',
)


def _config(**overrides) -> LocalJwtConfig:
    base = dict(secret='s' * 32, issuer='http://central/realms/fcc-dev', audience='fcc')
    base.update(overrides)
    return LocalJwtConfig(**base)


class TestEmptyLocalJwtValuesAreNotCoherent(unittest.TestCase):
    def test_a_bootable_configuration_reports_no_defect(self):
        """⚠️ 반대 방향 팔. 이것이 없으면 「전부 결함」으로 퇴화해도 아무도 모른다.

        `.claude/rules/check-axis-blindness.md` §비-공허성: *이 검사가 성공하면 이 팔이
        red 가 되는가?* → 아니오. 부팅 가능한 설정인 한 초록이다.
        """
        self.assertEqual(
            deployment_auth_defects(
                **_MODES,
                local_jwt_configs=[('FCC_PLATFORM_LOCAL_JWT_*', _config())],
            ),
            (),
        )

    def test_each_boot_required_value_is_reported_when_empty(self):
        """빈 값 하나하나가 실제로 결함을 만든다 — 전수."""
        for label, overrides in (
            ('issuer', {'issuer': ''}),
            ('audience', {'audience': ''}),
            ('secret', {'secret': ''}),
        ):
            with self.subTest(field=label):
                defects = deployment_auth_defects(
                    **_MODES,
                    local_jwt_configs=[('FCC_PLATFORM_LOCAL_JWT_*', _config(**overrides))],
                )
                self.assertTrue(
                    defects, f'{label} 가 비었는데 「정합」으로 읽혔다',
                )
                self.assertIn('is not bootable', defects[0])
                self.assertIn('FCC_PLATFORM_LOCAL_JWT_*', defects[0])

    def test_the_reported_reason_is_the_boot_error_itself(self):
        """⚠️ 사유를 이 축이 다시 쓰지 않는다 — 부팅이 내는 문장을 그대로 나른다.

        재표현하면 `LocalJwtConfig.validate` 가 바뀌는 날 게이트의 설명만 낡는다.
        """
        defects = deployment_auth_defects(
            **_MODES,
            local_jwt_configs=[('FCC_PLATFORM_LOCAL_JWT_*', _config(issuer=''))],
        )
        self.assertIn('local_jwt auth requires local_jwt_issuer', defects[0])

    def test_both_surfaces_are_reported_not_just_the_first(self):
        """운영자가 하나만 고치고 다시 막히지 않도록 — 이 함수의 본래 규율이다."""
        defects = deployment_auth_defects(
            **_MODES,
            local_jwt_configs=[
                ('FCC_PLATFORM_LOCAL_JWT_*', _config(issuer='')),
                ('FCC_HEADLESS_LOCAL_JWT_*', _config(audience='')),
            ],
        )
        self.assertEqual(len(defects), 2, defects)
        self.assertIn('FCC_HEADLESS_LOCAL_JWT_*', defects[1])

    def test_not_asking_the_axis_is_not_passing_it(self):
        """``None`` 은 *「이 축은 묻지 않는다」* 이지 *「통과」* 가 아니다 — 함수의 계약."""
        self.assertEqual(deployment_auth_defects(**_MODES), ())

    def test_empty_on_both_surfaces_is_not_read_as_agreement(self):
        """⚠️ **이 결함의 정확한 재현.** 짝 축은 `'' == ''` 를 「일치」로 읽는다."""
        self.assertEqual(
            deployment_auth_defects(**_MODES, local_jwt_secrets=('', '')), (),
            '전제가 바뀌었다 — 짝 축이 빈 값을 이미 잡는다면 이 축의 근거를 다시 써라',
        )
        self.assertTrue(
            deployment_auth_defects(
                **_MODES,
                local_jwt_secrets=('', ''),
                local_jwt_configs=[
                    ('FCC_PLATFORM_LOCAL_JWT_*', _config(secret='', issuer='', audience='')),
                ],
            ),
            '같은 입력을 부팅 검증에 물리면 결함이 나와야 한다',
        )


if __name__ == '__main__':
    unittest.main()
