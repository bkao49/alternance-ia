"""Score d'une offre pour un utilisateur : déterministe, reproductible, sans IA.

`score = 5 × Σ(wᵢ·sᵢ) / Σw` sur les composantes **connues** (une composante inconnue sort du calcul).
Couverture = poids des composantes connues / poids total ; sous 0,5, le score est ramené vers la
moyenne (une offre presque vide n'a jamais un score parfait). Un critère obligatoire violé plafonne le
score. L'explication est écrite par gabarit à partir des critères calculés et ne cite que des faits
du profil réellement utilisés : aucune invention possible, et `check_fact_ids` le vérifie.
"""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.ai.matching.extraction import Extraction, to_offer_view
from app.ai.matching.filters import (
    Criteria,
    FilterOutcome,
    MatchPolicy,
    Status,
    apply_filters,
    load_criteria,
    normalize,
    record_discard,
)

DEFAULT_WEIGHTS: Mapping[str, float] = {
    "title": 30, "skills": 20, "experience": 15, "location_remote": 10, "contract": 5, "salary": 10, "degree": 10}
MEAN_SCORE = 2.5  # vers quoi on ramène un score peu couvert
MIN_COVERAGE = 0.5
MANDATORY_CAP = 2.0  # plafond quand un critère obligatoire est violé
LABELS = {"title": "Intitulé", "skills": "Compétences", "experience": "Expérience",
          "location_remote": "Lieu et télétravail", "contract": "Contrat", "salary": "Salaire", "degree": "Diplôme"}
FACT_KINDS_PRACTICE = ("experience", "project")


class ScoringError(Exception):
    pass


def weights_from_env() -> dict[str, float]:
    """Poids réglables par le PO : `MATCH_WEIGHTS='{"title": 40, "salary": 0}'` (le reste garde sa valeur)."""
    raw = os.environ.get("MATCH_WEIGHTS", "")
    weights = dict(DEFAULT_WEIGHTS)
    if raw:
        try:
            custom = json.loads(raw)
            ok = isinstance(custom, dict) and set(custom) <= set(weights) and all(
                isinstance(v, int | float) and not isinstance(v, bool) and 0 <= v <= 1000 for v in custom.values())
        except ValueError:
            ok = False
        if not ok:
            raise RuntimeError("MATCH_WEIGHTS doit être un objet JSON {composante: poids 0 à 1000}")
        weights.update(custom)
    if sum(weights.values()) <= 0:
        raise RuntimeError("MATCH_WEIGHTS : la somme des poids doit être positive")
    return weights


@dataclass(frozen=True)
class Component:
    key: str
    score: float | None  # 0 à 1 ; None = inconnu, la composante sort du calcul
    note: str
    fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreResult:
    value: float
    confidence: str
    coverage: float
    criteria: list[dict]
    blocking_reasons: list[str]
    explanation: str


def _words(value: str) -> set[str]:
    return set(normalize(value).split())


def _facts_for(skill: str, facts: Sequence[Mapping], kinds: tuple[str, ...] | None = None) -> list[str]:
    wanted = normalize(skill)
    found = []
    for fact in facts:
        if kinds and fact["kind"] not in kinds:
            continue
        if not wanted:
            continue
        techs = {normalize(t) for t in fact["technologies"]} - {""}
        if wanted in techs or (wanted and wanted in _words(fact["text"])) or (
                " " in wanted and wanted in normalize(fact["text"])):
            found.append(str(fact["id"]))
    return found


def _skill_component(key: str, skills: Sequence[str], facts: Sequence[Mapping], kinds) -> Component:
    if not skills or not facts:
        return Component(key, None, "Information absente de l'offre ou du profil.")
    matched = {skill: _facts_for(skill, facts, kinds) for skill in skills}
    hits = [skill for skill, ids in matched.items() if ids]
    ids = tuple(dict.fromkeys(i for skill in hits for i in matched[skill]))
    note = f"{len(hits)} compétence(s) sur {len(skills)} retrouvée(s)" + (f" : {', '.join(hits)}." if hits else ".")
    return Component(key, len(hits) / len(skills), note, ids)


def _from_check(key: str, outcome: FilterOutcome, name: str, applicable: bool) -> Component:
    check = next(c for c in outcome.checks if c.name == name)
    if not applicable or check.status is Status.UNKNOWN:
        return Component(key, None, "Information absente de l'offre ou des critères.")
    return Component(key, 1.0 if check.status is Status.OK else 0.0, check.reason or "Conforme aux critères.")


def build_components(title: str, extraction: Extraction | None, criteria: Criteria, keywords: Sequence[str],
                     facts: Sequence[Mapping], outcome: FilterOutcome) -> list[Component]:
    skills = extraction.skills if extraction else []
    in_title = _words(title)
    title_hit = [k for k in keywords if normalize(k) and set(normalize(k).split()) <= in_title]
    salary = next(c for c in outcome.checks if c.name == "salary")
    return [
        Component("title", (1.0 if title_hit else 0.0) if keywords else None,
                  f"Intitulé proche de : {', '.join(title_hit)}." if title_hit else "Aucun mot-clé dans l'intitulé."),
        _skill_component("skills", skills, facts, None),
        _skill_component("experience", skills, facts, FACT_KINDS_PRACTICE),
        _from_check("location_remote", outcome, "location", bool(criteria.locations)),
        _from_check("contract", outcome, "contract", bool(criteria.contract_types)),
        _from_check("salary", outcome, "salary", criteria.min_salary_eur is not None)
        if salary.status is not Status.FAIL else Component("salary", 0.0, salary.reason),
        _from_check("degree", outcome, "education", criteria.education_level is not None),
    ]


def check_fact_ids(components: Sequence[Component], known_ids: set[str]) -> None:
    """Garde de sécurité : refuse tout fait cité absent de la liste donnée (les faits de l'utilisateur,
    lus sous RLS). Les composantes ne citent que des faits reçus ; ce contrôle protège une future
    évolution (explication par IA) contre un fait inventé. Les notes de critères reprennent des
    compétences d'annonce (texte non fiable) : le front les affiche en texte brut."""
    for component in components:
        if not set(component.fact_ids) <= known_ids:
            raise ScoringError("fait inexistant cité dans un critère")


def aggregate(components: Sequence[Component], weights: Mapping[str, float], violated: Sequence[str] = (),
              reasons: Sequence[str] = (), *, cap: float = MANDATORY_CAP) -> ScoreResult:
    weights = {**DEFAULT_WEIGHTS, **weights}
    total = sum(weights[c.key] for c in components)
    known = [c for c in components if c.score is not None and weights[c.key] > 0]
    noted = sum(weights[c.key] for c in known)
    coverage = noted / total if total else 0.0
    raw = 5 * sum(weights[c.key] * c.score for c in known) / noted if noted else MEAN_SCORE
    value = raw if coverage >= MIN_COVERAGE else MEAN_SCORE + (raw - MEAN_SCORE) * coverage / MIN_COVERAGE
    capped = bool(violated) and value > cap  # le plafond n'est annoncé que s'il a changé le score
    if violated:
        value = min(value, cap)
    value = round(max(0.0, min(5.0, value)), 2)
    confidence = "high" if coverage >= 0.8 else "medium" if coverage >= MIN_COVERAGE else "low"
    criteria = [{"key": c.key, "score": round(c.score, 2) if c.score is not None else 0, "weight": weights[c.key],
                 "explanation": c.note, "known": c.score is not None, "fact_ids": list(c.fact_ids)}
                for c in components]
    return ScoreResult(value, confidence, round(coverage, 2), criteria, list(reasons),
                       explain(components, weights, value, confidence, capped))


def explain(components: Sequence[Component], weights: Mapping[str, float], value: float, confidence: str,
            capped: bool) -> str:
    known = sorted((c for c in components if c.score is not None and weights[c.key] > 0),
                   key=lambda c: (-c.score * weights[c.key], c.key))
    strong = [LABELS[c.key].lower() for c in known if c.score >= 0.7][:3]
    weak = [LABELS[c.key].lower() for c in known if c.score < 0.4][:2]
    first = f"Score {value:.2f}/5 : " + (f"points forts : {', '.join(strong)}" if strong else "peu de points forts établis")
    first += f" ; points faibles : {', '.join(weak)}." if weak else "."
    cited = len({i for c in components for i in c.fact_ids})
    second = f"Appuyé sur {cited} fait(s) de votre profil. " if cited else ""
    if capped:
        second += "Un critère obligatoire n'est pas respecté : le score est plafonné. "
    if confidence != "high":
        second += "Offre peu renseignée : confiance " + ("faible." if confidence == "low" else "moyenne.")
    return (first + " " + second).strip()


def score_offer(conn: Connection, user_id: str, posting_id: str, *, weights: Mapping[str, float] | None = None,
                policy: MatchPolicy | None = None, today=None) -> ScoreResult | None:
    """Filtre puis note une offre de l'utilisateur de la transaction ; écrit dans `scores`.
    Rend None si l'utilisateur n'a pas saisi ses critères ou si l'offre est introuvable."""
    criteria = load_criteria(conn)
    posting = conn.execute(text(
        "SELECT title, location, description_text, expired FROM job_postings WHERE id = :id"),
        {"id": posting_id}).mappings().first()
    if criteria is None or posting is None:
        return None
    analysis = conn.execute(text(
        "SELECT id, extraction FROM analyses WHERE job_posting_id = :id ORDER BY created_at DESC, id LIMIT 1"),
        {"id": posting_id}).mappings().first()
    extraction = None
    if analysis is not None:
        try:
            body = {k: v for k, v in analysis["extraction"].items() if k != "content_hash"}
            extraction = Extraction.model_validate(body, strict=False)
        except (ValueError, AttributeError, TypeError):
            extraction = None  # analyse ancienne ou de démonstration : traitée comme absente
    outcome = apply_filters(to_offer_view(dict(posting), extraction), criteria, policy, today=today)
    if outcome.discarded:
        record_discard(conn, user_id, posting_id, outcome)
        return ScoreResult(0.0, "high", 1.0, [], list(outcome.reasons), "Offre écartée par un filtre dur.")
    keywords = conn.execute(text("SELECT keywords FROM search_preferences")).scalar_one()
    facts = conn.execute(text("SELECT id, kind, text, technologies FROM profile_facts")).mappings().all()
    components = build_components(posting["title"], extraction, criteria, keywords, facts, outcome)
    check_fact_ids(components, {str(f["id"]) for f in facts})
    reasons = [c.reason for c in outcome.checks if c.name in outcome.violated_mandatory]
    result = aggregate(components, weights or weights_from_env(), outcome.violated_mandatory, reasons)
    conn.execute(text(
        "INSERT INTO scores (user_id, job_posting_id, analysis_id, value, confidence, explanation, criteria, "
        "blocking_reasons, created_at) VALUES (:uid, :posting, :analysis, :value, :confidence, :explanation, "
        "CAST(:criteria AS jsonb), CAST(:reasons AS jsonb), clock_timestamp())"),
        {"uid": user_id, "posting": posting_id, "analysis": analysis["id"] if analysis else None,
         "value": result.value, "confidence": result.confidence, "explanation": result.explanation,
         "criteria": json.dumps(result.criteria), "reasons": json.dumps(result.blocking_reasons, ensure_ascii=False)})
    return result
