import logging

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app import security
from app.auth import CSRF_COOKIE, SESSION_COOKIE, Session, require_csrf
from app.config import get_settings
from app.db import user_scope
from app.errors import ApiError

router = APIRouter(tags=["account"])
logger = logging.getLogger("app.account")

LIMIT_DELETE = 5  # mots de passe faux par fenêtre de 15 min


class AccountDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024)
    confirm: bool


@router.post("/account/delete", status_code=204, operation_id="deleteAccount")
def delete_account(body: AccountDeletion, request: Request, response: Response,
                   session: Session = Depends(require_csrf)) -> None:
    """Droit à l'effacement : la suppression de `users` emporte toutes les tables (ON DELETE CASCADE)."""
    if body.confirm is not True:
        raise ApiError(422, "validation_error", "La suppression doit être confirmée")
    limiter: security.LoginLimiter = request.app.state.login_limiter
    key = f"delete:{session.user_id}"
    wait = limiter.retry_after(key, LIMIT_DELETE)
    if wait:
        raise ApiError(429, "too_many_attempts", "Trop de tentatives, réessayez plus tard",
                       headers={"Retry-After": str(wait)})

    with user_scope(session.user_id) as conn:
        stored = conn.execute(text("SELECT password_hash FROM users")).scalar()
        if stored is None:  # compte déjà supprimé alors que le cookie est encore valide
            raise ApiError(401, "unauthorized", "Non connecté")
        if not security.verify_password(stored, body.password):
            limiter.record_failure(key)
            raise ApiError(403, "invalid_password", "Mot de passe incorrect")
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": session.user_id})
    limiter.reset(key)
    logger.info("compte supprimé à la demande de l'utilisateur")  # aucun identifiant journalisé

    secure = get_settings().cookie_secure
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=secure, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, secure=secure, samesite="strict")
