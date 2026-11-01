"""Brouillons de CV et de lettres : génération, édition, versions, contrôle factuel (issues #21 et #22).

Seuls des faits de l'utilisateur (Row Level Security) sont lus. Le contrôle déterministe est refait à
chaque lecture ; le second regard par modèle ne tourne que sur demande (`POST …/check` avec `verify`).
Aucune route d'ici n'envoie quoi que ce soit : l'envoi d'une candidature reste un clic humain (#93).
"""

import json
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, text

from app.ai.gateway import BudgetExceeded, GatewayError, LLMGateway
from app.ai.generation.factcheck import check_document
from app.ai.generation.generate import GenerationError, NotEnoughFacts, OfferInfo, generate_document
from app.ai.generation.schema import MAX_SECTIONS, Bullet, Fact, Line, Section, SectionName
from app.ai.generation.verifier import verify_with_llm
from app.auth import Session, current_session, require_csrf
from app.db import user_scope
from app.errors import ApiError
from app.profile import MAX_FACTS

router = APIRouter(tags=["documents"])

MAX_LINES = 150  # lignes au total par version : borne la taille du texte stocké
MAX_VERSIONS = 100  # au-delà, les plus anciennes sont supprimées
GENERAL_TITLE = "CV général"
MANUAL_SOURCE = "Ajout manuel dans un CV"
FACT_COLUMNS = "id, kind, text, start_date, end_date, technologies, source, status"


def llm_gateway() -> LLMGateway | None:
    """Aucun fournisseur réel n'est encore branché (issue #15) : les tests remplacent cette dépendance."""
    return None


def _need(gateway: LLMGateway | None) -> LLMGateway:
    if gateway is None:
        raise ApiError(503, "llm_not_configured", "Aucun fournisseur d'IA n'est configuré")
    return gateway


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["cv", "cover_letter"]
    offer_id: uuid.UUID | None


class ManualBullet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texte: Line
    fact_ids: list[uuid.UUID] = Field(max_length=20)
    manual: bool = False


class SectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: SectionName
    bullets: list[ManualBullet] = Field(max_length=30)


class SaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=1)
    sections: list[SectionIn] = Field(max_length=MAX_SECTIONS)

    @model_validator(mode="after")
    def _bounded(self) -> "SaveIn":
        if sum(len(s.bullets) for s in self.sections) > MAX_LINES:
            raise ValueError(f"{MAX_LINES} lignes au plus")
        return self


class RestoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verify: bool


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Brouillon introuvable")


def _facts(conn: Connection) -> dict[str, Fact]:
    rows = conn.execute(text(f"SELECT {FACT_COLUMNS} FROM profile_facts ORDER BY created_at, id")).mappings().all()
    return {str(r["id"]): Fact(str(r["id"]), r["kind"], r["text"], r["start_date"], r["end_date"],
                               tuple(r["technologies"]), r["source"], r["status"]) for r in rows}


def _sections(content: list) -> list[Section]:
    return [Section.model_validate(item) for item in content]


def _jsonable(sections: list[Section]) -> list[dict]:
    return [s.model_dump(mode="json") for s in sections]


def _words(*values: str | None) -> list[str]:
    return re.findall(r"\w+", " ".join(v for v in values if v))


def _draft(conn: Connection, draft_id: str) -> dict:
    row = conn.execute(text(
        "SELECT d.id, d.kind, d.job_posting_id AS offer_id, d.current_version, d.updated_at, "
        "p.title AS offer_title, p.company AS offer_company, v.content "
        "FROM document_drafts d LEFT JOIN job_postings p ON p.id = d.job_posting_id "
        "JOIN document_versions v ON v.draft_id = d.id AND v.number = d.current_version WHERE d.id = :id"),
        {"id": draft_id}).mappings().first()
    if row is None:
        raise _not_found()
    return dict(row)


def _diff(sections: list[Section], facts: dict[str, Fact]) -> dict:
    lines, used = [], set()
    for s, section in enumerate(sections):
        for b, bullet in enumerate(section.bullets):
            cited = [facts[str(i)] for i in bullet.fact_ids if str(i) in facts]
            used |= {f.id for f in cited}
            same = len(cited) == 1 and cited[0].text.strip() == bullet.texte.strip()
            lines.append({"section": s, "bullet": b, "status": "same" if same else "reformulated",
                          "master_text": " ; ".join(f.text for f in cited)})
    omitted = [f.id for f in facts.values() if f.status == "validated" and f.id not in used]
    return {"lines": lines, "omitted_fact_ids": omitted}


def _check_out(sections: list[Section], facts: dict[str, Fact], extra_names: list[str], issues=None,
               verified: bool = False) -> dict:
    found = list(check_document(sections, facts, extra_names).issues) if issues is None else issues
    return {"ok": not found, "verified": verified,
            "issues": [{"section": i.section, "bullet": i.bullet, "code": i.code, "message": i.message} for i in found]}


def _out(conn: Connection, draft_id: str) -> dict:
    row = _draft(conn, draft_id)
    facts, sections = _facts(conn), _sections(row["content"])
    names = _words(row["offer_title"], row["offer_company"]) if row["kind"] == "cover_letter" else []
    return {"id": row["id"], "kind": row["kind"], "offer_id": row["offer_id"],
            "title": row["offer_title"] or GENERAL_TITLE, "current_version": row["current_version"],
            "updated_at": row["updated_at"], "sections": _jsonable(sections),
            "check": _check_out(sections, facts, names), "diff": _diff(sections, facts)}


def _add_version(conn: Connection, draft_id: str, user_id: str, sections: list[Section], origin: str) -> None:
    number = conn.execute(text(
        "UPDATE document_drafts SET current_version = current_version + 1, updated_at = now() WHERE id = :id "
        "RETURNING current_version"), {"id": draft_id}).scalar_one()
    conn.execute(text(
        "INSERT INTO document_versions (user_id, draft_id, number, origin, content) "
        "VALUES (:uid, :id, :n, :origin, CAST(:content AS jsonb))"),
        {"uid": user_id, "id": draft_id, "n": number, "origin": origin, "content": _json(sections)})
    conn.execute(text("DELETE FROM document_versions WHERE draft_id = :id AND number <= :old"),
                 {"id": draft_id, "old": number - MAX_VERSIONS})


def _json(sections: list[Section]) -> str:
    return json.dumps(_jsonable(sections), ensure_ascii=False)


@router.get("/documents", operation_id="listDocumentDrafts")
def list_drafts(offer_id: uuid.UUID | None = None, session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        rows = conn.execute(text(
            "SELECT d.id, d.kind, d.job_posting_id AS offer_id, COALESCE(p.title, :general) AS title, "
            "d.current_version, d.updated_at FROM document_drafts d "
            "LEFT JOIN job_postings p ON p.id = d.job_posting_id "
            "WHERE (CAST(:offer AS uuid) IS NULL OR d.job_posting_id = :offer) ORDER BY d.updated_at DESC, d.id"),
            {"general": GENERAL_TITLE, "offer": str(offer_id) if offer_id else None}).mappings().all()
    return [dict(r) for r in rows]


@router.post("/documents/generate", status_code=201, operation_id="generateDocument")
def generate(body: GenerateIn, session: Session = Depends(require_csrf), gateway: LLMGateway | None = Depends(llm_gateway)):
    if body.kind == "cover_letter" and body.offer_id is None:
        raise ApiError(422, "validation_error", "Une lettre a besoin d'une offre")
    gateway = _need(gateway)
    user = session.user_id
    with user_scope(user) as conn:
        facts = list(_facts(conn).values())
        offer = None
        if body.offer_id is not None:
            row = conn.execute(text("SELECT title, company, location, description_text, expired FROM job_postings "
                                    "WHERE id = :id"), {"id": str(body.offer_id)}).mappings().first()
            if row is None:
                raise ApiError(404, "not_found", "Offre introuvable")
            if row["expired"]:
                raise ApiError(409, "offer_expired", "Cette offre a expiré")
            offer = OfferInfo(row["title"], row["company"], row["location"], row["description_text"])
        revision = (conn.execute(text(
            "SELECT current_version FROM document_drafts WHERE user_id = :uid AND kind = :kind AND "
            "job_posting_id IS NOT DISTINCT FROM CAST(:offer AS uuid)"),
            {"uid": user, "kind": body.kind, "offer": str(body.offer_id) if body.offer_id else None}).scalar() or 0) + 1
    kind = "cover_letter" if body.kind == "cover_letter" else ("adapted_cv" if offer else "general_cv")
    try:
        sections = generate_document(gateway, user, kind=kind, facts=facts, offer=offer, revision=revision,
                                     known_names=[])
    except NotEnoughFacts as error:
        raise ApiError(409, "not_enough_facts", str(error)) from None
    except BudgetExceeded:
        raise ApiError(429, "llm_budget_exceeded", "Plafond de coût IA du jour atteint") from None
    except (GenerationError, GatewayError):
        raise ApiError(502, "generation_failed", "Le modèle n'a pas rendu un texte exploitable") from None
    with user_scope(user) as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('docs:' || :uid, 0))"), {"uid": user})
        existing = conn.execute(text(
            "SELECT id FROM document_drafts WHERE user_id = :uid AND kind = :kind AND "
            "job_posting_id IS NOT DISTINCT FROM CAST(:offer AS uuid)"),
            {"uid": user, "kind": body.kind, "offer": str(body.offer_id) if body.offer_id else None}).scalar()
        if existing:
            draft_id = str(existing)
            _add_version(conn, draft_id, user, sections, "generated")
        else:
            draft_id = str(conn.execute(text(
                "INSERT INTO document_drafts (user_id, kind, job_posting_id) VALUES (:uid, :kind, :offer) RETURNING id"),
                {"uid": user, "kind": body.kind, "offer": str(body.offer_id) if body.offer_id else None}).scalar_one())
            conn.execute(text("INSERT INTO document_versions (user_id, draft_id, number, origin, content) "
                              "VALUES (:uid, :id, 1, 'generated', CAST(:content AS jsonb))"),
                         {"uid": user, "id": draft_id, "content": _json(sections)})
        return _out(conn, draft_id)


@router.get("/documents/{document_id}", operation_id="getDocumentDraft")
def get_draft(document_id: uuid.UUID, session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        return _out(conn, str(document_id))


@router.put("/documents/{document_id}", operation_id="saveDocumentDraft")
def save_draft(document_id: uuid.UUID, body: SaveIn, session: Session = Depends(require_csrf)):
    user = session.user_id
    with user_scope(user) as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('docs:' || :uid, 0))"), {"uid": user})
        current = _draft(conn, str(document_id))
        if current["current_version"] != body.base_version:
            raise ApiError(409, "version_conflict", "Le brouillon a changé depuis votre dernière lecture")
        sections = []
        for section in body.sections:
            bullets = []
            for bullet in section.bullets:
                ids = [] if bullet.manual else bullet.fact_ids
                if bullet.manual:  # une ligne écrite à la main devient un fait à valider, jamais un fait validé
                    ids = [_manual_fact(conn, user, bullet.texte)]
                bullets.append(Bullet(texte=bullet.texte, fact_ids=ids))
            sections.append(Section(section=section.section, bullets=bullets))
        _add_version(conn, str(document_id), user, sections, "edited")
        return _out(conn, str(document_id))


def _manual_fact(conn: Connection, user: str, content: str) -> uuid.UUID:
    if conn.execute(text("SELECT count(*) FROM profile_facts WHERE status = 'proposed'")).scalar() >= MAX_FACTS:
        raise ApiError(409, "too_many_facts", f"{MAX_FACTS} faits à valider au plus : validez ou rejetez-en")
    existing = conn.execute(text("SELECT id FROM profile_facts WHERE text = :t AND status = 'proposed' AND source = :s"),
                            {"t": content, "s": MANUAL_SOURCE}).scalar()
    if existing:
        return existing
    return conn.execute(text(
        "INSERT INTO profile_facts (user_id, kind, text, technologies, source, status) "
        "VALUES (:uid, 'other', :t, '{}', :s, 'proposed') RETURNING id"),
        {"uid": user, "t": content, "s": MANUAL_SOURCE}).scalar_one()


@router.delete("/documents/{document_id}", status_code=204, operation_id="deleteDocumentDraft")
def delete_draft(document_id: uuid.UUID, session: Session = Depends(require_csrf)) -> None:
    with user_scope(session.user_id) as conn:
        if not conn.execute(text("DELETE FROM document_drafts WHERE id = :id"), {"id": str(document_id)}).rowcount:
            raise _not_found()


@router.get("/documents/{document_id}/versions", operation_id="listDocumentVersions")
def list_versions(document_id: uuid.UUID, session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        _draft(conn, str(document_id))
        rows = conn.execute(text("SELECT number, origin, created_at FROM document_versions WHERE draft_id = :id "
                                 "ORDER BY number DESC"), {"id": str(document_id)}).mappings().all()
    return [dict(r) for r in rows]


@router.post("/documents/{document_id}/restore", operation_id="restoreDocumentVersion")
def restore_version(document_id: uuid.UUID, body: RestoreIn, session: Session = Depends(require_csrf)):
    user = session.user_id
    with user_scope(user) as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('docs:' || :uid, 0))"), {"uid": user})
        _draft(conn, str(document_id))
        content = conn.execute(text("SELECT content FROM document_versions WHERE draft_id = :id AND number = :n"),
                               {"id": str(document_id), "n": body.version}).scalar()
        if content is None:
            raise ApiError(404, "not_found", "Version introuvable")
        _add_version(conn, str(document_id), user, _sections(content), "restored")
        return _out(conn, str(document_id))


@router.post("/documents/{document_id}/check", operation_id="checkDocumentDraft")
def check_draft(document_id: uuid.UUID, body: CheckIn, session: Session = Depends(require_csrf),
                gateway: LLMGateway | None = Depends(llm_gateway)):
    with user_scope(session.user_id) as conn:
        row = _draft(conn, str(document_id))
        facts = _facts(conn)
    sections = _sections(row["content"])
    names = _words(row["offer_title"], row["offer_company"]) if row["kind"] == "cover_letter" else []
    result = _check_out(sections, facts, names)
    if not (body.verify and result["ok"]):
        return result
    # Le second regard ne s'ajoute qu'à un texte déjà accepté par le contrôle déterministe.
    extra = verify_with_llm(_need(gateway), session.user_id, sections, facts, known_names=[])
    return _check_out(sections, facts, names, issues=extra,
                      verified=not any(i.code == "verifier_unavailable" for i in extra))
