import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import Session, current_session
from app.common import PageParams, page_of, page_params
from app.db import user_scope
from app.errors import ApiError

router = APIRouter(tags=["offers"])

# Dernier score de chaque offre (le plus récent ; id départage deux scores simultanés).
# Sous RLS : ne voit que les scores de l'utilisateur courant.
LATEST_SCORE = """
    SELECT DISTINCT ON (job_posting_id) job_posting_id, value, confidence, explanation, criteria, blocking_reasons
    FROM scores ORDER BY job_posting_id, created_at DESC, id
"""

OFFER_COLUMNS = ("o.id, o.title, o.company, o.location, o.source, o.url, o.detected_at, o.expired, "
                 "o.contract_type")
ContractType = Literal["internship", "apprenticeship", "fixed_term", "permanent", "other"]

SORTS = {
    "score_desc": "ls.value DESC NULLS LAST, o.detected_at DESC, o.id",
    "detected_desc": "o.detected_at DESC, o.id",
    "title_asc": "lower(o.title), o.id",
}


class OfferOut(BaseModel):
    id: uuid.UUID
    title: str
    company: str
    location: str | None = None
    source: str
    url: str
    detected_at: dt.datetime
    expired: bool
    contract_type: ContractType | None = None
    score: float | None = None
    explanation: str | None = None


def _offer(row: Any) -> dict:
    """Champs optionnels du contrat (location, score) : absents plutôt que null."""
    data = OfferOut(
        id=row["id"], title=row["title"], company=row["company"], location=row["location"],
        source=row["source"], url=row["url"], detected_at=row["detected_at"], expired=row["expired"],
        contract_type=row["contract_type"], score=float(row["score"]) if row["score"] is not None else None,
        explanation=row.get("explanation"),
    ).model_dump(mode="json")
    return {key: value for key, value in data.items() if value is not None}


@router.get("/offers", operation_id="listOffers")
def list_offers(
    q: str | None = Query(default=None, max_length=200),
    min_score: float | None = Query(default=None, ge=0, le=5),
    source: str | None = Query(default=None, max_length=100),
    contract_type: Annotated[list[ContractType] | None, Query()] = None,
    include_expired: bool = False,
    sort: Literal["score_desc", "detected_desc", "title_asc"] = "score_desc",
    params: PageParams = Depends(page_params),
    session: Session = Depends(current_session),
):
    where, args = ["TRUE"], {"limit": params.page_size, "offset": params.offset}
    if q:
        where.append("(o.title ILIKE :q ESCAPE '!' OR o.company ILIKE :q ESCAPE '!')")
        escaped = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")  # % et _ restent littéraux
        args["q"] = f"%{escaped}%"
    if min_score is not None:
        where.append("ls.value >= :min_score")  # une offre sans score ne passe jamais ce filtre
        args["min_score"] = min_score
    if source:
        where.append("o.source = :source")
        args["source"] = source
    if contract_type:  # une offre sans type connu ne passe jamais ce filtre
        where.append("o.contract_type = ANY(CAST(:contract_types AS text[]))")
        args["contract_types"] = contract_type
    if not include_expired:
        where.append("NOT o.expired")
    base = f"FROM job_postings o LEFT JOIN ({LATEST_SCORE}) ls ON ls.job_posting_id = o.id WHERE " + " AND ".join(where)
    with user_scope(session.user_id) as conn:
        total = conn.execute(text("SELECT count(*) " + base), args).scalar_one()
        rows = conn.execute(
            text(f"SELECT {OFFER_COLUMNS}, ls.value AS score, ls.explanation {base} ORDER BY {SORTS[sort]} LIMIT :limit OFFSET :offset"),
            args,
        ).mappings().all()
    return page_of([_offer(r) for r in rows], total, params)


@router.get("/offers/{offer_id}", operation_id="getOffer")
def get_offer(offer_id: uuid.UUID, session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        row = conn.execute(
            text(
                f"SELECT {OFFER_COLUMNS}, o.description_text, ls.value AS score, ls.confidence, ls.explanation, "
                "ls.criteria, ls.blocking_reasons, (SELECT a.extraction ->> 'summary' FROM analyses a "
                "WHERE a.job_posting_id = o.id ORDER BY a.created_at DESC, a.id LIMIT 1) AS analysis_summary "
                f"FROM job_postings o LEFT JOIN ({LATEST_SCORE}) ls ON ls.job_posting_id = o.id WHERE o.id = :id"
            ),
            {"id": str(offer_id)},
        ).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Offre introuvable")
    detail = _offer(row)
    detail["description_text"] = row["description_text"]  # donnée non fiable : renvoyée telle quelle
    if row["analysis_summary"] is not None:
        detail["analysis_summary"] = row["analysis_summary"]
    if row["score"] is not None:
        score = {
            "value": float(row["score"]), "confidence": row["confidence"],
            "blocking_reasons": row["blocking_reasons"], "criteria": row["criteria"],
        }
        if row["explanation"] is not None:
            score["explanation"] = row["explanation"]
        detail["score_detail"] = score
    return detail
