"""Schéma initial : 10 tables, user_id partout, Row Level Security, pgvector.

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Ordre de création (les clés étrangères pointent vers les tables précédentes).
TABLES = [
    "profile_facts", "job_postings", "status_definitions", "analyses", "scores",
    "applications", "events", "tasks", "llm_calls",
]

# user_id est toujours une clé étrangère vers users et la clé de filtrage RLS.
UID = "user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE"


def fk(column: str, parent: str, on_delete: str = "") -> str:
    """Clé étrangère composite (user_id, colonne) : interdit de pointer vers la ligne d'un autre
    utilisateur. PostgreSQL vérifie les clés étrangères hors RLS, donc user_id doit en faire partie."""
    return f"FOREIGN KEY (user_id, {column}) REFERENCES {parent} (user_id, id) {on_delete}"

DDL = [
    """CREATE TABLE users (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        email text NOT NULL UNIQUE,
        password_hash text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now())""",
    f"""CREATE TABLE profile_facts (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), {UID},
        kind text NOT NULL, text text NOT NULL,
        start_date date, end_date date, technologies text[] NOT NULL DEFAULT '{{}}',
        source text, created_at timestamptz NOT NULL DEFAULT now())""",
    f"""CREATE TABLE job_postings (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), {UID},
        source text NOT NULL, external_id text NOT NULL, url text NOT NULL,
        title text NOT NULL, company text NOT NULL, location text,
        description_text text NOT NULL, content_hash text NOT NULL,
        detected_at timestamptz NOT NULL DEFAULT now(), expired boolean NOT NULL DEFAULT false,
        UNIQUE (user_id, source, external_id), UNIQUE (user_id, id))""",
    f"""CREATE TABLE status_definitions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), {UID},
        name text NOT NULL, position integer NOT NULL, color text NOT NULL DEFAULT '#4f46e5',
        system_key text, UNIQUE (user_id, name), UNIQUE (user_id, id))""",
    f"""CREATE TABLE analyses (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), {UID},
        job_posting_id uuid NOT NULL,
        extraction jsonb NOT NULL, prompt_version text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        {fk("job_posting_id", "job_postings", "ON DELETE CASCADE")}, UNIQUE (user_id, id))""",
    f"""CREATE TABLE scores (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), {UID},
        job_posting_id uuid NOT NULL, analysis_id uuid,
        value numeric(3,2) NOT NULL CHECK (value BETWEEN 0 AND 5),
        confidence text NOT NULL CHECK (confidence IN ('low','medium','high')),
        explanation text, criteria jsonb NOT NULL DEFAULT '[]',
        blocking_reasons jsonb NOT NULL DEFAULT '[]',
        created_at timestamptz NOT NULL DEFAULT now(),
        {fk("job_posting_id", "job_postings", "ON DELETE CASCADE")},
        {fk("analysis_id", "analyses", "ON DELETE SET NULL (analysis_id)")})""",
    f"""CREATE TABLE applications (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), {UID},
        job_posting_id uuid, company text, title text,
        status_id uuid NOT NULL,
        notes text, sent_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        {fk("job_posting_id", "job_postings", "ON DELETE SET NULL (job_posting_id)")},
        {fk("status_id", "status_definitions")}, UNIQUE (user_id, id))""",
    f"""CREATE TABLE events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), {UID},
        application_id uuid NOT NULL, from_status_id uuid, to_status_id uuid NOT NULL,
        actor text NOT NULL CHECK (actor IN ('user','system')), comment text,
        occurred_at timestamptz NOT NULL DEFAULT now(),
        {fk("application_id", "applications", "ON DELETE CASCADE")},
        {fk("from_status_id", "status_definitions")}, {fk("to_status_id", "status_definitions")})""",
    f"""CREATE TABLE tasks (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), {UID},
        application_id uuid NOT NULL,
        state text NOT NULL DEFAULT 'open' CHECK (state IN ('open','done')),
        reason text NOT NULL, remaining_steps jsonb NOT NULL DEFAULT '[]',
        created_at timestamptz NOT NULL DEFAULT now(),
        {fk("application_id", "applications", "ON DELETE CASCADE")})""",
    f"""CREATE TABLE llm_calls (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), {UID},
        provider text NOT NULL, model text NOT NULL, purpose text NOT NULL,
        input_tokens integer NOT NULL DEFAULT 0, output_tokens integer NOT NULL DEFAULT 0,
        cost_eur numeric(10,6) NOT NULL DEFAULT 0, cache_hit boolean NOT NULL DEFAULT false,
        input_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())""",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for statement in DDL:
        op.execute(statement)
    # Le rôle app_rw est global au cluster : on ne le supprime donc pas au downgrade.
    # Rôle utilisé par l'application : pas propriétaire des tables, pas BYPASSRLS,
    # donc soumis aux politiques. La connexion applicative doit en être membre.
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') "
        "THEN CREATE ROLE app_rw NOLOGIN; END IF; END $$"
    )
    for table in ["users", *TABLES]:
        key = "id" if table == "users" else "user_id"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # Sans app.user_id défini, current_setting renvoie NULL : aucune ligne visible.
        op.execute(
            f"CREATE POLICY {table}_isolation ON {table} "
            f"USING ({key} = nullif(current_setting('app.user_id', true), '')::uuid) "
            f"WITH CHECK ({key} = nullif(current_setting('app.user_id', true), '')::uuid)"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rw")


def downgrade() -> None:
    for table in reversed(["users", *TABLES]):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
