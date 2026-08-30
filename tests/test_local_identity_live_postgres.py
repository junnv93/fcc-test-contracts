"""D-1 을 **실행으로** 증명한다 — 실 PostgreSQL (계약 M-1, T-6, S-5).

계획서 §2 D-1 은 nullable 신원키를 기각하면서 그 근거를 PostgreSQL 16.14 실측으로
적었다. **관측은 봉인이 아니다** — 이 저장소가 이미 이름 붙인 실패 모드다(memory:
*"observation is not a seal"*). 관측만 하고 테스트로 착지시키지 않으면 변이가 살아남고,
다음 사람이 *"nullable 로 해도 되지 않나"* 라고 물었을 때 답할 실행이 없다.

## ⚠️ SQLite 로는 이것을 증명할 수 없다

SQLite 도 NULL 을 distinct 로 다루지만, 이 축이 묻는 것은 *"우리가 배포하는 그 엔진이
그렇게 동작하는가"* 다. 형제 축이 같은 이유로 같은 결론을 냈다 — 실 PostgreSQL 행 잠금
증명이 SQLite shim 으로 재현 불가였던 것과 같은 형상이고, 그때도 답은 "shim 으로
바꾸자"가 아니라 "DSN 이 있을 때 실제로 돌린다"였다.

## DSN 이 없으면 skip 하고, **사유를 출력한다**

조용히 통과하면 *"증명했다"* 와 *"증명할 수 없었다"* 가 같아 보인다. skip 은 결함이
아니라 설계다 — 다만 그 skip 이 무엇을 확인하지 못했는지 말해야 한다.

    FCC_LOCAL_IDENTITY_PROOF_DB_URL=postgresql://fcc:...@127.0.0.1:5432/fcc_central \\
        python3 -m pytest tests/test_local_identity_live_postgres.py -q
"""
from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_REPO_ROOT / 'src'), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fcc_test_contracts.common.identity import LOCAL_IDENTITY_ISSUER  # noqa: E402


def _partial_index_ddl(table: str):
    """``CREATE UNIQUE INDEX … WHERE issuer = '<sentinel>' …`` for ``table``.

    ⚠️ The predicate is COMPOSED, not parameterised. A partial-index predicate is
    part of the index definition, not a query, so PostgreSQL cannot take a bind
    parameter there — it answers ``IndeterminateDatatype: could not determine data
    type of parameter $1`` (measured). ``psycopg.sql.Literal`` does the quoting, so
    this composes the value rather than formatting it into a string by hand.

    ⚠️ And the value still comes from the CONSTANT, never from a test literal —
    that binding is the whole point of this file.
    """
    from psycopg import sql

    return sql.SQL(
        'CREATE UNIQUE INDEX ON {table} (LOWER(email)) '
        'WHERE issuer = {issuer} AND email IS NOT NULL AND email <> {empty}'
    ).format(
        table=sql.Identifier(table),
        issuer=sql.Literal(LOCAL_IDENTITY_ISSUER),
        empty=sql.Literal(''),
    )

#: 형제 라이브 증명(`FCC_KEYSET_PROOF_DB_URL`)과 같은 형태의 opt-in 환경변수.
ENV_PROOF_DB_URL = 'FCC_LOCAL_IDENTITY_PROOF_DB_URL'

_SKIP_REASON = (
    'D-1 (nullable identity key) NOT PROVEN on this run: '
    f'{ENV_PROOF_DB_URL} is unset, so no live PostgreSQL was reachable. This is a '
    'SKIP, not a PASS — the nullable-vs-sentinel verdict rests on the plan\'s '
    'recorded 16.14 measurement alone until this test actually runs. Set the DSN '
    'against a throwaway database to execute it.'
)


def _connect():
    dsn = os.environ.get(ENV_PROOF_DB_URL, '').strip()
    if not dsn:
        return None
    try:
        import psycopg
    except ImportError:
        return None
    return psycopg.connect(dsn)


class TestNullableIdentityKeysDefeatTheUniqueIndex(unittest.TestCase):
    """계획서 §9 의 증명 SQL — 이제 실행되는 단언으로.

    ⚠️ 모든 작업은 **TEMP 테이블 + 롤백**이다. 이 증명은 운영 중인 중앙 DB 를 향해
    돌 수도 있으므로, 어떤 영속 상태도 만들지 않는 것이 전제다.
    """

    def setUp(self) -> None:
        self.conn = _connect()
        if self.conn is None:
            self.skipTest(_SKIP_REASON)
        self.addCleanup(self._rollback_and_close)

    def _rollback_and_close(self) -> None:
        try:
            self.conn.rollback()
        finally:
            self.conn.close()

    def test_the_engine_is_postgres_and_says_so(self):
        """어느 엔진에서 증명했는지 기록에 남는다."""
        with self.conn.cursor() as cur:
            cur.execute('SELECT version()')
            version = cur.fetchone()[0]
        self.assertIn('PostgreSQL', version)
        print(f'\n[D-1 proof] engine: {version.split(",")[0]}')

    def test_nullable_identity_keys_allow_duplicate_rows(self):
        """**(a) 기각 근거.** ``NULL`` 은 서로 distinct 이므로 유일 인덱스가 로컬
        사용자에게 아무것도 보장하지 않는다 — 같은 이메일로 행이 무한히 생기고,
        그 중 어느 행으로 로그인되는지는 **정의되지 않는다**.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                'CREATE TEMP TABLE probe_nullable '
                '(issuer text, subject text, email text) ON COMMIT DROP'
            )
            cur.execute(
                'CREATE UNIQUE INDEX ON probe_nullable (issuer, subject)'
            )
            cur.execute(
                "INSERT INTO probe_nullable VALUES (NULL, NULL, 'a@x.com')"
            )
            cur.execute(
                "INSERT INTO probe_nullable VALUES (NULL, NULL, 'a@x.com')"
            )
            cur.execute('SELECT count(*) FROM probe_nullable')
            rows = cur.fetchone()[0]
        self.assertEqual(
            rows, 2,
            'the nullable branch did NOT produce duplicates on this engine — the '
            'recorded rationale for choosing a sentinel no longer holds here and '
            'D-1 must be re-argued rather than assumed',
        )

    def test_the_sentinel_identity_key_refuses_the_duplicate(self):
        """**(b) 채택 근거.** 센티넬은 인덱스에 실제로 참여하므로 두 번째가 거부된다."""
        import psycopg

        with self.conn.cursor() as cur:
            cur.execute(
                'CREATE TEMP TABLE probe_sentinel '
                '(issuer text NOT NULL, subject text NOT NULL, email text) '
                'ON COMMIT DROP'
            )
            cur.execute(
                'CREATE UNIQUE INDEX ON probe_sentinel (issuer, subject)'
            )
            cur.execute(
                'INSERT INTO probe_sentinel VALUES (%s, %s, %s)',
                (LOCAL_IDENTITY_ISSUER, 'a@x.com', 'a@x.com'),
            )
            cur.execute('SAVEPOINT sp')
            with self.assertRaises(
                psycopg.errors.UniqueViolation,
                msg='the sentinel branch accepted a duplicate identity — local '
                    'email uniqueness is not actually enforced',
            ):
                cur.execute(
                    'INSERT INTO probe_sentinel VALUES (%s, %s, %s)',
                    (LOCAL_IDENTITY_ISSUER, 'a@x.com', 'a@x.com'),
                )
            cur.execute('ROLLBACK TO sp')
            cur.execute('SELECT count(*) FROM probe_sentinel')
            self.assertEqual(cur.fetchone()[0], 1)

    def test_the_partial_predicate_lets_two_oidc_rows_share_an_email(self):
        """⚠️ 이 축은 계획서에 **없었다** — 부분 조건의 ``issuer = local`` 이 없으면
        같은 이메일을 가진 두 issuer 의 OIDC 행이 서로 충돌해 두 번째 JIT 프로비저닝이
        503 이 된다(계약 M-2 위반). 그 조건이 실제로 그것을 허용하는지 **엔진에게 묻는다**.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                'CREATE TEMP TABLE probe_partial '
                '(issuer text NOT NULL, subject text NOT NULL, email text) '
                'ON COMMIT DROP'
            )
            cur.execute(_partial_index_ddl('probe_partial'))
            # 같은 사람이 Keycloak 과 Azure 양쪽에서 온다 — 정상이고 허용돼야 한다.
            cur.execute(
                'INSERT INTO probe_partial VALUES (%s, %s, %s)',
                ('https://keycloak.internal/realms/fcc', 'kc-sub', 'a@x.com'),
            )
            cur.execute(
                'INSERT INTO probe_partial VALUES (%s, %s, %s)',
                ('https://login.microsoftonline.com/t/v2.0', 'oid-1', 'A@X.com'),
            )
            cur.execute('SELECT count(*) FROM probe_partial')
            self.assertEqual(
                cur.fetchone()[0], 2,
                'the partial index blocked a second OIDC issuer carrying the same '
                'email — that is the Keycloak-to-Azure migration path, and this '
                'wave promises to leave it working',
            )

    def test_the_partial_predicate_still_refuses_two_local_rows(self):
        """그리고 좁히기가 로컬 유일성을 잃지 않았는지 — 반대 방향도 함께 묻는다."""
        import psycopg

        with self.conn.cursor() as cur:
            cur.execute(
                'CREATE TEMP TABLE probe_partial_local '
                '(issuer text NOT NULL, subject text NOT NULL, email text) '
                'ON COMMIT DROP'
            )
            cur.execute(_partial_index_ddl('probe_partial_local'))
            cur.execute(
                'INSERT INTO probe_partial_local VALUES (%s, %s, %s)',
                (LOCAL_IDENTITY_ISSUER, 'a@x.com', 'a@x.com'),
            )
            cur.execute('SAVEPOINT sp2')
            # 대소문자만 다른 두 번째 로컬 행 — LOWER() 인덱스가 잡아야 한다.
            with self.assertRaises(psycopg.errors.UniqueViolation):
                cur.execute(
                    'INSERT INTO probe_partial_local VALUES (%s, %s, %s)',
                    (LOCAL_IDENTITY_ISSUER, 'other', 'A@X.COM'),
                )
            cur.execute('ROLLBACK TO sp2')

    def test_two_email_less_rows_do_not_collide(self):
        """⚠️ ``email IS NOT NULL`` 조건이 빠지면 이메일 클레임을 안 싣는 OIDC 행
        **두 개가 서로** 충돌한다."""
        with self.conn.cursor() as cur:
            cur.execute(
                'CREATE TEMP TABLE probe_empty '
                '(issuer text NOT NULL, subject text NOT NULL, email text) '
                'ON COMMIT DROP'
            )
            cur.execute(_partial_index_ddl('probe_empty'))
            for subject, email in (('s1', None), ('s2', None), ('s3', ''), ('s4', '')):
                cur.execute(
                    'INSERT INTO probe_empty VALUES (%s, %s, %s)',
                    (LOCAL_IDENTITY_ISSUER, subject, email),
                )
            cur.execute('SELECT count(*) FROM probe_empty')
            self.assertEqual(cur.fetchone()[0], 4)


if __name__ == '__main__':
    unittest.main()
