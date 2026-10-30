"""Purge des données arrivées au bout de leur durée de conservation (RGPD), sans affaiblir la RLS.

La purge concerne tous les utilisateurs, alors que la RLS ne montre que l'utilisateur courant. Même
méthode que `auth_lookup_user` (0002) : UNE fonction étroite (SECURITY DEFINER) appartenant au rôle
dédié `retention_purger`, qui ne peut que lire et supprimer les lignes concernées par la purge.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# Tables purgées ; applications n'est que lue (une offre liée à une candidature est conservée).
PURGED = ["job_postings", "llm_calls", "llm_cache"]


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'retention_purger') "
        "THEN CREATE ROLE retention_purger NOLOGIN; END IF; END $$"
    )
    op.execute("GRANT retention_purger TO CURRENT_USER")
    for table in PURGED:
        op.execute(f"GRANT SELECT, DELETE ON {table} TO retention_purger")
        op.execute(f"CREATE POLICY {table}_retention_read ON {table} FOR SELECT TO retention_purger USING (true)")
        op.execute(f"CREATE POLICY {table}_retention_delete ON {table} FOR DELETE TO retention_purger USING (true)")
    op.execute("GRANT SELECT (job_posting_id) ON applications TO retention_purger")
    op.execute(
        "CREATE POLICY applications_retention_read ON applications FOR SELECT TO retention_purger USING (true)"
    )
    op.execute(
        """CREATE FUNCTION purge_expired_data(p_offers_days integer, p_llm_days integer)
        RETURNS TABLE (table_name text, deleted bigint)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
        DECLARE n bigint;
        BEGIN
          IF p_offers_days < 1 OR p_llm_days < 1 THEN
            RAISE EXCEPTION 'durée de conservation invalide';
          END IF;
          -- Les offres retenues par une candidature restent : la candidature est conservée jusqu'à
          -- sa suppression par l'utilisateur.
          DELETE FROM public.job_postings j
           WHERE j.detected_at < now() - make_interval(days => p_offers_days)
             AND NOT EXISTS (SELECT 1 FROM public.applications a WHERE a.job_posting_id = j.id);
          GET DIAGNOSTICS n = ROW_COUNT; table_name := 'job_postings'; deleted := n; RETURN NEXT;
          DELETE FROM public.llm_calls WHERE created_at < now() - make_interval(days => p_llm_days);
          GET DIAGNOSTICS n = ROW_COUNT; table_name := 'llm_calls'; deleted := n; RETURN NEXT;
          DELETE FROM public.llm_cache WHERE created_at < now() - make_interval(days => p_llm_days);
          GET DIAGNOSTICS n = ROW_COUNT; table_name := 'llm_cache'; deleted := n; RETURN NEXT;
        END $$"""
    )
    # ALTER OWNER exige que le nouveau propriétaire puisse créer dans le schéma : droit retiré aussitôt.
    op.execute("GRANT CREATE ON SCHEMA public TO retention_purger")
    op.execute("ALTER FUNCTION purge_expired_data(integer, integer) OWNER TO retention_purger")
    op.execute("REVOKE CREATE ON SCHEMA public FROM retention_purger")
    op.execute("REVOKE ALL ON FUNCTION purge_expired_data(integer, integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION purge_expired_data(integer, integer) TO app_rw")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS purge_expired_data(integer, integer)")
    op.execute("DROP POLICY IF EXISTS applications_retention_read ON applications")
    op.execute("REVOKE SELECT (job_posting_id) ON applications FROM retention_purger")
    for table in PURGED:
        op.execute(f"DROP POLICY IF EXISTS {table}_retention_delete ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_retention_read ON {table}")
        op.execute(f"REVOKE SELECT, DELETE ON {table} FROM retention_purger")
    op.execute("REVOKE retention_purger FROM CURRENT_USER")
