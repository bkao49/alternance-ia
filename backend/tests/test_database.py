import uuid

import psycopg
import pytest
from alembic import command
from psycopg import errors

EXPECTED_TABLES = {
    "users", "profile_facts", "job_postings", "analyses", "scores", "applications",
    "status_definitions", "events", "tasks", "llm_calls", "search_preferences",
    "llm_cache",
}
# Journal du plafond de coût : l'application ne peut pas en supprimer de lignes (migration 0005).
APPEND_ONLY = {"llm_calls"}

# Une insertion par table, dans l'ordre des dépendances. %(uid)s est le propriétaire de la ligne ;
# les identifiants des tables déjà insérées sont passés par nom de table (ex. %(job_postings)s).
SEED = [
    ("users", ("INSERT INTO users (id, email, password_hash) "
              "VALUES (%(uid)s, %(uid)s::text || '@example.test', 'x') RETURNING id")),
    ("status_definitions", ("INSERT INTO status_definitions (user_id, name, position) "
                           "VALUES (%(uid)s, 'Détectée', 1) RETURNING id")),
    ("profile_facts", ("INSERT INTO profile_facts (user_id, kind, text) "
                      "VALUES (%(uid)s, 'skill', 'Python') RETURNING id")),
    ("job_postings", ("INSERT INTO job_postings (user_id, source, external_id, url, title, company, "
                     "description_text, content_hash) VALUES (%(uid)s, 's', 'e1', 'https://x.test', "
                     "'t', 'c', 'd', 'h') RETURNING id")),
    ("analyses", ("INSERT INTO analyses (user_id, job_posting_id, extraction, prompt_version) "
                 "VALUES (%(uid)s, %(job_postings)s, '{}', 'v1') RETURNING id")),
    ("scores", ("INSERT INTO scores (user_id, job_posting_id, analysis_id, value, confidence) "
               "VALUES (%(uid)s, %(job_postings)s, %(analyses)s, 3.5, 'low') RETURNING id")),
    ("applications", ("INSERT INTO applications (user_id, job_posting_id, status_id) "
                     "VALUES (%(uid)s, %(job_postings)s, %(status_definitions)s) RETURNING id")),
    ("events", ("INSERT INTO events (user_id, application_id, to_status_id, actor) "
               "VALUES (%(uid)s, %(applications)s, %(status_definitions)s, 'user') RETURNING id")),
    ("tasks", ("INSERT INTO tasks (user_id, application_id, reason) "
              "VALUES (%(uid)s, %(applications)s, 'r') RETURNING id")),
    ("llm_calls", ("INSERT INTO llm_calls (user_id, provider, model, purpose, input_hash) "
                  "VALUES (%(uid)s, 'p', 'm', 'extraction', 'h') RETURNING id")),
    ("search_preferences", ("INSERT INTO search_preferences (user_id, keywords) "
                           "VALUES (%(uid)s, '{data}') RETURNING user_id")),
    ("llm_cache", ("INSERT INTO llm_cache (user_id, input_hash, response_text) "
                  "VALUES (%(uid)s, 'h', 'r') RETURNING user_id")),
]


def public_tables(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
    ).fetchall()
    return {r[0] for r in rows}


def as_app(conn, user_id):
    """Se comporte comme l'application : rôle sans privilège spécial + utilisateur courant."""
    conn.execute("RESET ROLE")
    conn.execute("SET ROLE app_rw")
    conn.execute("SELECT set_config('app.user_id', %s, false)", (str(user_id),))


def seed(conn, uid):
    ids = {}
    for table, sql in SEED:
        ids[table] = conn.execute(sql, {"uid": uid, **ids}).fetchone()[0]
    return ids


@pytest.fixture
def two_users(migrated_db):
    alice, bob = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(migrated_db) as conn:
        as_app(conn, alice)
        alice_ids = seed(conn, alice)
        as_app(conn, bob)
        bob_ids = seed(conn, bob)
        conn.commit()
        yield conn, alice, bob, alice_ids, bob_ids


def test_migration_is_reversible(migrated_db, alembic_config):
    with psycopg.connect(migrated_db) as conn:
        assert public_tables(conn) == EXPECTED_TABLES
    command.downgrade(alembic_config, "base")
    with psycopg.connect(migrated_db) as conn:
        assert public_tables(conn) == set()
    command.upgrade(alembic_config, "head")
    with psycopg.connect(migrated_db) as conn:
        assert public_tables(conn) == EXPECTED_TABLES


def test_a_user_cannot_have_two_statuses_with_the_same_system_key(two_users):
    conn, alice, *_ = two_users
    as_app(conn, alice)
    insert = "INSERT INTO status_definitions (user_id, name, position, system_key) VALUES (%s, %s, 9, 'sent')"
    conn.execute(insert, (alice, "Envoyée 1"))
    with pytest.raises(errors.UniqueViolation):
        conn.execute(insert, (alice, "Envoyée 2"))
    conn.rollback()
    as_app(conn, alice)
    conn.execute("INSERT INTO status_definitions (user_id, name, position) VALUES (%s, 'Libre 1', 10)", (alice,))
    conn.execute("INSERT INTO status_definitions (user_id, name, position) VALUES (%s, 'Libre 2', 11)", (alice,))
    # sans clé système, plusieurs statuts personnalisés restent possibles


def test_pgvector_is_installed(migrated_db):
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()


def test_seed_covers_every_table():
    assert {table for table, _ in SEED} == EXPECTED_TABLES


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_table_is_scoped_by_user_with_forced_rls_and_policy(migrated_db, table):
    column = "id" if table == "users" else "user_id"
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s AND is_nullable = 'NO'", (table, column),
        ).fetchone(), f"{table}.{column} manquant ou nullable"
        assert conn.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s", (table,)
        ).fetchone() == (True, True)
        policy = conn.execute(
            "SELECT qual, with_check FROM pg_policies WHERE tablename = %s AND policyname = %s",
            (table, f"{table}_isolation"),
        ).fetchone()
        assert policy and policy[0] and policy[1], f"politique USING / WITH CHECK absente sur {table}"


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_user_sees_and_deletes_only_own_rows(two_users, table):
    conn, alice, bob, _, _ = two_users
    key = "id" if table == "users" else "user_id"
    as_app(conn, alice)
    assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
    if table in APPEND_ONLY:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(f"DELETE FROM {table} WHERE {key} = %s", (bob,))
    else:
        assert conn.execute(f"DELETE FROM {table} WHERE {key} = %s", (bob,)).rowcount == 0
    conn.rollback()
    as_app(conn, bob)
    assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_user_cannot_insert_a_row_for_another_user(two_users, table):
    conn, alice, bob, _, bob_ids = two_users
    as_app(conn, alice)
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute(dict(SEED)[table], {"uid": bob, **bob_ids})
    conn.rollback()


def test_user_cannot_link_own_rows_to_another_users_rows(two_users):
    conn, alice, _bob, alice_ids, bob_ids = two_users
    as_app(conn, alice)
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO applications (user_id, job_posting_id, status_id) VALUES (%s, %s, %s)",
            (alice, alice_ids["job_postings"], bob_ids["status_definitions"]),
        )
    conn.rollback()
    as_app(conn, alice)
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO tasks (user_id, application_id, reason) VALUES (%s, %s, 'r')",
            (alice, bob_ids["applications"]),
        )
    conn.rollback()


def test_without_current_user_nothing_is_visible_even_with_data(two_users):
    conn, *_ = two_users
    conn.execute("RESET ROLE")
    conn.execute("SET ROLE app_rw")
    conn.execute("RESET app.user_id")
    for table in EXPECTED_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    conn.execute("SELECT set_config('app.user_id', '', false)")
    for table in EXPECTED_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table


def test_invalid_user_id_fails_closed(two_users):
    conn, *_ = two_users
    conn.execute("RESET ROLE")
    conn.execute("SET ROLE app_rw")
    conn.execute("SELECT set_config('app.user_id', 'pas-un-uuid', false)")
    with pytest.raises(errors.InvalidTextRepresentation):
        conn.execute("SELECT count(*) FROM users")
    conn.rollback()
