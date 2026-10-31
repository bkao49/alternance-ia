"""Routes du CV déposé : dépôt, état, téléchargement signé, suppression (menace T15, issue #41).

Le fichier reste en base (voir la migration 0010). Les données du CV ne sont jamais journalisées.
"""

import datetime as dt
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy import text
from starlette.datastructures import UploadFile

from app.auth import Session, current_session, require_csrf
from app.config import get_settings
from app.cv.files import MAX_BYTES, MIME, Rejected, check_file
from app.cv.parse import propose_facts
from app.cv.sandbox import ExtractionFailed, extract_text
from app.db import user_scope
from app.errors import ApiError
from app.profile import MAX_FACTS

router = APIRouter(tags=["profile"])
logger = logging.getLogger("app.cv")

UPLOADS_PER_HOUR = 5
LINK_SECONDS = 60
STALE_SECONDS = 180  # extraction « en cours » depuis plus longtemps : le processus a été interrompu
MULTIPART_OVERHEAD = 64 * 1024
COLUMNS = "id, original_name, file_type, size_bytes, status, error_code, facts_proposed, created_at"
REASONS = {"too_large": (413, "file_too_large", "Le fichier dépasse 5 Mo"),
           "empty": (415, "unsupported_file", "Le fichier est vide")}


class CvOut(BaseModel):
    id: uuid.UUID
    original_name: str
    file_type: Literal["pdf", "docx"]
    size_bytes: int
    status: Literal["processing", "done", "failed"]
    error_code: Literal["encrypted", "too_many_pages", "no_text", "timeout", "unreadable"] | None
    facts_proposed: int
    created_at: dt.datetime


class DownloadLink(BaseModel):
    url: str
    expires_at: dt.datetime


def _no_cv() -> ApiError:
    return ApiError(404, "not_found", "Aucun CV déposé")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="cv-download")


async def _read_upload(request: Request) -> tuple[bytes, str | None]:
    """Lit le fichier sans jamais en garder plus que la limite (la taille annoncée est vérifiée avant)."""
    try:
        announced = int(request.headers.get("content-length", ""))
    except ValueError:
        raise ApiError(422, "validation_error", "Taille du dépôt inconnue") from None
    if announced > MAX_BYTES + MULTIPART_OVERHEAD:
        raise ApiError(413, "file_too_large", "Le fichier dépasse 5 Mo")
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise ApiError(415, "unsupported_file", "Envoyez un formulaire multipart avec le champ « file »")
    try:
        form = await request.form(max_files=1, max_fields=1)
    except Exception:  # noqa: BLE001  multipart illisible ou trop de parties : jamais de détail renvoyé
        raise ApiError(422, "validation_error", "Formulaire illisible") from None
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or len(form) != 1:
        raise ApiError(422, "validation_error", "Un seul champ « file » est attendu")
    return await upload.read(MAX_BYTES + 1), upload.filename


def _store(user_id: str, data: bytes, file_type: str, name: str) -> dict:
    with user_scope(user_id) as conn:
        # Verrou par utilisateur : deux dépôts simultanés ne dépassent pas le quota.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('cv:' || :uid, 0))"), {"uid": user_id})
        conn.execute(text("DELETE FROM cv_uploads WHERE created_at < now() - interval '1 day'"))
        recent = conn.execute(text("SELECT count(*) FROM cv_uploads WHERE created_at > now() - interval '1 hour'")
                              ).scalar_one()
        if recent >= UPLOADS_PER_HOUR:
            raise ApiError(429, "too_many_uploads", "Trop de dépôts, réessayez plus tard",
                           headers={"Retry-After": "3600"})
        conn.execute(text("INSERT INTO cv_uploads (user_id) VALUES (:uid)"), {"uid": user_id})
        row = conn.execute(
            text("INSERT INTO cv_documents (user_id, original_name, file_type, size_bytes, content) "
                 "VALUES (:uid, :name, :type, :size, :content) "
                 "ON CONFLICT (user_id) DO UPDATE SET original_name = :name, file_type = :type, "
                 "size_bytes = :size, content = :content, status = 'processing', error_code = NULL, "
                 "facts_proposed = 0, created_at = now(), updated_at = now() "
                 f"RETURNING {COLUMNS}, updated_at"),
            {"uid": user_id, "name": name, "type": file_type, "size": len(data), "content": data},
        ).mappings().one()
        # Après l'écriture : des faits d'une extraction qui venait de finir partent aussi.
        conn.execute(text("DELETE FROM profile_facts WHERE status = 'proposed' AND cv_document_id IS NOT NULL"))
    return dict(row)


def _process(user_id: str, cv_id: str, version: dt.datetime) -> None:
    """Tâche de fond : extraction isolée du texte, puis état final. `version` écarte un dépôt plus ancien."""
    with user_scope(user_id) as conn:
        row = conn.execute(text("SELECT file_type, content FROM cv_documents WHERE id = :id AND updated_at = :v"),
                           {"id": cv_id, "v": version}).first()
    if row is None:
        return
    status, error, facts = "done", None, []
    try:
        # Règles locales seulement : le texte du CV ne quitte jamais cette machine et n'est jamais une consigne.
        facts = propose_facts(extract_text(bytes(row.content), row.file_type))
    except ExtractionFailed as failure:
        status, error = "failed", failure.code
    except Exception:
        logger.exception("extraction du CV interrompue")
        status, error = "failed", "unreadable"
    try:
        _finish(user_id, cv_id, version, status, error, facts)
    except Exception:
        logger.exception("enregistrement des faits du CV impossible")
        with user_scope(user_id) as conn:  # le dépôt ne reste jamais « en cours »
            conn.execute(text("UPDATE cv_documents SET status = 'failed', error_code = 'unreadable', "
                              "facts_proposed = 0, updated_at = now() WHERE id = :id AND updated_at = :v"),
                         {"id": cv_id, "v": version})


def _finish(user_id: str, cv_id: str, version: dt.datetime, status: str, error: str | None, facts: list) -> None:
    with user_scope(user_id) as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('facts:' || :uid, 0))"), {"uid": user_id})
        # Un seul plafond, sur les faits validés (les seuls qui servent) : les faits à relire ne l'entament pas.
        room = max(0, MAX_FACTS - conn.execute(
            text("SELECT count(*) FROM profile_facts WHERE status = 'validated'")).scalar_one())
        known = {(r.kind, r.text.lower()) for r in conn.execute(text("SELECT kind, text FROM profile_facts"))}
        facts = [f for f in facts if (f.kind, f.text.lower()) not in known][:room]
        updated = conn.execute(
            text("UPDATE cv_documents SET status = :s, error_code = :e, facts_proposed = :n, updated_at = now() "
                 "WHERE id = :id AND updated_at = :v RETURNING id"),
            {"s": status, "e": error, "n": len(facts), "id": cv_id, "v": version}).first()
        if updated is None:  # un dépôt plus récent a remplacé celui-ci pendant l'extraction
            return
        for fact in facts:  # toujours « proposed » : rien n'est utilisé avant la validation de l'utilisateur
            conn.execute(
                text("INSERT INTO profile_facts (user_id, kind, text, start_date, end_date, technologies, source, "
                     "status, cv_document_id) VALUES (:uid, :kind, :text, :start, :end, :tech, 'CV', 'proposed', :cv)"),
                {"uid": user_id, "kind": fact.kind, "text": fact.text, "start": fact.start_date,
                 "end": fact.end_date, "tech": fact.technologies, "cv": cv_id})


@router.post("/profile/cv", response_model=CvOut, status_code=202, operation_id="uploadProfileCv")
async def upload_cv(request: Request, background: BackgroundTasks, session: Session = Depends(require_csrf)):
    data, raw_name = await _read_upload(request)
    try:
        checked = check_file(data, raw_name)
    except Rejected as rejected:
        status, code, message = REASONS.get(rejected.reason, (415, "unsupported_file",
                                                              "Seuls les PDF et DOCX sans contenu actif sont acceptés"))
        raise ApiError(status, code, message) from None
    row = await run_in_threadpool(_store, session.user_id, data, checked.file_type, checked.name)
    background.add_task(_process, session.user_id, str(row["id"]), row["updated_at"])
    return row


@router.get("/profile/cv", response_model=CvOut, operation_id="getProfileCv")
def get_cv(session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        conn.execute(text("UPDATE cv_documents SET status = 'failed', error_code = 'timeout' "
                          "WHERE status = 'processing' AND updated_at < now() - make_interval(secs => :s)"),
                     {"s": STALE_SECONDS})
        row = conn.execute(text(f"SELECT {COLUMNS} FROM cv_documents")).mappings().first()
    if row is None:
        raise _no_cv()
    return dict(row)


@router.delete("/profile/cv", status_code=204, operation_id="deleteProfileCv")
def delete_cv(session: Session = Depends(require_csrf)) -> None:
    with user_scope(session.user_id) as conn:
        # Les faits venus de ce CV partent avec lui (clé étrangère ON DELETE CASCADE).
        deleted = conn.execute(text("DELETE FROM cv_documents")).rowcount
    if not deleted:
        raise _no_cv()


@router.post("/profile/cv/download-link", response_model=DownloadLink, operation_id="createProfileCvDownloadLink")
def create_download_link(session: Session = Depends(require_csrf)):
    with user_scope(session.user_id) as conn:
        cv_id = conn.execute(text("SELECT id FROM cv_documents")).scalar()
    if cv_id is None:
        raise _no_cv()
    token = _serializer().dumps({"u": session.user_id, "c": str(cv_id)})
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=LINK_SECONDS)
    return {"url": f"/profile/cv/file/{token}", "expires_at": expires}


@router.get("/profile/cv/file/{token}", operation_id="downloadProfileCv", response_class=Response)
def download_cv(token: str, session: Session = Depends(current_session)):
    try:
        claim = _serializer().loads(token, max_age=LINK_SECONDS)
        valid = isinstance(claim, dict) and claim.get("u") == session.user_id
    except BadSignature:
        valid = False
    if not valid:  # expiré, falsifié ou délivré à un autre utilisateur : même réponse
        raise _no_cv()
    with user_scope(session.user_id) as conn:
        row = conn.execute(text("SELECT file_type, content FROM cv_documents WHERE id = :id"),
                           {"id": claim["c"]}).first()
    if row is None:
        raise _no_cv()
    return Response(bytes(row.content), media_type=MIME[row.file_type], headers={
        "Content-Disposition": f'attachment; filename="cv.{row.file_type}"',  # nom fixe, jamais celui du déposant
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox"})
