from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Connection, create_engine, text

from app.config import get_settings


@lru_cache
def _engine(url: str):
    return create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1), pool_pre_ping=True)


@contextmanager
def user_scope(user_id: str | None = None) -> Iterator[Connection]:
    """Transaction soumise à la Row Level Security.

    `SET LOCAL ROLE` et `set_config(..., true)` ne durent que le temps de la transaction : rien ne
    reste sur la connexion rendue au pool. Sans `user_id`, aucune ligne n'est visible (sauf la
    fonction de connexion `auth_lookup_user`).
    """
    with _engine(get_settings().database_url).begin() as conn:
        conn.execute(text("SET LOCAL ROLE app_rw"))
        if user_id is not None:
            conn.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": user_id})
        yield conn
