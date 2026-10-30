"""Durées de conservation (RGPD) et purge : `python -m app.retention`.

Les durées se règlent par variables d'environnement ; la politique complète est décrite dans
`docs/security/retention.md`. À lancer chaque jour (tâche planifiée du worker, à venir), avec
MIGRATION_DATABASE_URL : seul le rôle des migrations est membre de `retention_runner`, le rôle de
l'API ne peut pas déclencher de purge (migration 0006).
"""
import logging
import os
from dataclasses import dataclass

from sqlalchemy import text

from app.db import _engine

log = logging.getLogger(__name__)

DEFAULT_OFFERS_DAYS = 180
DEFAULT_LLM_DAYS = 90
MIN_DAYS = 30  # même plancher qu'en base
MAX_DAYS = 3650


@dataclass(frozen=True)
class Retention:
    offers_days: int  # offres détectées non retenues par une candidature
    llm_days: int  # journal et cache des appels IA


def _days(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        value = int(raw) if raw else default
    except ValueError:
        raise RuntimeError(f"{name} doit être un nombre entier de jours") from None
    if not MIN_DAYS <= value <= MAX_DAYS:
        raise RuntimeError(f"{name} doit être compris entre {MIN_DAYS} et {MAX_DAYS}")
    return value


def retention_from_env() -> Retention:
    return Retention(offers_days=_days("RETENTION_OFFERS_DAYS", DEFAULT_OFFERS_DAYS),
                     llm_days=_days("RETENTION_LLM_DAYS", DEFAULT_LLM_DAYS))


def purge_expired(retention: Retention | None = None) -> dict[str, int]:
    """Supprime, pour tous les utilisateurs, les lignes plus anciennes que leur durée de conservation."""
    retention = retention or retention_from_env()
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATION_DATABASE_URL n'est pas défini")
    with _engine(url).begin() as conn:
        conn.execute(text("SET LOCAL ROLE retention_runner"))
        rows = conn.execute(text("SELECT table_name, deleted FROM purge_expired_data(:offers, :llm)"),
                            {"offers": retention.offers_days, "llm": retention.llm_days}).all()
    counts = {row.table_name: int(row.deleted) for row in rows}
    log.info("purge de conservation : %s", counts)  # des compteurs seulement, aucun contenu
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(purge_expired())
