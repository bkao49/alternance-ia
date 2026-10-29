import uuid

import psycopg
import pytest
from alembic import command
from psycopg import errors

EXPECTED_TABLES = {
    "users", "profile_facts", "job_postings", "analyses", "scores", "applications",
    "status_definitions", "events", "tasks", "llm_calls",
}


def public_tables(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
    ).fetchall()
    return {r[0] for r in rows}


def test_migration_is_reversible(migrated_db, alembic_config):
    with psycopg.connect(migrated_db) as conn:
        assert public_tables(conn) == EXPECTED_TABLES
    command.downgrade(alembic_config, "base")
    with psycopg.connect(migrated_db) as conn:
        assert public_tables(conn) == set()
    command.upgrade(alembic_config, "head")
    with psycopg.connect(migrated_db) as conn:
        assert public_tables(conn) == EXPECTED_TABLES


def test_pgvector_is_installed(migrated_db):
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
        assert row is not None


def test_every_table_has_user_scope_and_forced_rls(migrated_db):
    with psycopg.connect(migrated_db) as conn:
        for table in EXPECTED_TABLES:
            column = "id" if table == "users" else "user_id"
            has_column = conn.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s AND is_nullable = 'NO'",
                (table, column),
            ).fetchone()
            assert has_column, f"{table}.{column} manquant ou nullable"
            rls = conn.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                (table,),
            ).fetchone()
            assert rls == (True, True), f"RLS non forcée sur {table}"


def as_user(conn, user_id):
    """Se comporte comme l'application : rôle sans privilège spécial + utilisateur courant."""
    conn.execute("SET ROLE app_rw")
    conn.execute("SELECT set_config('app.user_id', %s, false)", (str(user_id) if user_id else "",))


def create_user(conn, user_id, email):
    as_user(conn, user_id)
    conn.execute(
        "INSERT INTO users (id, email, password_hash) VALUES (%s, %s, 'x')", (user_id, email)
    )
    conn.execute(
        "INSERT INTO status_definitions (user_id, name, position) VALUES (%s, 'Détectée', 1)",
        (user_id,),
    )
    conn.commit()


def test_a_user_cannot_read_or_write_another_users_rows(migrated_db):
    alice, bob = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(migrated_db) as conn:
        create_user(conn, alice, "alice@example.test")
        create_user(conn, bob, "bob@example.test")

        as_user(conn, alice)
        assert conn.execute("SELECT count(*) FROM status_definitions").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        conn.execute("UPDATE status_definitions SET name = 'piraté' WHERE user_id = %s", (bob,))
        assert conn.execute("SELECT count(*) FROM status_definitions WHERE name = 'piraté'").fetchone()[0] == 0

        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO status_definitions (user_id, name, position) VALUES (%s, 'x', 2)",
                (bob,),
            )


def test_without_current_user_nothing_is_visible(migrated_db):
    alice = uuid.uuid4()
    with psycopg.connect(migrated_db) as conn:
        create_user(conn, alice, "alice@example.test")
        as_user(conn, None)
        for table in EXPECTED_TABLES:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
