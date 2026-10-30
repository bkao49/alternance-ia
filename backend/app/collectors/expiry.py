"""Marquage des offres expirées (#14), sous RLS (`user_scope`).

Une offre expirée reste en base (historique des candidatures) avec `expired = true`. Les pages
sont relues hors transaction : aucune connexion n'est gardée ouverte pendant les 3 s d'attente
entre deux requêtes.
"""

import datetime as dt
import logging
from collections.abc import Iterable

from sqlalchemy import Connection, text

from app.collectors.base import Collector, CollectorError, SourceBlocked
from app.db import user_scope

log = logging.getLogger(__name__)


def mark_expired(conn: Connection, source: str, external_ids: Iterable[str]) -> int:
    """Marque les offres de la source ; renvoie le nombre de lignes passées à expirée."""
    ids = sorted(set(external_ids))
    if not ids:
        return 0
    return conn.execute(
        text("UPDATE job_postings SET expired = true "
             "WHERE source = :source AND external_id = ANY(:ids) AND NOT expired"),
        {"source": source, "ids": ids},
    ).rowcount


def refresh_expired(
    user_id: str, collector: Collector, *, limit: int = 50, after: dt.datetime | None = None,
) -> tuple[list[str], dt.datetime | None]:
    """Revérifie jusqu'à `limit` offres non expirées détectées après `after` (curseur que le
    planificateur fait tourner). Renvoie les identifiants marqués et le nouveau curseur (None :
    fin de liste). Un blocage arrête la vérification ; les marquages déjà trouvés sont gardés,
    puis le blocage remonte."""
    with user_scope(user_id) as conn:
        rows = conn.execute(
            text("SELECT external_id, url, detected_at FROM job_postings "
                 "WHERE source = :source AND NOT expired AND detected_at > :after "
                 "ORDER BY detected_at, id LIMIT :limit"),
            {"source": collector.source, "limit": limit,
             "after": after or dt.datetime.min.replace(tzinfo=dt.UTC)},
        ).all()
    expired, blocked, cursor = [], None, None
    for external_id, url, detected_at in rows:
        try:
            verdict = collector.check_expired(url)
        except SourceBlocked as exc:
            blocked = exc
            break
        except CollectorError as exc:
            log.warning("collector=%s vérification ignorée (%s)", collector.source,
                        type(exc).__name__)
            verdict = None
        cursor = detected_at
        if verdict:
            expired.append(external_id)
    with user_scope(user_id) as conn:
        mark_expired(conn, collector.source, expired)
    if blocked:
        raise blocked
    return expired, (cursor if len(rows) == limit else None)
