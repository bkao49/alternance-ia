"""Recherche d'un utilisateur par e-mail avant connexion, sans affaiblir la RLS.

Avant la connexion, `app.user_id` n'existe pas encore : la RLS cacherait tous les comptes. Au lieu
de donner un accès large à `users`, on expose UNE fonction étroite (SECURITY DEFINER) qui ne renvoie
que l'identifiant et le hash du compte demandé. Elle appartient à un rôle dédié `auth_reader` qui n'a
que SELECT sur trois colonnes et une politique en lecture seule.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_reader') "
        "THEN CREATE ROLE auth_reader NOLOGIN; END IF; END $$"
    )
    op.execute("GRANT auth_reader TO CURRENT_USER")
    op.execute("GRANT SELECT (id, email, password_hash) ON users TO auth_reader")
    op.execute("CREATE POLICY users_login_lookup ON users FOR SELECT TO auth_reader USING (true)")
    op.execute(
        """CREATE FUNCTION auth_lookup_user(p_email text)
        RETURNS TABLE (user_id uuid, pw_hash text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$ SELECT id, password_hash FROM users WHERE email = p_email $$"""
    )
    # ALTER OWNER exige que le nouveau propriétaire puisse créer dans le schéma : droit retiré aussitôt.
    op.execute("GRANT CREATE ON SCHEMA public TO auth_reader")
    op.execute("ALTER FUNCTION auth_lookup_user(text) OWNER TO auth_reader")
    op.execute("REVOKE CREATE ON SCHEMA public FROM auth_reader")
    op.execute("REVOKE ALL ON FUNCTION auth_lookup_user(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_lookup_user(text) TO app_rw")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_lookup_user(text)")
    op.execute("DROP POLICY IF EXISTS users_login_lookup ON users")
    op.execute("REVOKE SELECT (id, email, password_hash) ON users FROM auth_reader")
