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
