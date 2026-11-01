"""Statut des faits de profil : « proposed » (extrait d'un CV, à relire) ou « validated ».

Les faits existants ont tous été saisis par l'utilisateur : ils sont validés.

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE profile_facts ADD COLUMN status text NOT NULL DEFAULT 'validated' "
               "CONSTRAINT profile_facts_status CHECK (status IN ('proposed','validated'))")


def downgrade() -> None:
    op.execute("ALTER TABLE profile_facts DROP COLUMN status")
