"""Un seul statut par clé système et par utilisateur : filet de sécurité côté base.

La règle « Envoyée seulement par confirmation » s'appuie sur la clé système `sent`. Cet index
empêche qu'un second statut porte la même clé, même si le code se trompait un jour.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX status_definitions_system_key_unique "
        "ON status_definitions (user_id, system_key) WHERE system_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS status_definitions_system_key_unique")
