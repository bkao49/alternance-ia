import psycopg
import pytest
from sqlalchemy.exc import DBAPIError
from test_applications import (  # noqa: F401  (fixtures et helpers partagés)
    PASSWORD,
    alice,
    application,
    bob,
    new_application,
    status_ids,
)
from test_database import SEED, as_app

from app.retention import Retention, purge_expired, retention_from_env

DELETE = {"password": PASSWORD, "confirm": True}


def tables_with_owner(conn):
    rows = conn.execute("SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' "
                        "AND column_name = 'user_id'").fetchall()
    return {r[0]: "user_id" for r in rows} | {"users": "id"}


def count_rows(db_url, user_id):
    """Compte les lignes de l'utilisateur dans chaque table. La connexion de test est superutilisateur,
    donc hors RLS ; si elle ne l'était plus, tout vaudrait 0 et la garde « before » échouerait."""
    with psycopg.connect(db_url) as conn:
        every_table = {r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
            "AND table_name <> 'alembic_version'")}
        assert set(tables_with_owner(conn)) == every_table, "table sans user_id : à couvrir par ce test"
        return {table: conn.execute(f"SELECT count(*) FROM {table} WHERE {key} = %s", (user_id,)).fetchone()[0]
                for table, key in tables_with_owner(conn).items()}


def fill_every_table(db_url, api):
    """Une ligne au moins dans chaque table, par le rôle applicatif (SEED de test_database)."""
    ids = {"status_definitions": status_ids(api)["detected"]}
    with psycopg.connect(db_url) as conn:
        as_app(conn, api.user_id)
        for table, sql in SEED:
            if table not in ids and table != "users":
                ids[table] = conn.execute(sql, {"uid": api.user_id, **ids}).fetchone()[0]
        conn.commit()


def test_delete_everything_leaves_no_row_in_any_table(alice, bob, migrated_db):  # noqa: F811
    fill_every_table(migrated_db, alice)
    fill_every_table(migrated_db, bob)
    new_application(alice)
    before = count_rows(migrated_db, alice.user_id)
    assert all(before.values()), f"tables non remplies : {[t for t, n in before.items() if not n]}"

    response = alice.post("/account/delete", DELETE)
    assert response.status_code == 204, response.text
    assert count_rows(migrated_db, alice.user_id) == dict.fromkeys(before, 0)
    assert all(count_rows(migrated_db, bob.user_id).values())  # Bob n'est pas touché
    assert "session" not in alice.client.cookies
    assert alice.get("/auth/me").status_code == 401


def test_wrong_password_deletes_nothing(alice, migrated_db):  # noqa: F811
    before = count_rows(migrated_db, alice.user_id)
    response = alice.post("/account/delete", {"password": "faux-mot-de-passe", "confirm": True})
    assert (response.status_code, response.json()["code"]) == (403, "invalid_password")
    assert count_rows(migrated_db, alice.user_id) == before


@pytest.mark.parametrize("body", [{"password": PASSWORD, "confirm": False}, {"password": PASSWORD},
                                  {"confirm": True}, {**DELETE, "extra": 1}])
def test_deletion_must_be_confirmed(alice, migrated_db, body):  # noqa: F811
    assert alice.post("/account/delete", body).status_code == 422
    assert count_rows(migrated_db, alice.user_id)["users"] == 1


def test_deletion_requires_csrf(alice, migrated_db):  # noqa: F811
    assert alice.client.post("/account/delete", json=DELETE).status_code == 403
    assert count_rows(migrated_db, alice.user_id)["users"] == 1


def test_too_many_wrong_passwords_are_limited(alice):  # noqa: F811
    wrong = {"password": "faux-mot-de-passe", "confirm": True}
    assert [alice.post("/account/delete", wrong).status_code for _ in range(5)] == [403] * 5
    assert alice.post("/account/delete", DELETE).status_code == 429


def add(db_url, user_id, sql, params=()):
    with psycopg.connect(db_url) as conn:
        as_app(conn, user_id)
        cursor = conn.execute(sql, (user_id, *params))
        row = cursor.fetchone() if cursor.description else None
        conn.commit()
        return row[0] if row else None


def offer(db_url, user_id, external_id, days_ago):
    return str(add(db_url, user_id,
                   "INSERT INTO job_postings (user_id, source, external_id, url, title, company, description_text, "
                   "content_hash, detected_at) VALUES (%s, 'test', %s, 'https://exemple.test', 't', 'c', 'd', 'h', "
                   "now() - make_interval(days => %s)) RETURNING id", (external_id, days_ago)))


def test_purge_removes_only_expired_rows_for_every_user(alice, bob, migrated_db):  # noqa: F811
    for api in (alice, bob):
        offer(migrated_db, api.user_id, "ancienne", 200)
        kept = offer(migrated_db, api.user_id, "ancienne-candidature", 200)
        new_application(api, offer_id=kept)
        offer(migrated_db, api.user_id, "recente", 10)
        for days, digest in ((100, "vieux"), (5, "neuf")):
            add(migrated_db, api.user_id, "INSERT INTO llm_calls (user_id, provider, model, purpose, input_hash, "
                "created_at) VALUES (%s, 'fake', 'm', 'test', %s, now() - make_interval(days => %s))",
                (digest, days))
            add(migrated_db, api.user_id, "INSERT INTO llm_cache (user_id, input_hash, response_text, created_at) "
                "VALUES (%s, %s, 'r', now() - make_interval(days => %s))", (digest, days))

    assert purge_expired(Retention(offers_days=180, llm_days=90)) == {
        "job_postings": 2, "llm_calls": 2, "llm_cache": 2}
    with psycopg.connect(migrated_db) as conn:
        offers = sorted(r[0] for r in conn.execute("SELECT external_id FROM job_postings"))
        assert offers == ["ancienne-candidature", "ancienne-candidature", "recente", "recente"]
        assert conn.execute("SELECT DISTINCT input_hash FROM llm_calls").fetchall() == [("neuf",)]
        assert conn.execute("SELECT DISTINCT input_hash FROM llm_cache").fetchall() == [("neuf",)]


def test_retention_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("RETENTION_OFFERS_DAYS", "30")
    monkeypatch.delenv("RETENTION_LLM_DAYS", raising=False)
    assert retention_from_env() == Retention(offers_days=30, llm_days=90)
    for bad in ("0", "29", "abc", "100000"):
        monkeypatch.setenv("RETENTION_LLM_DAYS", bad)
        with pytest.raises(RuntimeError):
            retention_from_env()


def test_application_role_cannot_trigger_a_purge(alice, bob, migrated_db):  # noqa: F811
    offer(migrated_db, bob.user_id, "ancienne", 400)
    with psycopg.connect(migrated_db) as conn:
        as_app(conn, alice.user_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM purge_expired_data(30, 30)")
    assert count_rows(migrated_db, bob.user_id)["job_postings"] == 1


def test_purge_refuses_too_short_durations(migrated_db):
    with pytest.raises(DBAPIError, match="trop courte"):
        purge_expired(Retention(offers_days=1, llm_days=1))


def test_purger_reads_no_content(migrated_db):
    with psycopg.connect(migrated_db) as conn:
        for table, column in (("llm_cache", "response_text"), ("job_postings", "description_text"),
                              ("users", "email"), ("profile_facts", "text")):
            assert not conn.execute("SELECT has_column_privilege('retention_purger', %s, %s, 'SELECT')",
                                    (table, column)).fetchone()[0], (table, column)
