"""Critères de recherche saisis par chaque utilisateur : une ligne par utilisateur, sous RLS.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

CONTRACT_TYPES = "ARRAY['internship','apprenticeship','fixed_term','permanent','other']"
EDUCATION_LEVELS = "('bac','bac_plus_2','bac_plus_3','bac_plus_4','bac_plus_5','doctorate','other')"


def upgrade() -> None:
    # user_id est la clé primaire : une seule fiche de critères par utilisateur.
    op.execute(
        f"""CREATE TABLE search_preferences (
        user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        keywords text[] NOT NULL DEFAULT '{{}}' CHECK (cardinality(keywords) <= 20),
        locations jsonb NOT NULL DEFAULT '[]' 
            CHECK (jsonb_typeof(locations) = 'array' AND jsonb_array_length(locations) <= 10),
        remote_accepted boolean NOT NULL DEFAULT false,
        contract_types text[] NOT NULL DEFAULT '{{}}' CHECK (contract_types <@ {CONTRACT_TYPES}),
        start_date date,
        duration_months integer CHECK (duration_months BETWEEN 1 AND 60),
        alternance_rhythm text CHECK (length(alternance_rhythm) <= 80),
        education_level text CHECK (education_level IN {EDUCATION_LEVELS}),
        min_salary_eur integer CHECK (min_salary_eur BETWEEN 0 AND 1000000),
        excluded_keywords text[] NOT NULL DEFAULT '{{}}' CHECK (cardinality(excluded_keywords) <= 50),
        updated_at timestamptz NOT NULL DEFAULT now())"""
    )
    op.execute("ALTER TABLE search_preferences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE search_preferences FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY search_preferences_isolation ON search_preferences "
        "USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid) "
        "WITH CHECK (user_id = nullif(current_setting('app.user_id', true), '')::uuid)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON search_preferences TO app_rw")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_preferences")
