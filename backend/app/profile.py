import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text

from app.auth import Session, current_session, require_csrf
from app.db import user_scope
from app.errors import ApiError
from app.preferences import text_field

router = APIRouter(tags=["profile"])

FactKind = Literal["experience", "education", "project", "skill", "certification", "language", "other"]
MAX_FACTS = 500
COLUMNS = "id, kind, text, start_date, end_date, technologies, source, created_at"
ORDER = "ORDER BY start_date DESC NULLS LAST, created_at DESC, id"


class FactIn(BaseModel):
    """Remplacement complet : aucun champ n'a de valeur par défaut (le contrat les exige tous)."""

    model_config = ConfigDict(extra="forbid")

    kind: FactKind
    text: text_field(1000)
    start_date: dt.date | None
    end_date: dt.date | None
    technologies: list[text_field(60)] = Field(max_length=30)
    source: text_field(120) | None

    @field_validator("technologies")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("valeurs en double")
        return value

    @model_validator(mode="after")
    def _dates_in_order(self) -> "FactIn":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date précède start_date")
        return self


class FactOut(FactIn):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    created_at: dt.datetime


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Fait introuvable")


@router.get("/profile/facts", response_model=list[FactOut], operation_id="listProfileFacts")
def list_facts(kind: FactKind | None = None, session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        rows = conn.execute(
            text(f"SELECT {COLUMNS} FROM profile_facts WHERE CAST(:kind AS text) IS NULL OR kind = :kind {ORDER}"),
            {"kind": kind},
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/profile/facts", response_model=FactOut, status_code=201, operation_id="createProfileFact")
def create_fact(body: FactIn, session: Session = Depends(require_csrf)):
    with user_scope(session.user_id) as conn:
        # Verrou par utilisateur : deux ajouts simultanés ne dépassent pas la limite.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('facts:' || :uid))"), {"uid": session.user_id})
        if conn.execute(text("SELECT count(*) FROM profile_facts")).scalar() >= MAX_FACTS:
            raise ApiError(409, "too_many_facts", f"{MAX_FACTS} faits au plus")
        row = conn.execute(
            text("INSERT INTO profile_facts (user_id, kind, text, start_date, end_date, technologies, source) "
                 "VALUES (:uid, :kind, :text, :start_date, :end_date, :technologies, :source) "
                 f"RETURNING {COLUMNS}"),
            {"uid": session.user_id, **body.model_dump()},
        ).mappings().one()
    return dict(row)


@router.put("/profile/facts/{fact_id}", response_model=FactOut, operation_id="updateProfileFact")
def update_fact(fact_id: uuid.UUID, body: FactIn, session: Session = Depends(require_csrf)):
    with user_scope(session.user_id) as conn:
        row = conn.execute(
            text("UPDATE profile_facts SET kind = :kind, text = :text, start_date = :start_date, "
                 "end_date = :end_date, technologies = :technologies, source = :source "
                 f"WHERE id = :id RETURNING {COLUMNS}"),
            {"id": str(fact_id), **body.model_dump()},
        ).mappings().first()
    if row is None:
        raise _not_found()
    return dict(row)


@router.delete("/profile/facts/{fact_id}", status_code=204, operation_id="deleteProfileFact")
def delete_fact(fact_id: uuid.UUID, session: Session = Depends(require_csrf)) -> None:
    with user_scope(session.user_id) as conn:
        deleted = conn.execute(text("DELETE FROM profile_facts WHERE id = :id"), {"id": str(fact_id)}).rowcount
    if not deleted:
        raise _not_found()
