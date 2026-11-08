"""Alertes e-mail par utilisateur (#128, suite de #90) : la boîte DÉDIÉE de chacun, saisie dans l'application.

L'utilisateur crée lui-même ses alertes (LinkedIn, Indeed…) vers une boîte à lui réservée à cet usage ; on lit
cette boîte en IMAP sécurisé avec un mot de passe d'application. Aucune connexion à LinkedIn ou à un autre site.

- Le mot de passe est chiffré au repos (Fernet, clé dérivée de SECRET_KEY, ADR 0012), n'est jamais renvoyé par
  l'API ni écrit dans les journaux ou les erreurs.
- L'hôte est une saisie de l'utilisateur : même garde-fou SSRF que les pages du robot web (pas d'adresse IP, locale
  ou privée), vérifié aussi à chaque connexion ; seul le port 993 (IMAP sur TLS) est accepté.
- « Tester la connexion » se lance depuis l'écran, au plus une fois toutes les 10 secondes.
"""
import base64
import datetime as dt
import logging
import os
from collections.abc import Callable
from typing import Annotated

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, StrictInt, StringConstraints, field_validator
from sqlalchemy import Connection, text

from app.auth import Session, current_session, require_csrf
from app.collectors.base import Collector, CollectorError, NetworkError
from app.collectors.http_client import is_public_address, system_resolver
from app.collectors.mail import EmailCollector, ImapMailClient, MailClient
from app.db import user_scope
from app.errors import ApiError
from app.web_pages import check_hostname

log = logging.getLogger(__name__)
router = APIRouter(tags=["sources"])

EMAIL_SOURCE = "email"
IMAPS_PORT = 993
TEST_COOLDOWN_SECONDS = 10
KEY_INFO = b"ereuna/email-box/v1"
UNREADABLE = "mot de passe illisible : ressaisissez-le dans « Mes sources »"

# Remplaçable en test : connexion IMAP réelle par défaut.
connect_imap: Callable[..., MailClient] = ImapMailClient


# --- Chiffrement --------------------------------------------------------------------------------


def _fernet() -> Fernet:
    secret = os.environ.get("SECRET_KEY", "")
    if len(secret) < 32:
        raise RuntimeError("SECRET_KEY doit contenir au moins 32 caractères")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=KEY_INFO).derive(secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(password: str) -> str:
    return _fernet().encrypt(password.encode()).decode()


def decrypt(token: str) -> str:
    """Mot de passe en clair ; `ValueError` si la clé a changé ou si la valeur est altérée."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("mot de passe illisible") from None


# --- Validation ---------------------------------------------------------------------------------


def _no_control(value: str) -> str:
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("caractère interdit")
    return value


def ensure_public_host(host: str) -> None:
    """Refuse un serveur dont le nom ou l'adresse est locale ou privée (SSRF). Appelé à l'enregistrement
    ET avant chaque connexion : l'adresse d'un nom peut changer entre deux."""
    try:
        check_hostname(host)
        addresses = list(system_resolver(host))
    except ValueError as exc:
        raise CollectorError(EMAIL_SOURCE, f"serveur refusé : {exc}") from None
    except OSError:
        raise NetworkError(EMAIL_SOURCE, "serveur introuvable") from None
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise CollectorError(EMAIL_SOURCE, "serveur refusé : adresse non publique")


class MailboxIn(BaseModel):
    """Remplacement des réglages ; `password` absent = on garde celui déjà enregistré."""

    model_config = ConfigDict(extra="forbid")

    host: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=253)]
    port: StrictInt = IMAPS_PORT
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=254)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    folder: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] = "INBOX"

    @field_validator("host", "username", "password", "folder")
    @classmethod
    def _plain(cls, value: str | None) -> str | None:
        return None if value is None else _no_control(value)

    @field_validator("port")
    @classmethod
    def _port(cls, value: int) -> int:
        if value != IMAPS_PORT:
            raise ValueError("seul le port 993 (IMAP sécurisé) est accepté")
        return value


class Mailbox(BaseModel):
    configured: bool
    host: str | None = None
    port: int | None = None
    username: str | None = None
    folder: str | None = None
    updated_at: dt.datetime | None = None
    last_test_at: dt.datetime | None = None
    last_test_ok: bool | None = None
    last_test_error: str | None = None


class MailboxTest(BaseModel):
    ok: bool
    message: str
    tested_at: dt.datetime


COLUMNS = "host, port, username, folder, updated_at, last_test_at, last_test_ok, last_test_error"


def read_mailbox(conn: Connection) -> dict:
    row = conn.execute(text(f"SELECT {COLUMNS} FROM email_boxes")).mappings().first()
    return {"configured": True, **row} if row else {"configured": False}


@router.get("/sources/email/mailbox", response_model=Mailbox, operation_id="getMailbox",
            response_model_exclude_none=True)
def get_mailbox(session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        return read_mailbox(conn)


@router.put("/sources/email/mailbox", response_model=Mailbox, operation_id="updateMailbox",
            response_model_exclude_none=True)
def update_mailbox(body: MailboxIn, session: Session = Depends(require_csrf)):
    try:
        ensure_public_host(body.host)
    except NetworkError:
        pass  # DNS momentanément indisponible ou nom inconnu : le test de connexion le dira
    except CollectorError as exc:
        raise ApiError(422, "validation_error", exc.message[0].upper() + exc.message[1:] + ".") from None
    with user_scope(session.user_id) as conn:
        existing = conn.execute(text("SELECT password_enc FROM email_boxes")).first()
        if body.password is None and existing is None:
            raise ApiError(422, "validation_error", "Le mot de passe d'application est obligatoire.")
        encrypted = encrypt(body.password) if body.password is not None else existing.password_enc
        conn.execute(
            text("INSERT INTO email_boxes (user_id, host, port, username, password_enc, folder) "
                 "VALUES (:uid, :host, :port, :username, :pw, :folder) "
                 "ON CONFLICT (user_id) DO UPDATE SET host = EXCLUDED.host, port = EXCLUDED.port, "
                 "username = EXCLUDED.username, password_enc = EXCLUDED.password_enc, folder = EXCLUDED.folder, "
                 "updated_at = now(), last_test_at = NULL, last_test_ok = NULL, last_test_error = NULL"),
            {"uid": session.user_id, "host": body.host, "port": body.port, "username": body.username,
             "pw": encrypted, "folder": body.folder},
        )
        return read_mailbox(conn)


@router.delete("/sources/email/mailbox", status_code=204, operation_id="deleteMailbox")
def delete_mailbox(session: Session = Depends(require_csrf)):
    with user_scope(session.user_id) as conn:
        conn.execute(text("DELETE FROM email_boxes"))
        conn.execute(text("UPDATE source_settings SET enabled = false WHERE source = :s"), {"s": EMAIL_SOURCE})
    return Response(status_code=204)


@router.post("/sources/email/mailbox/test", response_model=MailboxTest, operation_id="testMailbox")
def test_mailbox(session: Session = Depends(require_csrf)):
    with user_scope(session.user_id) as conn:
        row = conn.execute(
            text("SELECT host, port, username, password_enc, folder, "
                 "(last_test_at > now() - make_interval(secs => :cool)) AS too_soon FROM email_boxes"),
            {"cool": TEST_COOLDOWN_SECONDS},
        ).mappings().first()
        if row is None:
            raise ApiError(404, "not_found", "Aucune boîte enregistrée.")
        if row["too_soon"]:
            raise ApiError(429, "too_many_requests", "Patientez quelques secondes avant un nouveau test.")
        # Le créneau est pris avant la connexion : deux clics rapprochés ne lancent qu'un test.
        conn.execute(text("UPDATE email_boxes SET last_test_at = now()"))
    try:
        password = decrypt(row["password_enc"])
        ensure_public_host(row["host"])
        connect_imap(row["host"], row["username"], password, row["port"], row["folder"]).close()
        ok, message = True, "Connexion réussie : la boîte et le dossier sont lisibles."
    except ValueError:
        ok, message = False, UNREADABLE
    except CollectorError as exc:  # messages fixes : jamais l'identifiant ni la réponse du serveur
        ok, message = False, exc.message[0].upper() + exc.message[1:] + "."
    now = dt.datetime.now(dt.UTC)
    with user_scope(session.user_id) as conn:
        conn.execute(
            text("UPDATE email_boxes SET last_test_at = :now, last_test_ok = :ok, last_test_error = :err"),
            {"now": now, "ok": ok, "err": None if ok else message[:200]},
        )
    return {"ok": ok, "message": message, "tested_at": now}


# --- Collecte par le worker ---------------------------------------------------------------------


def email_collector(conn: Connection) -> Collector | None:
    """Collecteur de la boîte de l'utilisateur courant (RLS) ; None s'il n'en a pas enregistré."""
    row = conn.execute(text("SELECT host, port, username, password_enc, folder FROM email_boxes")).first()
    if row is None:
        return None

    def connect() -> MailClient:
        try:
            password = decrypt(row.password_enc)
        except ValueError:
            raise CollectorError(EMAIL_SOURCE, UNREADABLE) from None
        ensure_public_host(row.host)
        return connect_imap(row.host, row.username, password, row.port, row.folder)

    return EmailCollector(connect=connect)
