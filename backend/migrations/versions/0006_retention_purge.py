"""Purge des données arrivées au bout de leur durée de conservation (RGPD), sans affaiblir la RLS.

La purge concerne tous les utilisateurs, alors que la RLS ne montre que l'utilisateur courant. Même
méthode que `auth_lookup_user` (0002) : UNE fonction étroite (SECURITY DEFINER) appartenant au rôle
dédié `retention_purger`, qui ne lit que les colonnes de date et d'identifiant et ne peut que supprimer.
L'application (`app_rw`) ne peut PAS l'appeler : seul `retention_runner`, dont n'est membre que le
rôle des migrations, le peut (`python -m app.retention` se connecte avec MIGRATION_DATABASE_URL).

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# Colonnes lues par la purge, table par table ; applications n'est que lue (une offre liée à une
# candidature est conservée).
READ = {"job_postings": "id, detected_at", "llm_calls": "created_at", "llm_cache": "created_at"}
MIN_DAYS = 30  # plancher en base : même un appel direct ne peut pas tout effacer


def create_role(name: str) -> None:
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{name}') "
        f"THEN CREATE ROLE {name} NOLOGIN; END IF; END $$"
    )


def upgrade() -> None:
    create_role("retention_purger")
    create_role("retention_runner")
    op.execute("GRANT retention_purger TO CURRENT_USER")
    op.execute("GRANT retention_runner TO CURRENT_USER")
    for table, columns in READ.items():
        op.execute(f"GRANT SELECT ({columns}), DELETE ON {table} TO retention_purger")
        op.execute(f"CREATE POLICY {table}_retention_read ON {table} FOR SELECT TO retention_purger USING (true)")
        op.execute(f"CREATE POLICY {table}_retention_delete ON {table} FOR DELETE TO retention_purger USING (true)")
    op.execute("GRANT SELECT (job_posting_id) ON applications TO retention_purger")
    op.execute(
        "CREATE POLICY applications_retention_read ON applications FOR SELECT TO retention_purger USING (true)"
    )
    op.execute(
        f"""CREATE FUNCTION purge_expired_data(p_offers_days integer, p_llm_days integer)
        RETURNS TABLE (table_name text, deleted bigint)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
        DECLARE n bigint;
        BEGIN
          IF p_offers_days < {MIN_DAYS} OR p_llm_days < {MIN_DAYS} THEN
            RAISE EXCEPTION 'durée de conservation trop courte';
          END IF;
          -- Les offres retenues par une candidature restent : la candidature est conservée jusqu'à
          -- sa suppression par l'utilisateur. Analyses et scores de l'offre suivent (ON DELETE CASCADE).
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
    op.execute("GRANT EXECUTE ON FUNCTION purge_expired_data(integer, integer) TO retention_runner")
    # Le rôle des migrations n'a plus besoin d'être purger (accès inter-utilisateurs) : il reste runner.
    op.execute("REVOKE retention_purger FROM CURRENT_USER")


def downgrade() -> None:
    op.execute("GRANT retention_purger TO CURRENT_USER")  # nécessaire pour supprimer sa fonction
    op.execute("DROP FUNCTION IF EXISTS purge_expired_data(integer, integer)")
    op.execute("DROP POLICY IF EXISTS applications_retention_read ON applications")
    op.execute("REVOKE SELECT (job_posting_id) ON applications FROM retention_purger")
    for table, columns in READ.items():
        op.execute(f"DROP POLICY IF EXISTS {table}_retention_delete ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_retention_read ON {table}")
        op.execute(f"REVOKE SELECT ({columns}), DELETE ON {table} FROM retention_purger")
    op.execute("REVOKE retention_runner FROM CURRENT_USER")
    op.execute("REVOKE retention_purger FROM CURRENT_USER")
