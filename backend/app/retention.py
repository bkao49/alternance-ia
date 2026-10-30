"""Durées de conservation (RGPD) et purge : `python -m app.retention`.

Les durées se règlent par variables d'environnement ; la politique complète est décrite dans
`docs/security/retention.md`. À lancer chaque jour (tâche planifiée du worker, à venir).
"""
import logging
import os
from dataclasses import dataclass

from sqlalchemy import text

from app.db import user_scope

log = logging.getLogger(__name__)

DEFAULT_OFFERS_DAYS = 180
DEFAULT_LLM_DAYS = 90
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
    if not 1 <= value <= MAX_DAYS:
        raise RuntimeError(f"{name} doit être compris entre 1 et {MAX_DAYS}")
    return value


def retention_from_env() -> Retention:
    return Retention(offers_days=_days("RETENTION_OFFERS_DAYS", DEFAULT_OFFERS_DAYS),
                     llm_days=_days("RETENTION_LLM_DAYS", DEFAULT_LLM_DAYS))


def purge_expired(retention: Retention | None = None) -> dict[str, int]:
    """Supprime, pour tous les utilisateurs, les lignes plus anciennes que leur durée de conservation."""
    retention = retention or retention_from_env()
    with user_scope() as conn:
        rows = conn.execute(text("SELECT table_name, deleted FROM purge_expired_data(:offers, :llm)"),
                            {"offers": retention.offers_days, "llm": retention.llm_days}).all()
    counts = {row.table_name: int(row.deleted) for row in rows}
    log.info("purge de conservation : %s", counts)  # des compteurs seulement, aucun contenu
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(purge_expired())
