"""Pages carrières saisies par chaque utilisateur pour le robot web (source « web »).

Une ligne par page, sous RLS. Le nombre de pages est limité par l'API (10) ; la base borne la longueur.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE web_pages (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        position smallint NOT NULL CHECK (position >= 0),
        url text NOT NULL CHECK (length(url) <= 2000 AND url ~ '^https?://'),
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (user_id, url),
        UNIQUE (user_id, position) DEFERRABLE INITIALLY DEFERRED)"""
    )
    op.execute("ALTER TABLE web_pages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE web_pages FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY web_pages_isolation ON web_pages "
        "USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid) "
        "WITH CHECK (user_id = nullif(current_setting('app.user_id', true), '')::uuid)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON web_pages TO app_rw")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS web_pages")
