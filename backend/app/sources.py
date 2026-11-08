"""« Mes sources » : chaque utilisateur choisit lui-même les sources que le worker collecte (ADR 0004).

Le catalogue des sources est écrit ici (une fiche `docs/sources/<nom>.md` par source) ; l'état de
chaque utilisateur vit dans `source_settings` (migration 0008), sous la RLS. Une clé de service est une
variable d'environnement du serveur : l'API dit seulement si elle est présente, jamais sa valeur.
"""
import dataclasses
import datetime as dt
import os
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import text

from app.auth import Session, current_session, require_csrf
from app.config import get_worker_settings
from app.db import user_scope
from app.errors import ApiError
from app.mailbox import EMAIL_SOURCE
from app.web_pages import WEB_SOURCE

router = APIRouter(tags=["sources"])

MIN_INTERVAL_MINUTES = 60  # même minimum que la base (CHECK) et que COLLECT_INTERVAL_MINUTES
MAX_INTERVAL_MINUTES = 7 * 24 * 60


@dataclasses.dataclass(frozen=True)
class SourceInfo:
    key: str
    label: str
    description: str
    key_env: tuple[str, ...] = ()  # variables d'environnement du serveur qui doivent être renseignées
    needs: str | None = None  # « pages » (robot web) ou « mailbox » (alertes e-mail) : réglage propre à l'utilisateur

    @property
    def configured(self) -> bool:
        return all(os.environ.get(name) for name in self.key_env)


CATALOG: tuple[SourceInfo, ...] = (
    SourceInfo("france_travail", "France Travail",
               "L'API officielle de l'État : offres de tous contrats et de tous métiers.",
               ("FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET")),
    SourceInfo("lba", "La Bonne Alternance",
               "L'API officielle des offres en alternance et des entreprises qui recrutent.",
               ("LBA_API_TOKEN",)),
    SourceInfo("adzuna", "Adzuna",
               "Un agrégateur d'annonces avec une API gratuite : stages, CDD, CDI et alternance.",
               ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")),
    SourceInfo(WEB_SOURCE, "Pages carrières (robot web)",
               "Les pages emploi des entreprises que vous indiquez : le robot lit les offres qu'elles publient.",
               needs="pages"),
    SourceInfo(EMAIL_SOURCE, "Alertes e-mail (LinkedIn, Indeed…)",
               "Les alertes emploi que vous créez vous-même, reçues dans une boîte e-mail dédiée que le robot lit.",
               needs="mailbox"),
)

# Table qui prouve que l'utilisateur a fait le réglage, et message quand il manque.
NEEDS = {
    "pages": ("web_pages", "Ajoutez d'abord au moins une page à lire."),
    "mailbox": ("email_boxes", "Enregistrez d'abord votre boîte e-mail dédiée."),
}
BY_KEY = {s.key: s for s in CATALOG}


class SourceOut(BaseModel):
    source: str
    label: str
    description: str
    key_env: list[str]
    configured: bool
    enabled: bool
    interval_minutes: int | None
    default_interval_minutes: int
    blocked: bool
    blocked_cause: str | None
    blocked_at: dt.datetime | None
    last_run_at: dt.datetime | None
    last_success_at: dt.datetime | None


class SourceIn(BaseModel):
    """Remplacement complet des réglages d'une source ; `interval_minutes` null = intervalle par défaut."""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    interval_minutes: Annotated[StrictInt, Field(ge=MIN_INTERVAL_MINUTES, le=MAX_INTERVAL_MINUTES)] | None
    confirm_unblock: StrictBool = False


COLUMNS = "source, enabled, interval_minutes, blocked_at, blocked_cause, last_run_at, last_success_at"


def _ready(conn, info: SourceInfo) -> bool:
    """Prête à collecter : clés du serveur présentes et, pour le robot web, au moins une page saisie."""
    if info.needs and not conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {NEEDS[info.needs][0]})")).scalar_one():
        return False
    return info.configured


def _out(info: SourceInfo, row, default_minutes: int, configured: bool) -> dict:
    row = row or {}
    blocked_at = row.get("blocked_at")
    return {
        "source": info.key, "label": info.label, "description": info.description,
        "key_env": list(info.key_env), "configured": configured,
        "enabled": bool(row.get("enabled", False)) and blocked_at is None,
        "interval_minutes": row.get("interval_minutes"), "default_interval_minutes": default_minutes,
        "blocked": blocked_at is not None,
        "blocked_cause": (row.get("blocked_cause") or "Source bloquée") if blocked_at is not None else None,
        "blocked_at": blocked_at, "last_run_at": row.get("last_run_at"),
        "last_success_at": row.get("last_success_at"),
    }


@router.get("/sources", response_model=list[SourceOut], operation_id="listSources")
def list_sources(session: Session = Depends(current_session)):
    default_minutes = get_worker_settings().collect_interval_minutes
    with user_scope(session.user_id) as conn:
        rows = {r["source"]: r for r in conn.execute(text(f"SELECT {COLUMNS} FROM source_settings")).mappings().all()}
        return [_out(info, rows.get(info.key), default_minutes, _ready(conn, info)) for info in CATALOG]


@router.put("/sources/{source}", response_model=SourceOut, operation_id="updateSource")
def update_source(source: str, body: SourceIn, session: Session = Depends(require_csrf)):
    info = BY_KEY.get(source)
    if info is None:
        raise ApiError(404, "not_found", "Source inconnue")
    default_minutes = get_worker_settings().collect_interval_minutes
    with user_scope(session.user_id) as conn:
        current = conn.execute(
            text(f"SELECT {COLUMNS} FROM source_settings WHERE source = :s FOR UPDATE"), {"s": source}
        ).mappings().first()
        blocked = current is not None and current["blocked_at"] is not None
        if body.enabled and blocked and not body.confirm_unblock:
            # Un blocage (403, CAPTCHA, quota) est un signal du site : on ne le lève que sciemment.
            raise ApiError(409, "source_blocked",
                           f"Cette source a été arrêtée : {current['blocked_cause'] or 'blocage détecté'}. "
                           "La réactiver peut aggraver le blocage ; confirmez pour continuer.")
        ready = _ready(conn, info)
        if body.enabled and not ready:
            raise ApiError(409, "source_not_configured",
                           NEEDS[info.needs][1] if info.needs
                           else "La clé de cette source n'est pas configurée sur le serveur.")
        row = conn.execute(
            text("INSERT INTO source_settings (user_id, source, enabled, interval_minutes) "
                 "VALUES (:uid, :s, :enabled, :interval) "
                 "ON CONFLICT (user_id, source) DO UPDATE SET enabled = EXCLUDED.enabled, "
                 "interval_minutes = EXCLUDED.interval_minutes, "
                 "blocked_at = CASE WHEN :unblock THEN NULL ELSE source_settings.blocked_at END, "
                 "blocked_cause = CASE WHEN :unblock THEN NULL ELSE source_settings.blocked_cause END "
                 f"RETURNING {COLUMNS}"),
            {"uid": session.user_id, "s": source, "enabled": body.enabled, "interval": body.interval_minutes,
             "unblock": body.enabled and blocked},  # blocage levé seulement avec confirmation (vérifiée plus haut)
        ).mappings().one()
    return _out(info, row, default_minutes, ready)
