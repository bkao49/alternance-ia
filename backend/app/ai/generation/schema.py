"""Forme d'un texte généré : des sections, chacune faite de lignes qui citent les faits dont elles viennent."""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
SectionName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
MAX_SECTIONS = 12
MAX_BULLETS = 30
MAX_FACT_IDS = 20


class Bullet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texte: Line
    fact_ids: list[uuid.UUID] = Field(max_length=MAX_FACT_IDS)  # vide = ligne non justifiée, que le contrôle rejette


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: SectionName
    bullets: list[Bullet] = Field(max_length=MAX_BULLETS)


@dataclass(frozen=True)
class Fact:
    """Un fait du profil tel que le contrôle le voit (copie en lecture seule d'une ligne de `profile_facts`)."""

    id: str
    kind: str
    text: str
    start_date: dt.date | None
    end_date: dt.date | None
    technologies: tuple[str, ...]
    source: str | None
    status: str  # « validated » ou « proposed » : seuls les faits validés justifient une ligne
