# ADR 0004 : planificateur et file de tâches PostgreSQL (#13)

Statut : **accepté, migration 0008** (2026-10-30)

## Contexte
Les collectes (#59, #12, Adzuna…) et la revérification des offres expirées (#14) doivent tourner seules, à une fréquence choisie par source, sans Redis (ADR 0001). L'issue #13 demande `SKIP LOCKED`, des reprises avec backoff, la détection des tâches mortes et une fréquence par source.

La table `tasks` existante ne convient pas : elle sert aux **tâches de validation humaine** d'une candidature (`application_id NOT NULL`, états `open` / `done`) et n'a ni date d'exécution, ni verrou, ni compteur d'essais. La détourner mélangerait deux notions. Il faut donc deux tables nouvelles : cette PR ne crée aucune migration (une autre session les gère) et décrit le besoin.

## Décision proposée

### Tables (migration à écrire par le Backend)
```sql
CREATE TABLE source_settings (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source text NOT NULL,                       -- conforme à SOURCE_PATTERN
    enabled boolean NOT NULL DEFAULT false,     -- activée par le PO seulement
    interval_minutes integer NOT NULL DEFAULT 720 CHECK (interval_minutes >= 60),
    blocked_at timestamptz,                     -- #14 : blocage détecté → enabled = false
    blocked_cause text,                         -- texte fixe (« HTTP 403 », « CAPTCHA »)
    last_run_at timestamptz,
    PRIMARY KEY (user_id, source));

CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('collect', 'refresh_expired')),
    source text NOT NULL,
    state text NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued', 'running', 'done', 'failed', 'dead')),
    run_at timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    locked_by text, locked_at timestamptz, heartbeat_at timestamptz,
    last_error text,                            -- CollectorError.message, jamais de contenu
    created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
    UNIQUE (user_id, id));
CREATE INDEX jobs_ready ON jobs (run_at) WHERE state = 'queued';
-- Une seule tâche active par source : le planificateur ne crée pas de doublon.
CREATE UNIQUE INDEX jobs_one_active ON jobs (user_id, kind, source)
    WHERE state IN ('queued', 'running');
```
Les deux tables suivent les règles du schéma : `user_id` partout, RLS `ENABLE` + `FORCE`, politique sur `app.user_id`, droits pour `app_rw`.

### Prise d'une tâche (worker)
```sql
UPDATE jobs SET state = 'running', locked_by = :worker, locked_at = now(),
               heartbeat_at = now(), attempts = attempts + 1
WHERE id = (SELECT id FROM jobs WHERE state = 'queued' AND run_at <= now()
            ORDER BY run_at FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING id, user_id, kind, source, attempts;
```
Le worker n'a pas d'utilisateur courant : comme `auth_lookup_user`, la prise passe par une fonction `SECURITY DEFINER` étroite (`claim_job(worker text)`) qui ne renvoie que la tâche prise. Le travail lui-même se fait ensuite dans `user_scope(user_id)`.

### Résultat
| Issue de la tâche | Effet |
|---|---|
| succès | `done`, `source_settings.last_run_at = now()` |
| `QuotaExceeded` | `queued`, `run_at = now() + retry_after` (ou backoff) |
| `NetworkError` | `queued`, backoff : `min(2^attempts min, 6 h)` ± 20 % ; `dead` après `max_attempts` |
| `SourceBlocked` | `dead` sans nouvel essai ; `enabled = false`, `blocked_at`, `blocked_cause` ; notification (`handle_blocks`, #14) |
| autre erreur | `failed`, pas de nouvel essai automatique |

### Tâches mortes
Le worker met `heartbeat_at` à jour toutes les 30 s. Une tâche `running` sans battement depuis 10 min repasse en `queued` (l'essai compte) ou en `dead` si `attempts >= max_attempts`.

### Planification
Chaque minute : pour chaque source `enabled`, non bloquée, dont `last_run_at + interval_minutes <= now()`, insérer une tâche `collect` (`ON CONFLICT DO NOTHING` grâce à l'index partiel). Une tâche `refresh_expired` par jour et par source.

## Conséquences
- Une seule collecte à la fois par source, ce qui garde valable le délai de 3 s par domaine tenu en mémoire (ADR 0003).
- Réactiver une source bloquée reste un geste du PO (`enabled = true`, `blocked_at = NULL`).
- Le code (`app/worker.py`) et le test de concurrence demandé par #13 (deux workers, une tâche) seront écrits dès que la migration existera.

## Mise en œuvre (migration 0008, PR #13)
- Écarts avec la proposition : `kind` n'accepte que `collect` pour l'instant (la revérification quotidienne `refresh_expired` s'ajoutera avec sa planification) ; `interval_minutes` peut être NULL (intervalle par défaut du worker, `COLLECT_INTERVAL_MINUTES`, 120 min) ; `source_settings.last_success_at` et les compteurs d'offres de `jobs` servent d'historique des passages.
- Trois fonctions SQL étroites : `claim_job`, `schedule_due_jobs`, `reap_stale_jobs`. Une tâche `dead` par la relève fait avancer `last_run_at`, pour qu'un worker qui plante en boucle ne soit pas relancé chaque minute.
- Un `Retry-After` de la source est borné entre 1 minute et 6 h ; un quota encore refusé après `max_attempts` essais bloque la source.
- **Limites connues** : le blocage est par utilisateur et par source (le projet est mono-PO) ; si plusieurs utilisateurs partageaient une source, il faudrait un blocage global, et le délai de 3 s par domaine (en mémoire) ne couvrirait pas deux workers sur le même domaine. Les fonctions sont exécutables par le rôle de l'API (même modèle que `auth_lookup_user`) ; un rôle distinct pour le worker pourra les réserver plus tard.
