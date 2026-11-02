"""Brouillons de CV et de lettres, et leurs versions successives (issue #21).

Un brouillon par utilisateur, type et offre (ou sans offre : CV général). Chaque enregistrement est une
nouvelle ligne de `document_versions` : l'historique n'est jamais réécrit. Le texte est du JSON
`[{section, bullets:[{texte, fact_ids}]}]` ; le contrôle factuel est refait à la lecture, jamais stocké.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

OWN = "user_id = nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""CREATE TABLE document_drafts (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind text NOT NULL CHECK (kind IN ('cv','cover_letter')),
        job_posting_id uuid,
        current_version integer NOT NULL DEFAULT 1 CHECK (current_version >= 1),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CHECK (kind = 'cv' OR job_posting_id IS NOT NULL),
        UNIQUE (user_id, id),
        FOREIGN KEY (user_id, job_posting_id) REFERENCES job_postings (user_id, id) ON DELETE CASCADE)""")
    op.execute("CREATE UNIQUE INDEX document_drafts_target ON document_drafts "
               "(user_id, kind, COALESCE(job_posting_id, '00000000-0000-0000-0000-000000000000'::uuid))")
    op.execute("""CREATE TABLE document_versions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        draft_id uuid NOT NULL,
        number integer NOT NULL CHECK (number >= 1),
        origin text NOT NULL CHECK (origin IN ('generated','edited','restored')),
        content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'array' AND pg_column_size(content) <= 2000000),
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (draft_id, number),
        FOREIGN KEY (user_id, draft_id) REFERENCES document_drafts (user_id, id) ON DELETE CASCADE)""")
    for table in ("document_drafts", "document_versions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_isolation ON {table} USING ({OWN}) WITH CHECK ({OWN})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rw")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_versions")
    op.execute("DROP TABLE IF EXISTS document_drafts")
