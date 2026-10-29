import logging
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import security
from app.config import get_settings
from app.db import user_scope
from app.errors import ApiError

router = APIRouter()
logger = logging.getLogger("app.auth")

# Plafonds d'échecs par fenêtre de 15 min. Le couple (IP, e-mail) est strict ; l'IP seule et l'e-mail
# seul sont plus larges, pour qu'un tiers ne puisse pas verrouiller le compte du propriétaire.
LIMIT_PAIR, LIMIT_IP, LIMIT_EMAIL = 5, 20, 50

SESSION_COOKIE = "session"
CSRF_COOKIE = "csrf_token"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    # Plafond pour éviter qu'un mot de passe géant ne serve à saturer Argon2.
    password: str = Field(min_length=1, max_length=1024)


class Me(BaseModel):
    id: uuid.UUID
    email: str


@dataclass
class Session:
    user_id: str
    sid: str


def current_session(request: Request) -> Session:
    settings = get_settings()
    token = request.cookies.get(SESSION_COOKIE)
    data = security.read_session(settings.secret_key, token, settings.session_max_age) if token else None
    if data is None:
        raise ApiError(401, "unauthorized", "Non connecté")
    try:
        uuid.UUID(data["u"])
    except ValueError:
        raise ApiError(401, "unauthorized", "Non connecté") from None
    return Session(user_id=data["u"], sid=data["s"])


def require_csrf(request: Request, session: Session = Depends(current_session)) -> Session:
    """Double soumission : le cookie `csrf_token` (lisible) doit être renvoyé dans X-CSRF-Token."""
    supplied = request.headers.get("X-CSRF-Token")
    if not security.csrf_is_valid(get_settings().secret_key, session.sid, supplied):
        raise ApiError(403, "csrf_invalid", "Jeton CSRF absent ou invalide")
    return session


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "inconnu"


@router.post("/auth/login", response_model=Me, tags=["auth"])
def login(body: LoginRequest, request: Request, response: Response) -> Me:
    settings = get_settings()
    limiter: security.LoginLimiter = request.app.state.login_limiter
    email = body.email.strip().lower()
    ip = _client_ip(request)
    pair, ip_key, email_key = f"pair:{ip}|{email}", f"ip:{ip}", f"email:{email}"

    wait = max(
        limiter.retry_after(pair, LIMIT_PAIR),
        limiter.retry_after(ip_key, LIMIT_IP),
        limiter.retry_after(email_key, LIMIT_EMAIL),
    )
    if wait:
        logger.warning("connexion bloquée par la limitation des essais")
        raise ApiError(429, "too_many_attempts", "Trop de tentatives, réessayez plus tard",
                       headers={"Retry-After": str(wait)})

    with user_scope() as conn:
        row = conn.execute(text("SELECT user_id, pw_hash FROM auth_lookup_user(:email)"), {"email": email}).first()
    if not security.verify_password(row.pw_hash if row else None, body.password):
        for key in (pair, ip_key, email_key):
            limiter.record_failure(key)
        logger.info("échec de connexion")
        raise ApiError(401, "invalid_credentials", "Identifiants invalides")

    limiter.reset(pair)
    limiter.reset(email_key)
    user_id = str(row.user_id)
    token, sid = security.create_session(settings.secret_key, user_id)
    common = {"max_age": settings.session_max_age, "secure": settings.cookie_secure, "samesite": "strict"}
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, security.csrf_token(settings.secret_key, sid), httponly=False, **common)
    return Me(id=row.user_id, email=email)


@router.post("/auth/logout", status_code=204, tags=["auth"])
def logout(response: Response, _: Session = Depends(require_csrf)) -> None:
    secure = get_settings().cookie_secure
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=secure, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, secure=secure, samesite="strict")


@router.get("/auth/me", response_model=Me, tags=["auth"])
def me(session: Session = Depends(current_session)) -> Me:
    with user_scope(session.user_id) as conn:
        row = conn.execute(text("SELECT id, email FROM users")).first()
    if row is None:  # compte supprimé alors que le cookie est encore valide
        raise ApiError(401, "unauthorized", "Non connecté")
    return Me(id=row.id, email=row.email)
