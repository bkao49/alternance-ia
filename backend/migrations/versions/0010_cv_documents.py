"""Dépôt de CV : le fichier (un seul par utilisateur), le journal des dépôts pour le quota, le lien des faits.

Le fichier est gardé dans la base (colonne bytea) et non sur le disque : il n'est donc jamais dans un
dossier servi, aucun nom de fichier ne sert de chemin, la Row Level Security le protège comme le reste
et il disparaît avec le compte (ON DELETE CASCADE).

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

MAX_BYTES = 5 * 1024 * 1024
OWN = "user_id = nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute(f"""CREATE TABLE cv_documents (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        original_name text NOT NULL CHECK (length(original_name) BETWEEN 1 AND 120),
        file_type text NOT NULL CHECK (file_type IN ('pdf','docx')),
        size_bytes integer NOT NULL CHECK (size_bytes BETWEEN 1 AND {MAX_BYTES}),
        content bytea NOT NULL CHECK (octet_length(content) = size_bytes),
        status text NOT NULL DEFAULT 'processing' CHECK (status IN ('processing','done','failed')),
        error_code text CHECK (error_code IN ('encrypted','too_many_pages','no_text','timeout','unreadable')),
        facts_proposed integer NOT NULL DEFAULT 0 CHECK (facts_proposed >= 0),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (user_id, id))""")
    op.execute("""CREATE TABLE cv_uploads (
        id bigserial PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("CREATE INDEX cv_uploads_user_created ON cv_uploads (user_id, created_at)")
    op.execute("ALTER TABLE profile_facts ADD COLUMN cv_document_id uuid")
    op.execute("ALTER TABLE profile_facts ADD CONSTRAINT profile_facts_cv FOREIGN KEY (user_id, cv_document_id) "
               "REFERENCES cv_documents (user_id, id) ON DELETE CASCADE")
    op.execute("CREATE INDEX profile_facts_cv ON profile_facts (cv_document_id)")
    for table in ("cv_documents", "cv_uploads"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_isolation ON {table} USING ({OWN}) WITH CHECK ({OWN})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rw")
    op.execute("GRANT USAGE ON SEQUENCE cv_uploads_id_seq TO app_rw")


def downgrade() -> None:
    op.execute("ALTER TABLE profile_facts DROP CONSTRAINT IF EXISTS profile_facts_cv")
    op.execute("DROP INDEX IF EXISTS profile_facts_cv")
    op.execute("ALTER TABLE profile_facts DROP COLUMN IF EXISTS cv_document_id")
    op.execute("DROP TABLE IF EXISTS cv_uploads")
    op.execute("DROP TABLE IF EXISTS cv_documents")
