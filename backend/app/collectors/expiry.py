"""Marquage des offres expirées (#14), dans une transaction `user_scope` (RLS).

Une offre expirée reste en base (historique des candidatures) avec `expired = true`.
"""

import logging
from collections.abc import Iterable

from sqlalchemy import Connection, text

from app.collectors.base import Collector, CollectorError, SourceBlocked

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


def refresh_expired(conn: Connection, collector: Collector, limit: int = 50) -> list[str]:
    """Revérifie les plus anciennes offres non expirées de la source. Un blocage arrête la
    vérification (et remonte) ; une autre erreur sur une offre la laisse telle quelle."""
    rows = conn.execute(
        text("SELECT external_id, url FROM job_postings WHERE source = :source AND NOT expired "
             "ORDER BY detected_at, id LIMIT :limit"),
        {"source": collector.source, "limit": limit},
    ).all()
    expired = []
    for external_id, url in rows:
        try:
            verdict = collector.check_expired(url)
        except SourceBlocked:
            mark_expired(conn, collector.source, expired)
            raise
        except CollectorError as exc:
            log.warning("collector=%s vérification ignorée (%s)", collector.source,
                        type(exc).__name__)
            continue
        if verdict:
            expired.append(external_id)
    mark_expired(conn, collector.source, expired)
    return expired
