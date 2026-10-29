import re
import secrets
import uuid

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import text

from app import db, seed_demo
from app.create_user import create_user

PASSWORD = "mot-de-passe-de-test-123"  # fictif, uniquement pour les tests


@pytest.fixture
def demo_db(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(32))
    monkeypatch.setenv("ALLOW_DEMO_DATA", "true")
    yield migrated_db
    db._engine(migrated_db).dispose()
    db._engine.cache_clear()


def counts(user_id):
    with db.user_scope(user_id) as conn:
        return {
            table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("job_postings", "analyses", "scores", "applications", "events")
        }


def test_seed_cree_des_donnees_fictives_completes(demo_db):
    user_id = create_user("alice@example.test", PASSWORD)
    assert seed_demo.seed(user_id) == (12, 7)
    assert counts(user_id) == {"job_postings": 12, "analyses": 12, "scores": 12, "applications": 7, "events": 27}
    with db.user_scope(user_id) as conn:
        urls = conn.execute(text("SELECT url FROM job_postings")).scalars().all()
        assert all(re.fullmatch(r"https://jobs\.example\.test/\d+", url) for url in urls)
        values = conn.execute(text("SELECT value, jsonb_array_length(criteria) FROM scores")).all()
        assert all(3 <= v <= 5 and n == 7 for v, n in values)
        statuses = set(conn.execute(text(
            "SELECT s.system_key FROM applications a JOIN status_definitions s ON s.id = a.status_id")).scalars())
        assert len(statuses) >= 5


def test_envoyee_a_sent_at_et_evenement_d_envoi(demo_db):
    user_id = create_user("alice@example.test", PASSWORD)
    seed_demo.seed(user_id)
    with db.user_scope(user_id) as conn:
        rows = conn.execute(text(
            "SELECT a.sent_at, s.system_key, "
            "(SELECT count(*) FROM events e JOIN status_definitions t ON t.id = e.to_status_id "
            " WHERE e.application_id = a.id AND t.system_key = 'sent') AS sent_events "
            "FROM applications a JOIN status_definitions s ON s.id = a.status_id")).all()
    for sent_at, key, sent_events in rows:
        if key in {"abandoned", "to_prepare", "human_review"}:
            assert sent_at is None and sent_events == 0
        else:
            assert sent_at is not None and sent_events == 1


def test_seed_est_idempotent(demo_db):
    user_id = create_user("alice@example.test", PASSWORD)
    seed_demo.seed(user_id)
    before = counts(user_id)
    assert seed_demo.seed(user_id) == (0, 0)
    assert counts(user_id) == before


def test_seed_respecte_la_rls(demo_db):
    alice = create_user("alice@example.test", PASSWORD)
    bob = create_user("bob@example.test", PASSWORD)
    seed_demo.seed(alice)
    assert set(counts(bob).values()) == {0}
    assert counts(alice)["applications"] == 7


def test_main_refuse_sans_autorisation(demo_db, monkeypatch, capsys):
    user_id = create_user("alice@example.test", PASSWORD)
    for value in (None, "false", "oui"):
        if value is None:
            monkeypatch.delenv("ALLOW_DEMO_DATA")
        else:
            monkeypatch.setenv("ALLOW_DEMO_DATA", value)
        assert seed_demo.main(["alice@example.test"]) == 1
        assert "ALLOW_DEMO_DATA" in capsys.readouterr().out
    assert counts(user_id)["job_postings"] == 0


def test_main_par_email_et_compte_inconnu(demo_db, capsys):
    create_user("alice@example.test", PASSWORD)
    assert seed_demo.main(["inconnu@example.test"]) == 1
    assert seed_demo.main([]) == 1
    assert seed_demo.main(["Alice@Example.test"]) == 0
    assert "12 offres, 7 candidatures" in capsys.readouterr().out


def test_role_de_connexion_non_proprietaire_soumis_a_la_rls(demo_db, monkeypatch):
    """Reproduit infra/db/10-roles.sh : login membre de app_rw, sans BYPASSRLS ni propriété des tables."""
    user_id = create_user("alice@example.test", PASSWORD)
    seed_demo.seed(user_id)
    login = f"app_test_{uuid.uuid4().hex[:8]}"
    password = secrets.token_hex(16)
    base = psycopg.conninfo.conninfo_to_dict(demo_db)
    try:
        with psycopg.connect(demo_db, autocommit=True) as admin:
            admin.execute(sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS IN ROLE app_rw"
            ).format(sql.Identifier(login), sql.Literal(password)))
            owner = admin.execute(
                "SELECT tableowner FROM pg_tables WHERE tablename = 'applications'").fetchone()[0]
            assert owner != login
            flags = admin.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", (login,)).fetchone()
            assert flags == (False, False)
        base.update(user=login, password=password)
        with psycopg.connect(**base) as conn:
            conn.execute("SET LOCAL ROLE app_rw")
            # Sans utilisateur courant : aucune ligne visible, malgré les 7 candidatures existantes.
            assert conn.execute("SELECT count(*) FROM applications").fetchone()[0] == 0
            conn.execute("SELECT set_config('app.user_id', %s, true)", (user_id,))
            assert conn.execute("SELECT count(*) FROM applications").fetchone()[0] == 7
            conn.execute("SELECT set_config('app.user_id', %s, true)", (str(uuid.uuid4()),))
            assert conn.execute("SELECT count(*) FROM applications").fetchone()[0] == 0
        with psycopg.connect(**base) as conn:
            # Même sans SET ROLE, le login n'est ni propriétaire ni BYPASSRLS : FORCE RLS s'applique.
            assert conn.execute("SELECT count(*) FROM applications").fetchone()[0] == 0
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("DROP TABLE applications")
    finally:
        with psycopg.connect(demo_db, autocommit=True) as admin:
            admin.execute(f"DROP ROLE IF EXISTS {login}")
