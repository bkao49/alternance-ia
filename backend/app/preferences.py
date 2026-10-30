import datetime as dt
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import text

from app.auth import Session, current_session, require_csrf
from app.db import user_scope

router = APIRouter(tags=["preferences"])

ContractType = Literal["internship", "apprenticeship", "fixed_term", "permanent", "other"]
EducationLevel = Literal["bac", "bac_plus_2", "bac_plus_3", "bac_plus_4", "bac_plus_5", "doctorate", "other"]
Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]

COLUMNS = ("keywords, locations, remote_accepted, contract_types, start_date, duration_months, "
           "alternance_rhythm, education_level, min_salary_eur, excluded_keywords, updated_at")


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    radius_km: int = Field(ge=0, le=200)


class PreferencesIn(BaseModel):
    """Remplacement complet : aucun champ n'a de valeur par défaut (le contrat les exige tous)."""

    model_config = ConfigDict(extra="forbid")

    keywords: list[Keyword] = Field(max_length=20)
    locations: list[Location] = Field(max_length=10)
    remote_accepted: bool
    contract_types: list[ContractType]
    start_date: dt.date | None
    duration_months: Annotated[int, Field(ge=1, le=60)] | None
    alternance_rhythm: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None
    education_level: EducationLevel | None
    min_salary_eur: Annotated[int, Field(ge=0, le=1_000_000)] | None
    excluded_keywords: list[Keyword] = Field(max_length=50)

    @field_validator("keywords", "contract_types", "excluded_keywords")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("valeurs en double")
        return value

    @field_validator("locations")
    @classmethod
    def _unique_locations(cls, value: list[Location]) -> list[Location]:
        if len({(loc.label, loc.radius_km) for loc in value}) != len(value):
            raise ValueError("lieux en double")
        return value

    @field_validator("alternance_rhythm")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None


class PreferencesOut(PreferencesIn):
    model_config = ConfigDict(extra="ignore")

    updated_at: dt.datetime | None


EMPTY = {"keywords": [], "locations": [], "remote_accepted": False, "contract_types": [],
         "start_date": None, "duration_months": None, "alternance_rhythm": None,
         "education_level": None, "min_salary_eur": None, "excluded_keywords": [], "updated_at": None}


@router.get("/preferences", response_model=PreferencesOut, operation_id="getPreferences")
def get_preferences(session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        row = conn.execute(text(f"SELECT {COLUMNS} FROM search_preferences")).mappings().first()
    return dict(row) if row else EMPTY


@router.put("/preferences", response_model=PreferencesOut, operation_id="updatePreferences")
def update_preferences(body: PreferencesIn, session: Session = Depends(require_csrf)):
    values = body.model_dump()
    values["locations"] = json.dumps(values["locations"])
    with user_scope(session.user_id) as conn:
        row = conn.execute(
            text(
                "INSERT INTO search_preferences (user_id, keywords, locations, remote_accepted, contract_types, "
                "start_date, duration_months, alternance_rhythm, education_level, min_salary_eur, "
                "excluded_keywords) VALUES (:uid, :keywords, CAST(:locations AS jsonb), :remote_accepted, "
                ":contract_types, :start_date, :duration_months, :alternance_rhythm, :education_level, "
                ":min_salary_eur, :excluded_keywords) "
                "ON CONFLICT (user_id) DO UPDATE SET keywords = EXCLUDED.keywords, "
                "locations = EXCLUDED.locations, remote_accepted = EXCLUDED.remote_accepted, "
                "contract_types = EXCLUDED.contract_types, start_date = EXCLUDED.start_date, "
                "duration_months = EXCLUDED.duration_months, alternance_rhythm = EXCLUDED.alternance_rhythm, "
                "education_level = EXCLUDED.education_level, min_salary_eur = EXCLUDED.min_salary_eur, "
                f"excluded_keywords = EXCLUDED.excluded_keywords, updated_at = now() RETURNING {COLUMNS}"
            ),
            {"uid": session.user_id, **values},
        ).mappings().one()
    return dict(row)
