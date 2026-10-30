import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    secret_key: str
    database_url: str
    cookie_secure: bool
    session_max_age: int = 7 * 24 * 3600


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} n'est pas défini")
    return value


def get_settings() -> Settings:
    """Lit l'environnement à chaque appel (utile aux tests). N'inclut jamais de valeur dans les erreurs."""
    secret = os.environ.get("SECRET_KEY", "")
    if len(secret) < 32:
        raise RuntimeError("SECRET_KEY doit contenir au moins 32 caractères")
    return Settings(
        secret_key=secret,
        database_url=_required("DATABASE_URL"),
        # Désactivable uniquement pour le développement local en http.
        cookie_secure=os.environ.get("COOKIE_SECURE", "true").lower() != "false",
    )


@dataclass(frozen=True)
class WorkerSettings:
    """Réglages du worker (processus séparé de l'API), tous modifiables par l'environnement."""

    collect_interval_minutes: int = 120  # intervalle des sources sans réglage propre (ADR 0004)
    poll_seconds: float = 5.0  # attente quand la file est vide
    schedule_seconds: float = 60.0  # fréquence du planificateur
    heartbeat_seconds: float = 30.0
    stale_seconds: int = 600  # tâche sans battement depuis ce délai : worker considéré planté
    web_sites_file: str | None = None  # TOML des sites activés (un site listé = site validé par le PO)


def _number(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(name, "")
    try:
        value = float(raw) if raw else default
    except ValueError:
        raise RuntimeError(f"{name} doit être un nombre") from None
    if value < minimum:
        raise RuntimeError(f"{name} doit être au moins {minimum:g}")
    return value


def get_worker_settings() -> WorkerSettings:
    settings = _worker_settings()
    if settings.stale_seconds < 4 * settings.heartbeat_seconds:  # sinon un worker vivant serait « mort »
        raise RuntimeError("WORKER_STALE_SECONDS doit valoir au moins 4 fois WORKER_HEARTBEAT_SECONDS")
    return settings


def _worker_settings() -> WorkerSettings:
    return WorkerSettings(
        collect_interval_minutes=int(_number("COLLECT_INTERVAL_MINUTES", 120, 60)),  # >= 60 comme en base
        poll_seconds=_number("WORKER_POLL_SECONDS", 5, 0.1),
        schedule_seconds=_number("WORKER_SCHEDULE_SECONDS", 60, 1),
        heartbeat_seconds=_number("WORKER_HEARTBEAT_SECONDS", 30, 0.1),
        stale_seconds=int(_number("WORKER_STALE_SECONDS", 600, 60)),
        web_sites_file=os.environ.get("WEB_SITES_FILE") or None,
    )
