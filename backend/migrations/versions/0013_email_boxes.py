"""Boîte e-mail dédiée aux alertes, une par utilisateur (source « email »).

Le mot de passe d'application est chiffré (Fernet, clé dérivée de SECRET_KEY, ADR 0012) : la base ne
contient jamais le mot de passe en clair. Sous RLS comme toutes les tables de l'utilisateur.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE email_boxes (
        user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        host text NOT NULL CHECK (length(host) BETWEEN 1 AND 253),
        port integer NOT NULL DEFAULT 993 CHECK (port BETWEEN 1 AND 65535),
        username text NOT NULL CHECK (length(username) BETWEEN 1 AND 254),
        password_enc text NOT NULL CHECK (length(password_enc) BETWEEN 1 AND 2000),
        folder text NOT NULL DEFAULT 'INBOX' CHECK (length(folder) BETWEEN 1 AND 100),
        updated_at timestamptz NOT NULL DEFAULT now(),
        last_test_at timestamptz,
        last_test_ok boolean,
        last_test_error text CHECK (length(last_test_error) <= 200))"""
    )
    op.execute("ALTER TABLE email_boxes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE email_boxes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY email_boxes_isolation ON email_boxes "
        "USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid) "
        "WITH CHECK (user_id = nullif(current_setting('app.user_id', true), '')::uuid)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON email_boxes TO app_rw")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS email_boxes")
