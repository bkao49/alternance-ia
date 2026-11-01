"""État de la collecte, servi par GET /bot/status (écran d'accueil, bloc « Le bot travaille »).

Lit seulement `source_settings` et `jobs` (migration 0008) sous la RLS de l'utilisateur. Aucun contenu
d'annonce : les causes sont les textes fixes écrits par le worker, les messages sont construits ici.
"""
import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.auth import Session, current_session
from app.config import get_worker_settings
from app.db import user_scope

router = APIRouter(tags=["bot"])

ACTIVITY_LIMIT = 10

# Dernier résultat connu de chaque source : une tâche terminée, ou remise en file après un échec
# (attempts > 0). La suivante en attente donne l'heure de la prochaine collecte.
SOURCES_SQL = """
    SELECT s.source, s.enabled, s.interval_minutes, s.blocked_at, s.blocked_cause, s.last_run_at,
           j.state AS job_state, j.last_error, j.offers_found, j.offers_new,
           (SELECT min(q.run_at) FROM jobs q WHERE q.source = s.source AND q.state = 'queued') AS queued_at
    FROM source_settings s
    LEFT JOIN LATERAL (
        SELECT state, last_error, offers_found, offers_new FROM jobs
        WHERE jobs.source = s.source AND (state IN ('done', 'failed', 'dead') OR (state = 'queued' AND attempts > 0))
        ORDER BY created_at DESC, id LIMIT 1
    ) j ON true
    ORDER BY s.source
"""

ACTIVITY_SQL = """
    SELECT j.finished_at AS at, j.source, j.state, j.last_error, j.offers_found, j.offers_new,
           (s.blocked_cause IS NOT NULL AND s.blocked_cause = j.last_error) AS was_blocked
    FROM jobs j LEFT JOIN source_settings s ON s.source = j.source
    WHERE j.state IN ('done', 'failed', 'dead') AND j.finished_at IS NOT NULL
      AND j.last_error IS DISTINCT FROM 'source bloquée'  -- tâches en file abandonnées par un blocage : doublons
    ORDER BY j.finished_at DESC, j.id LIMIT :limit
"""


def plural(n: int, one: str, many: str) -> str:
    return one if n <= 1 else many


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _source(row, default_minutes: int) -> dict:
    if row["blocked_at"] is not None:
        state, cause = "blocked", row["blocked_cause"] or "Source bloquée"
    elif not row["enabled"]:
        state, cause = "disabled", "Source non activée"
    elif row["job_state"] is None:
        state, cause = "pending", None
    elif row["job_state"] == "done":
        state, cause = "ok", None
    else:
        state, cause = "error", row["last_error"] or "Dernière collecte en échec"
    next_run = None
    if state in ("ok", "error", "pending"):  # une source bloquée ou désactivée ne collecte plus
        if row["queued_at"] is not None:
            next_run = row["queued_at"]
        elif row["last_run_at"] is not None:
            minutes = row["interval_minutes"] or default_minutes
            next_run = row["last_run_at"] + dt.timedelta(minutes=minutes)
    data = {
        "source": row["source"], "state": state, "cause": cause, "last_run_at": row["last_run_at"],
        "offers_found": row["offers_found"], "offers_new": row["offers_new"], "next_run_at": next_run,
    }
    return {key: v for key, v in data.items() if v is not None}


def _activity(row) -> dict:
    if row["state"] == "done":
        found, new = row["offers_found"] or 0, row["offers_new"] or 0
        outcome, message = "done", f"{found} {plural(found, 'offre lue', 'offres lues')}, {new} {plural(new, 'nouvelle', 'nouvelles')}"
    elif row["was_blocked"]:
        outcome, message = "blocked", row["last_error"]
    else:
        outcome, message = "error", row["last_error"] or "Collecte en échec"
    return {"at": _iso(row["at"]), "source": row["source"], "outcome": outcome, "message": message}


@router.get("/bot/status", operation_id="getBotStatus")
def get_bot_status(session: Session = Depends(current_session)):
    default_minutes = get_worker_settings().collect_interval_minutes  # le worker lit la même variable
    with user_scope(session.user_id) as conn:
        sources = [_source(r, default_minutes) for r in conn.execute(text(SOURCES_SQL)).mappings().all()]
        activity = [_activity(r) for r in conn.execute(text(ACTIVITY_SQL), {"limit": ACTIVITY_LIMIT}).mappings().all()]
    upcoming = [s["next_run_at"] for s in sources if "next_run_at" in s]
    for source in sources:
        for key in ("last_run_at", "next_run_at"):
            if key in source:
                source[key] = _iso(source[key])
    result = {"sources": sources, "activity": activity}
    if upcoming:
        result["next_run_at"] = _iso(min(upcoming))
    return result
