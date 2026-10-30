"""File de tâches adossée à PostgreSQL (ADR 0004, #13).

La prise, la planification et la relève des tâches abandonnées passent par trois fonctions SQL
étroites (migration 0008), seules à voir plusieurs utilisateurs. Le reste se fait sous la RLS de
l'utilisateur de la tâche. Chaque mise à jour exige `locked_by = worker` : un worker dont la tâche a
été relâchée (trop lent) ne peut plus écrire dessus.
"""
import dataclasses
import logging
import random

from sqlalchemy import text

from app.db import user_scope

log = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 6 * 3600
BASE_BACKOFF_SECONDS = 60


@dataclasses.dataclass(frozen=True)
class Job:
    id: str
    user_id: str
    kind: str
    source: str
    attempts: int
    max_attempts: int


def backoff_seconds(attempts: int, rng: random.Random | None = None) -> float:
    """Délai avant le prochain essai : 2^(essais-1) minutes, au plus 6 h, ± 20 %."""
    base = min(BASE_BACKOFF_SECONDS * 2 ** max(attempts - 1, 0), MAX_BACKOFF_SECONDS)
    return base * (rng or random).uniform(0.8, 1.2)


def claim_job(worker: str) -> Job | None:
    """Prend la plus ancienne tâche prête ; deux workers ne prennent jamais la même (SKIP LOCKED)."""
    with user_scope() as conn:
        row = conn.execute(text("SELECT * FROM claim_job(:worker)"), {"worker": worker}).first()
    if row is None:
        return None
    return Job(str(row.id), str(row.user_id), row.kind, row.source, row.attempts, row.max_attempts)


def schedule_due(default_minutes: int) -> int:
    """Crée une tâche par source activée dont l'intervalle est écoulé ; renvoie le nombre créé."""
    with user_scope() as conn:
        return conn.execute(text("SELECT schedule_due_jobs(:m)"), {"m": default_minutes}).scalar_one()


def reap_stale(stale_seconds: int) -> int:
    """Relâche les tâches `running` sans battement depuis `stale_seconds` (worker plantée)."""
    with user_scope() as conn:
        return conn.execute(text("SELECT reap_stale_jobs(:s)"), {"s": stale_seconds}).scalar_one()


def heartbeat(job: Job, worker: str) -> bool:
    """False : la tâche n'est plus à ce worker."""
    with user_scope(job.user_id) as conn:
        return conn.execute(
            text("UPDATE jobs SET heartbeat_at = now() "
                 "WHERE id = :id AND locked_by = :w AND state = 'running'"),
            {"id": job.id, "w": worker},
        ).rowcount == 1


def _finish(job: Job, worker: str, state: str, error: str | None, run_after: float | None = None,
            counts: tuple[int, int, int] | None = None) -> bool:
    found, new, rejected = counts or (None, None, None)
    queued = state == "queued"
    with user_scope(job.user_id) as conn:
        done = conn.execute(
            text("UPDATE jobs SET state = :state, last_error = left(:error, 200), "
                 "run_at = CASE WHEN :queued THEN now() + make_interval(secs => :after) ELSE run_at END, "
                 "locked_by = NULL, locked_at = NULL, heartbeat_at = NULL, "
                 "finished_at = CASE WHEN :queued THEN NULL ELSE now() END, "
                 "offers_found = :found, offers_new = :new, offers_rejected = :rejected "
                 "WHERE id = :id AND locked_by = :w AND state = 'running'"),
            {"state": state, "error": error, "queued": queued, "after": run_after or 0,
             "found": found, "new": new, "rejected": rejected, "id": job.id, "w": worker},
        ).rowcount == 1
        if done and state != "queued":
            # Fin de passage : base du prochain intervalle, même après un échec (pas de boucle serrée).
            conn.execute(
                text("UPDATE source_settings SET last_run_at = now(), "
                     "last_success_at = CASE WHEN :ok THEN now() ELSE last_success_at END "
                     "WHERE source = :source"),
                {"ok": state == "done", "source": job.source},
            )
    if not done:
        log.warning("job=%s relâché par un autre worker : résultat ignoré", job.id)
    return done


def complete(job: Job, worker: str, found: int, new: int, rejected: int) -> bool:
    return _finish(job, worker, "done", None, counts=(found, new, rejected))


def retry_later(job: Job, worker: str, error: str, after: float | None = None,
                counts: tuple[int, int, int] | None = None) -> bool:
    """Nouvel essai après un délai croissant ; `dead` quand les essais sont épuisés."""
    if job.attempts >= job.max_attempts:
        return _finish(job, worker, "dead", error, counts=counts)
    delay = after if after is not None else backoff_seconds(job.attempts)
    return _finish(job, worker, "queued", error, delay, counts)


def fail(job: Job, worker: str, error: str, counts: tuple[int, int, int] | None = None) -> bool:
    """Erreur sans reprise automatique (clé absente, réponse illisible, bogue)."""
    return _finish(job, worker, "failed", error, counts=counts)


def block_source(job: Job, worker: str, cause: str,
                 counts: tuple[int, int, int] | None = None) -> None:
    """Blocage détecté (403, 429 persistant, CAPTCHA) : jamais de nouvel essai. La source passe à
    « bloquée » et désactivée ; ses autres tâches en attente sont abandonnées. Seul le PO la réactive."""
    _finish(job, worker, "dead", cause, counts=counts)
    with user_scope(job.user_id) as conn:
        conn.execute(
            text("UPDATE source_settings SET enabled = false, blocked_at = now(), blocked_cause = left(:c, 200) "
                 "WHERE source = :source"),
            {"c": cause, "source": job.source},
        )
        conn.execute(
            text("UPDATE jobs SET state = 'dead', last_error = 'source bloquée', finished_at = now() "
                 "WHERE source = :source AND state = 'queued'"),
            {"source": job.source},
        )
