import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import Session, current_session, require_csrf
from app.db import user_scope
from app.errors import ApiError

router = APIRouter(tags=["statuses"])

DEFAULT_COLOR = "#4f46e5"
COLUMNS = "id, name, position, color, system_key"


class StatusOut(BaseModel):
    id: uuid.UUID
    name: str
    position: int
    color: str
    system_key: str | None


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # system_key n'est jamais modifiable

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    position: int | None = Field(default=None, ge=1, le=1000)


def _name_taken() -> ApiError:
    return ApiError(409, "status_name_taken", "Un statut porte déjà ce nom")


@router.get("/statuses", response_model=list[StatusOut], operation_id="listStatuses")
def list_statuses(session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        rows = conn.execute(text(f"SELECT {COLUMNS} FROM status_definitions ORDER BY position, name")).mappings().all()
    return [dict(r) for r in rows]


@router.post("/statuses", response_model=StatusOut, status_code=201, operation_id="createStatus")
def create_status(body: StatusIn, session: Session = Depends(require_csrf)):
    try:
        with user_scope(session.user_id) as conn:
            row = conn.execute(
                text(
                    "INSERT INTO status_definitions (user_id, name, position, color) VALUES (:uid, :name, "
                    "COALESCE(:position, (SELECT COALESCE(MAX(position), 0) + 1 FROM status_definitions)), :color) "
                    f"RETURNING {COLUMNS}"
                ),
                {"uid": session.user_id, "name": body.name.strip(), "position": body.position,
                 "color": body.color or DEFAULT_COLOR},
            ).mappings().one()
    except IntegrityError:
        raise _name_taken() from None
    return dict(row)


@router.patch("/statuses/{status_id}", response_model=StatusOut, operation_id="updateStatus")
def update_status(status_id: uuid.UUID, body: StatusIn, session: Session = Depends(require_csrf)):
    """Les statuts par défaut peuvent être renommés mais jamais supprimés (aucune route de suppression)."""
    try:
        with user_scope(session.user_id) as conn:
            row = conn.execute(
                text(
                    "UPDATE status_definitions SET name = :name, color = COALESCE(:color, color), "
                    f"position = COALESCE(:position, position) WHERE id = :id RETURNING {COLUMNS}"
                ),
                {"id": str(status_id), "name": body.name.strip(), "color": body.color, "position": body.position},
            ).mappings().first()
    except IntegrityError:
        raise _name_taken() from None
    if row is None:
        raise ApiError(404, "not_found", "Statut introuvable")
    return dict(row)
