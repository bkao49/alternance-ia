import datetime as dt
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from app.auth import Session, current_session, require_csrf
from app.common import PageParams, page_of, page_params
from app.db import user_scope
from app.errors import ApiError
from app.statuses import StatusOut

router = APIRouter(tags=["applications"])

SELECT_APPLICATION = """
    SELECT a.id, a.job_posting_id AS offer_id, a.company, a.title, a.notes, a.sent_at,
           a.created_at, a.updated_at,
           s.id AS s_id, s.name AS s_name, s.position AS s_position, s.color AS s_color,
           s.system_key AS s_key
    FROM applications a JOIN status_definitions s ON s.id = a.status_id
"""


class ApplicationOut(BaseModel):
    id: uuid.UUID
    offer_id: uuid.UUID | None
    company: str | None
    title: str | None
    status: StatusOut
    notes: str | None
    sent_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: uuid.UUID | None = None
    company: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    # « Envoyée » est volontairement absent : voir confirm-sent.
    initial_status: Literal["detected", "to_prepare"] = "to_prepare"


class ApplicationUpdate(BaseModel):
    # Interdit tout autre champ : status_id et sent_at ne passent jamais par ici.
    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(default=None, max_length=5000)
    company: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status_id: uuid.UUID
    comment: str | None = Field(default=None, max_length=500)


class ConfirmSent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Accepte n'importe quel type pour répondre 409 (et non 422) à tout ce qui n'est pas exactement
    # `true` : "true", 1 ou "yes" ne comptent pas comme une confirmation.
    confirmed: Any
    comment: str | None = Field(default=None, max_length=500)


class EventOut(BaseModel):
    id: uuid.UUID
    from_status: str | None
    to_status: str
    actor: Literal["user", "system"]
    comment: str | None
    occurred_at: dt.datetime


def _to_application(row) -> dict:
    data = dict(row)
    data["status"] = {
        "id": data.pop("s_id"), "name": data.pop("s_name"), "position": data.pop("s_position"),
        "color": data.pop("s_color"), "system_key": data.pop("s_key"),
    }
    return data


def _fetch(conn: Connection, application_id: uuid.UUID, lock: bool = False) -> dict:
    suffix = " WHERE a.id = :id" + (" FOR UPDATE OF a" if lock else "")
    row = conn.execute(text(SELECT_APPLICATION + suffix), {"id": str(application_id)}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Candidature introuvable")
    return _to_application(row)


def _record_event(conn: Connection, user_id: str, application_id: uuid.UUID, from_status, to_status, comment) -> None:
    conn.execute(
        text(
            "INSERT INTO events (user_id, application_id, from_status_id, to_status_id, actor, comment) "
            "VALUES (:uid, :app, :from_status, :to_status, 'user', :comment)"
        ),
        {"uid": user_id, "app": str(application_id), "from_status": from_status,
         "to_status": to_status, "comment": comment},
    )


def _status_by_key(conn: Connection, key: str):
    row = conn.execute(text("SELECT id FROM status_definitions WHERE system_key = :key"), {"key": key}).first()
    if row is None:
        raise ApiError(409, "status_missing", f"Statut par défaut « {key} » introuvable")
    return row.id


@router.get("/applications", operation_id="listApplications")
def list_applications(
    status_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    params: PageParams = Depends(page_params),
    session: Session = Depends(current_session),
):
    where, args = ["TRUE"], {"limit": params.page_size, "offset": params.offset}
    if status_id:
        where.append("a.status_id = :status_id")
        args["status_id"] = str(status_id)
    if q:
        where.append("(a.company ILIKE :q ESCAPE '!' OR a.title ILIKE :q ESCAPE '!')")
        escaped = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")  # % et _ restent littéraux
        args["q"] = f"%{escaped}%"
    clause = " WHERE " + " AND ".join(where)
    with user_scope(session.user_id) as conn:
        total = conn.execute(text("SELECT count(*) FROM applications a" + clause), args).scalar_one()
        rows = conn.execute(
            text(SELECT_APPLICATION + clause + " ORDER BY a.created_at DESC, a.id LIMIT :limit OFFSET :offset"), args
        ).mappings().all()
    return page_of([ApplicationOut(**_to_application(r)).model_dump(mode="json") for r in rows], total, params)


@router.post("/applications", response_model=ApplicationOut, status_code=201, operation_id="createApplication")
def create_application(body: ApplicationCreate, session: Session = Depends(require_csrf)):
    with user_scope(session.user_id) as conn:
        company, title = body.company, body.title
        offer_id = body.offer_id
        if offer_id:
            offer = conn.execute(
                text("SELECT company, title FROM job_postings WHERE id = :id"), {"id": str(offer_id)}
            ).first()
            if offer is None:
                raise ApiError(404, "not_found", "Offre introuvable")
            company, title = company or offer.company, title or offer.title
        elif not (company and title):
            raise ApiError(422, "validation_error", "Fournir offer_id, ou company et title")
        status_id = _status_by_key(conn, body.initial_status)
        application_id = conn.execute(
            text(
                "INSERT INTO applications (user_id, job_posting_id, company, title, status_id, notes) "
                "VALUES (:uid, :offer, :company, :title, :status, :notes) RETURNING id"
            ),
            {"uid": session.user_id, "offer": str(offer_id) if offer_id else None, "company": company,
             "title": title, "status": status_id, "notes": body.notes},
        ).scalar_one()
        _record_event(conn, session.user_id, application_id, None, status_id, "Candidature créée")
        return _fetch(conn, application_id)


@router.get("/applications/{application_id}", response_model=ApplicationOut, operation_id="getApplication")
def get_application(application_id: uuid.UUID, session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        return _fetch(conn, application_id)


@router.patch("/applications/{application_id}", response_model=ApplicationOut, operation_id="updateApplication")
def update_application(application_id: uuid.UUID, body: ApplicationUpdate, session: Session = Depends(require_csrf)):
    changes = body.model_dump(exclude_unset=True)
    if any(key in changes and changes[key] is None for key in ("company", "title")):
        raise ApiError(422, "validation_error", "company et title ne peuvent pas être vides")
    with user_scope(session.user_id) as conn:
        _fetch(conn, application_id, lock=True)
        if changes:
            assignments = ", ".join(f"{column} = :{column}" for column in changes)  # colonnes issues du modèle
            conn.execute(
                text(f"UPDATE applications SET {assignments}, updated_at = now() WHERE id = :id"),
                {**changes, "id": str(application_id)},
            )
        return _fetch(conn, application_id)


@router.post("/applications/{application_id}/status", response_model=ApplicationOut,
             operation_id="changeApplicationStatus")
def change_status(application_id: uuid.UUID, body: StatusChange, session: Session = Depends(require_csrf)):
    """Refuse « Envoyée » : ce statut ne s'obtient que par confirm-sent (confirmation humaine)."""
    with user_scope(session.user_id) as conn:
        current = _fetch(conn, application_id, lock=True)
        target = conn.execute(
            text("SELECT id, system_key FROM status_definitions WHERE id = :id"), {"id": str(body.status_id)}
        ).first()
        if target is None:
            raise ApiError(404, "not_found", "Statut introuvable")
        if target.system_key == "sent":
            raise ApiError(409, "confirmation_required", "Utiliser la confirmation d'envoi pour passer à « Envoyée »")
        if target.id != current["status"]["id"]:
            conn.execute(
                text("UPDATE applications SET status_id = :status, updated_at = now() WHERE id = :id"),
                {"status": target.id, "id": str(application_id)},
            )
            _record_event(conn, session.user_id, application_id, current["status"]["id"], target.id, body.comment)
        return _fetch(conn, application_id)


@router.post("/applications/{application_id}/confirm-sent", response_model=ApplicationOut,
             operation_id="confirmApplicationSent")
def confirm_sent(application_id: uuid.UUID, body: ConfirmSent, session: Session = Depends(require_csrf)):
    """Seul chemin vers « Envoyée » : l'utilisateur certifie avoir envoyé lui-même la candidature."""
    if body.confirmed is not True:
        raise ApiError(409, "confirmation_required", "Confirmation explicite requise (confirmed: true)")
    with user_scope(session.user_id) as conn:
        current = _fetch(conn, application_id, lock=True)
        if current["status"]["system_key"] == "sent":
            raise ApiError(409, "already_sent", "Cette candidature est déjà marquée comme envoyée")
        sent_id = _status_by_key(conn, "sent")
        conn.execute(
            text(
                "UPDATE applications SET status_id = :status, sent_at = COALESCE(sent_at, now()), "
                "updated_at = now() WHERE id = :id"
            ),
            {"status": sent_id, "id": str(application_id)},
        )
        _record_event(conn, session.user_id, application_id, current["status"]["id"], sent_id,
                      body.comment or "Envoi confirmé par l'utilisateur")
        return _fetch(conn, application_id)


@router.get("/applications/{application_id}/events", operation_id="listApplicationEvents")
def list_events(
    application_id: uuid.UUID,
    params: PageParams = Depends(page_params),
    session: Session = Depends(current_session),
):
    with user_scope(session.user_id) as conn:
        _fetch(conn, application_id)
        total = conn.execute(
            text("SELECT count(*) FROM events WHERE application_id = :id"), {"id": str(application_id)}
        ).scalar_one()
        rows = conn.execute(
            text(
                "SELECT e.id, fs.name AS from_status, ts.name AS to_status, e.actor, e.comment, e.occurred_at "
                "FROM events e LEFT JOIN status_definitions fs ON fs.id = e.from_status_id "
                "JOIN status_definitions ts ON ts.id = e.to_status_id WHERE e.application_id = :id "
                "ORDER BY e.occurred_at DESC, e.id LIMIT :limit OFFSET :offset"
            ),
            {"id": str(application_id), "limit": params.page_size, "offset": params.offset},
        ).mappings().all()
    return page_of([EventOut(**r).model_dump(mode="json") for r in rows], total, params)
