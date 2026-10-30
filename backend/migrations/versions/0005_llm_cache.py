"""Cache des réponses LLM (par utilisateur, sous RLS) et index du plafond de coût journalier.

Le cache n'est jamais partagé entre utilisateurs : la réponse est stockée pseudonymisée, telle que
reçue du fournisseur, et disparaît avec le compte (ON DELETE CASCADE).

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE llm_cache (
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        input_hash text NOT NULL,
        response_text text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, input_hash))"""
    )
    op.execute("ALTER TABLE llm_cache ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_cache FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY llm_cache_isolation ON llm_cache "
        "USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid) "
        "WITH CHECK (user_id = nullif(current_setting('app.user_id', true), '')::uuid)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON llm_cache TO app_rw")
    op.execute("CREATE INDEX llm_calls_user_created ON llm_calls (user_id, created_at)")
    # Le plafond se calcule sur llm_calls : l'application ne peut ni supprimer une ligne ni toucher
    # la réservation ; elle ne met à jour que les jetons et le coût réel après l'appel.
    op.execute("ALTER TABLE llm_calls ADD COLUMN reserved_eur numeric(10,6) NOT NULL DEFAULT 0")
    op.execute("REVOKE DELETE, UPDATE ON llm_calls FROM app_rw")
    op.execute("GRANT UPDATE (input_tokens, output_tokens, cost_eur) ON llm_calls TO app_rw")


def downgrade() -> None:
    op.execute("GRANT DELETE, UPDATE ON llm_calls TO app_rw")
    op.execute("ALTER TABLE llm_calls DROP COLUMN IF EXISTS reserved_eur")
    op.execute("DROP INDEX IF EXISTS llm_calls_user_created")
    op.execute("DROP TABLE IF EXISTS llm_cache")
