"""Extraction structurée d'une annonce : texte libre → JSON validé, via la passerelle LLM uniquement.

L'extraction ne voit jamais le profil de l'utilisateur : la fonction n'en reçoit aucun champ et
l'appel est étiqueté `JOB_POSTING`. Le texte de l'annonce est une donnée non fiable (la passerelle
l'encadre) et la réponse du modèle aussi : elle n'est acceptée que si elle respecte le schéma strict.
"""

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import text

from app.ai.gateway import DataKind, GatewayError, LLMGateway
from app.ai.matching.filters import OfferView
from app.db import user_scope

PROMPT_VERSION = "extraction-v1"  # à changer avec le schéma ou les consignes : les anciennes analyses sont refaites
MAX_ATTEMPTS = 2  # une première réponse, puis une nouvelle tentative si elle est invalide
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]

INSTRUCTIONS = f"""Tu extrais les exigences d'une annonce d'emploi. Réponds par UN SEUL objet JSON, sans texte
autour, avec exactement ces clés (null si l'annonce ne le dit pas, jamais d'invention) :
- "skills": liste (30 au plus) de compétences ou technologies demandées, courtes ;
- "education_level": "bac", "bac_plus_2", "bac_plus_3", "bac_plus_4", "bac_plus_5", "doctorate", "other" ou null ;
- "duration_months": entier de 1 à 60 ou null ;
- "contract_type": "internship", "apprenticeship", "fixed_term", "permanent", "other" ou null ;
- "location": lieu de travail (texte court) ou null ;
- "remote": "none", "partial", "full" ou null ;
- "salary_eur_year": salaire brut annuel en euros (entier) ou null ;
- "start_date": date de début "AAAA-MM-JJ" ou null ;
- "summary": résumé neutre en une phrase (400 caractères au plus) ou null.
Version du format : {PROMPT_VERSION}."""
RETRY_NOTE = ("\nTa réponse précédente n'était pas un objet JSON valide pour ce format. "
              "Réponds uniquement par l'objet JSON demandé.")


class Extraction(BaseModel):
    """Schéma strict : toute clé inconnue, valeur hors liste ou type inexact fait rejeter la réponse."""

    model_config = ConfigDict(extra="forbid", strict=True)

    skills: list[Short] = Field(max_length=30)
    education_level: Literal["bac", "bac_plus_2", "bac_plus_3", "bac_plus_4", "bac_plus_5", "doctorate",
                             "other"] | None
    duration_months: Annotated[int, Field(ge=1, le=60)] | None
    contract_type: Literal["internship", "apprenticeship", "fixed_term", "permanent", "other"] | None
    location: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None
    remote: Literal["none", "partial", "full"] | None
    salary_eur_year: Annotated[int, Field(ge=0, le=1_000_000)] | None
    start_date: dt.date | None
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)] | None


class ExtractionError(Exception):
    """Aucune réponse valide après les tentatives (ou passerelle en échec)."""


@dataclass(frozen=True)
class ExtractionResult:
    extraction: Extraction
    analysis_id: str
    reused: bool  # True : analyse déjà faite pour ce texte, aucun appel au modèle


def parse_extraction(raw: str) -> Extraction:
    body = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.DOTALL)
    return Extraction.model_validate_json(fenced.group(1) if fenced else body)


def fingerprint(title: str, location: str | None, description: str) -> str:
    """Empreinte de ce que le modèle voit : une même annonce n'est analysée qu'une fois."""
    return hashlib.sha256(json.dumps([title, location, description]).encode()).hexdigest()


def to_offer_view(posting: dict, extraction: Extraction | None) -> OfferView:
    """Réunit les colonnes de `job_postings` et l'extraction pour les filtres durs."""
    view = OfferView(title=posting["title"], description=posting["description_text"],
                     location=posting["location"], expired=posting["expired"])
    if extraction is None:
        return view
    return OfferView(
        title=view.title, description=view.description, location=extraction.location or view.location,
        expired=view.expired, contract_type=extraction.contract_type, start_date=extraction.start_date,
        education_level=extraction.education_level,
        remote=None if extraction.remote is None else extraction.remote == "full",
        salary_eur=extraction.salary_eur_year)


def _find(conn, posting_id: str, digest: str):
    return conn.execute(text(
        "SELECT id, extraction FROM analyses WHERE job_posting_id = :id AND prompt_version = :v "
        "AND extraction ->> 'content_hash' = :h ORDER BY created_at DESC, id LIMIT 1"),
        {"id": posting_id, "v": PROMPT_VERSION, "h": digest}).mappings().first()


def _stored(row) -> Extraction:
    stored = {k: v for k, v in row["extraction"].items() if k != "content_hash"}
    return Extraction.model_validate(stored, strict=False)  # déjà validée : la date revient en texte


def extract_offer(gateway: LLMGateway, user_id: str, posting_id: str) -> ExtractionResult:
    with user_scope(user_id) as conn:
        posting = conn.execute(text(
            "SELECT title, location, description_text FROM job_postings WHERE id = :id"),
            {"id": posting_id}).mappings().first()
        if posting is None:
            raise ExtractionError("offre introuvable")
        digest = fingerprint(posting["title"], posting["location"], posting["description_text"])
        known = _find(conn, posting_id, digest)
    if known is not None:
        return ExtractionResult(_stored(known), str(known["id"]), reused=True)

    data = f"Titre : {posting['title']}\nLieu : {posting['location'] or 'non précisé'}\n\n{posting['description_text']}"
    extraction = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            reply = gateway.call(user_id, purpose="extract_offer", kind=DataKind.JOB_POSTING,
                                 instructions=INSTRUCTIONS + (RETRY_NOTE * attempt), data=data,
                                 max_output_tokens=800)
        except GatewayError as error:
            raise ExtractionError(error.code) from None  # budget, fournisseur refusé ou en échec
        try:
            extraction = parse_extraction(reply.text)
            break
        except ValidationError:
            continue  # le détail contient la réponse du modèle : on ne le garde pas
    if extraction is None:
        raise ExtractionError("réponse du modèle invalide après nouvelle tentative")

    stored = {**extraction.model_dump(mode="json"), "content_hash": digest}
    with user_scope(user_id) as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('extract:' || :id))"), {"id": posting_id})
        known = _find(conn, posting_id, digest)  # une extraction concurrente a pu finir entre-temps
        if known is not None:
            return ExtractionResult(_stored(known), str(known["id"]), reused=True)
        analysis_id = conn.execute(text(
            "INSERT INTO analyses (user_id, job_posting_id, extraction, prompt_version) "
            "VALUES (:uid, :id, CAST(:extraction AS jsonb), :v) RETURNING id"),
            {"uid": user_id, "id": posting_id, "extraction": json.dumps(stored), "v": PROMPT_VERSION},
        ).scalar_one()
    return ExtractionResult(extraction, str(analysis_id), reused=False)
