"""File de tâches (`jobs`), état par source (`source_settings`) et colonnes d'offre du collecteur.

ADR 0004. Le worker n'a pas d'utilisateur courant alors que la RLS ne montre que l'utilisateur
courant. Comme pour `auth_lookup_user` (0002) et la purge (0006), trois fonctions étroites
(SECURITY DEFINER) appartenant au rôle dédié `job_dispatcher` font le seul travail inter-utilisateurs :
prendre UNE tâche prête, créer les tâches dues, relâcher les tâches abandonnées. Tout le reste
(heartbeat, résultat, enregistrement des offres) se fait dans `user_scope(user_id)`.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

CONTRACTS = "('internship','apprenticeship','fixed_term','permanent','other')"
FUNCTIONS = [
    ("claim_job(text)",
     """CREATE FUNCTION claim_job(p_worker text)
        RETURNS TABLE (id uuid, user_id uuid, kind text, source text, attempts integer, max_attempts integer)
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
          UPDATE public.jobs j SET state = 'running', locked_by = p_worker, locked_at = now(),
                                   heartbeat_at = now(), attempts = j.attempts + 1
           WHERE j.id = (SELECT q.id FROM public.jobs q
                          WHERE q.state = 'queued' AND q.run_at <= now()
                            AND EXISTS (SELECT 1 FROM public.source_settings s
                                         WHERE s.user_id = q.user_id AND s.source = q.source
                                           AND s.enabled AND s.blocked_at IS NULL)
                          ORDER BY q.run_at FOR UPDATE OF q SKIP LOCKED LIMIT 1)
          RETURNING j.id, j.user_id, j.kind, j.source, j.attempts, j.max_attempts
        $$"""),
    ("schedule_due_jobs(integer)",
     """CREATE FUNCTION schedule_due_jobs(p_default_minutes integer) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
        DECLARE n integer;
        BEGIN
          IF p_default_minutes < 60 THEN RAISE EXCEPTION 'intervalle trop court'; END IF;
          -- L'index partiel jobs_one_active garantit une seule tâche active par source.
          INSERT INTO public.jobs (user_id, kind, source)
          SELECT s.user_id, 'collect', s.source FROM public.source_settings s
           WHERE s.enabled AND s.blocked_at IS NULL
             AND (s.last_run_at IS NULL OR s.last_run_at
                  + make_interval(mins => coalesce(s.interval_minutes, p_default_minutes)) <= now())
          ON CONFLICT (user_id, kind, source) WHERE state IN ('queued', 'running') DO NOTHING;
          GET DIAGNOSTICS n = ROW_COUNT;
          RETURN n;
        END $$"""),
    ("reap_stale_jobs(integer)",
     """CREATE FUNCTION reap_stale_jobs(p_stale_seconds integer) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
        DECLARE n integer;
        BEGIN
          IF p_stale_seconds < 60 THEN RAISE EXCEPTION 'délai trop court'; END IF;
          -- Worker disparu (plantage) : l'essai compte ; trop d'essais, la tâche est « morte ».
          -- Tâche devenue « morte » : la source garde son intervalle (sinon un worker qui plante en
          -- boucle serait relancé à chaque minute).
          WITH r AS (
            UPDATE public.jobs SET
                state = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
                run_at = now(), locked_by = NULL, locked_at = NULL, heartbeat_at = NULL,
                finished_at = CASE WHEN attempts >= max_attempts THEN now() END,
                last_error = 'worker disparu'
             WHERE state = 'running' AND heartbeat_at < now() - make_interval(secs => p_stale_seconds)
            RETURNING user_id, source, state),
          t AS (
            UPDATE public.source_settings s SET last_run_at = now() FROM r
             WHERE r.state = 'dead' AND s.user_id = r.user_id AND s.source = r.source
            RETURNING 1)
          SELECT count(*) INTO n FROM r;
          RETURN n;
        END $$"""),
]


def upgrade() -> None:
    op.execute(
        """CREATE TABLE source_settings (
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source text NOT NULL CHECK (source ~ '^[a-z][a-z0-9_]{1,39}$'),
        enabled boolean NOT NULL DEFAULT false,  -- activée par le PO seulement
        interval_minutes integer CHECK (interval_minutes >= 60),  -- NULL : intervalle par défaut du worker
        blocked_at timestamptz,
        blocked_cause text CHECK (length(blocked_cause) <= 200),  -- texte fixe, jamais du contenu
        last_run_at timestamptz,  -- fin du dernier passage (réussi ou non) : base du prochain
        last_success_at timestamptz,
        PRIMARY KEY (user_id, source))"""
    )
    op.execute(
        """CREATE TABLE jobs (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind text NOT NULL CHECK (kind IN ('collect')),
        source text NOT NULL CHECK (source ~ '^[a-z][a-z0-9_]{1,39}$'),
        state text NOT NULL DEFAULT 'queued'
            CHECK (state IN ('queued', 'running', 'done', 'failed', 'dead')),
        run_at timestamptz NOT NULL DEFAULT now(),
        attempts integer NOT NULL DEFAULT 0,
        max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 10),
        locked_by text CHECK (length(locked_by) <= 100), locked_at timestamptz, heartbeat_at timestamptz,
        last_error text CHECK (length(last_error) <= 200),  -- message fixe, jamais de contenu
        offers_found integer, offers_new integer, offers_rejected integer,  -- historique du passage
        created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
        UNIQUE (user_id, id))"""
    )
    op.execute("CREATE INDEX jobs_ready ON jobs (run_at) WHERE state = 'queued'")
    op.execute(
        "CREATE UNIQUE INDEX jobs_one_active ON jobs (user_id, kind, source) "
        "WHERE state IN ('queued', 'running')"
    )
    op.execute("CREATE INDEX jobs_history ON jobs (user_id, source, created_at DESC)")
    for table in ("source_settings", "jobs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_isolation ON {table} "
            f"USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid) "
            f"WITH CHECK (user_id = nullif(current_setting('app.user_id', true), '')::uuid)"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rw")

    # Champs de l'offre normalisée (ADR 0002) ; NULL pour les offres déjà enregistrées.
    op.execute(f"ALTER TABLE job_postings ADD COLUMN contract_type text CHECK (contract_type IN {CONTRACTS})")
    op.execute("ALTER TABLE job_postings ADD COLUMN published_at timestamptz")
    op.execute("ALTER TABLE job_postings ADD COLUMN fingerprint text")

    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'job_dispatcher') "
        "THEN CREATE ROLE job_dispatcher NOLOGIN; END IF; END $$"
    )
    op.execute("GRANT job_dispatcher TO CURRENT_USER")
    op.execute("GRANT SELECT, INSERT, UPDATE ON jobs TO job_dispatcher")
    op.execute("GRANT SELECT ON source_settings TO job_dispatcher")
    op.execute("GRANT UPDATE (last_run_at) ON source_settings TO job_dispatcher")
    op.execute("CREATE POLICY jobs_dispatch ON jobs TO job_dispatcher USING (true) WITH CHECK (true)")
    op.execute(
        "CREATE POLICY source_settings_dispatch_read ON source_settings FOR SELECT TO job_dispatcher "
        "USING (true)"
    )
    op.execute(
        "CREATE POLICY source_settings_dispatch_touch ON source_settings FOR UPDATE TO job_dispatcher "
        "USING (true) WITH CHECK (true)"
    )
    # ALTER OWNER exige que le nouveau propriétaire puisse créer dans le schéma : droit retiré aussitôt.
    op.execute("GRANT CREATE ON SCHEMA public TO job_dispatcher")
    for signature, ddl in FUNCTIONS:
        op.execute(ddl)
        op.execute(f"ALTER FUNCTION {signature} OWNER TO job_dispatcher")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO app_rw")
    op.execute("REVOKE CREATE ON SCHEMA public FROM job_dispatcher")
    op.execute("REVOKE job_dispatcher FROM CURRENT_USER")


def downgrade() -> None:
    for signature, _ in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.execute("ALTER TABLE job_postings DROP COLUMN IF EXISTS fingerprint")
    op.execute("ALTER TABLE job_postings DROP COLUMN IF EXISTS published_at")
    op.execute("ALTER TABLE job_postings DROP COLUMN IF EXISTS contract_type")
    op.execute("DROP TABLE IF EXISTS jobs")
    op.execute("DROP TABLE IF EXISTS source_settings")
