"""Contraintes des faits de profil, alignées sur le contrat (`/profile/facts`).

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

KINDS = "('experience','education','project','skill','certification','language','other')"
CHECKS = {
    "profile_facts_kind": f"kind IN {KINDS}",
    "profile_facts_text_length": "length(text) BETWEEN 1 AND 1000",
    "profile_facts_dates": "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
    "profile_facts_technologies": "cardinality(technologies) <= 30",
    "profile_facts_source_length": "length(source) <= 120",
}


# Remise en conformité des lignes existantes, sans rien perdre d'essentiel : sinon une seule ligne
# hors règle bloquerait toute la migration au déploiement.
CLEANUP = [
    f"UPDATE profile_facts SET kind = 'other' WHERE kind NOT IN {KINDS}",
    "UPDATE profile_facts SET text = left(text, 1000) WHERE length(text) > 1000",
    "UPDATE profile_facts SET end_date = NULL WHERE end_date < start_date",
    "UPDATE profile_facts SET technologies = technologies[1:30] WHERE cardinality(technologies) > 30",
    "UPDATE profile_facts SET source = left(source, 120) WHERE length(source) > 120",
]


def upgrade() -> None:
    for statement in CLEANUP:
        op.execute(statement)
    for name, condition in CHECKS.items():
        op.execute(f"ALTER TABLE profile_facts ADD CONSTRAINT {name} CHECK ({condition})")
    op.execute("CREATE INDEX profile_facts_user ON profile_facts (user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS profile_facts_user")
    for name in CHECKS:
        op.execute(f"ALTER TABLE profile_facts DROP CONSTRAINT IF EXISTS {name}")
