"""Chaîne d'analyse des nouvelles offres, lancée par le worker après chaque collecte (ADR 0011).

Pour chaque offre de l'utilisateur qui n'a encore aucun score : filtres durs (code, gratuit), puis
extraction par la passerelle (une seule fois par offre, l'analyse est réutilisée), puis score. Une offre
sans score est « en attente » : une erreur ou le plafond de coût ne perd donc rien, la passe suivante
reprend là où elle s'est arrêtée. Rien de ce module n'écrit le contenu d'une annonce dans les journaux.
"""
import logging
from dataclasses import dataclass

from sqlalchemy import text

from app.ai.gateway import LLMGateway
from app.ai.matching.extraction import ExtractionError, extract_offer, to_offer_view
from app.ai.matching.filters import apply_filters, load_criteria, record_discard
from app.ai.matching.scoring import score_offer
from app.db import user_scope

log = logging.getLogger(__name__)

PASS_LIMIT = 100  # offres traitées par passe : le reste attend la passe suivante
MAX_PROVIDER_FAILURES = 3  # panne du fournisseur : on arrête la passe au lieu d'insister offre après offre
BUDGET_CODE = "llm_budget_exceeded"
TRANSIENT_CODES = {"llm_error", "provider_not_allowed"}  # sinon : le modèle a répondu, mais de façon invalide

PENDING_SQL = (
    "SELECT p.id FROM job_postings p WHERE NOT p.expired "
    "AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.job_posting_id = p.id) ORDER BY p.detected_at, p.id LIMIT :n")


@dataclass
class PassResult:
    scored: int = 0
    discarded: int = 0
    failed: int = 0
    waiting: int = 0  # offres laissées pour la passe suivante
    stopped: str | None = None  # "budget", "provider" ou "not_configured"


def _filter_only(user_id: str, posting_id: str) -> bool:
    """Filtres durs sans IA. True si l'offre est écartée (score 0 enregistré) : elle ne coûte rien."""
    with user_scope(user_id) as conn:
        criteria = load_criteria(conn)
        posting = conn.execute(text(
            "SELECT title, location, description_text, expired FROM job_postings WHERE id = :id"),
            {"id": posting_id}).mappings().first()
        if criteria is None or posting is None:
            return False
        outcome = apply_filters(to_offer_view(dict(posting), None), criteria)
        if outcome.discarded:
            record_discard(conn, user_id, posting_id, outcome)
        return outcome.discarded


def analyse_user_offers(gateway: LLMGateway | None, user_id: str, limit: int = PASS_LIMIT) -> PassResult:
    result = PassResult()
    with user_scope(user_id) as conn:
        if load_criteria(conn) is None:
            return result  # pas de critères saisis : rien à filtrer ni à noter
        pending = [str(r[0]) for r in conn.execute(text(PENDING_SQL), {"n": limit + 1})]
    result.waiting = max(len(pending) - limit, 0)  # au moins ce qui dépasse la passe
    provider_failures = 0
    for index, posting_id in enumerate(pending[:limit]):
        if _filter_only(user_id, posting_id):
            result.discarded += 1
            continue
        if gateway is None:
            result.stopped = "not_configured"
        elif provider_failures >= MAX_PROVIDER_FAILURES:
            result.stopped = "provider"
        if result.stopped:
            result.waiting += len(pending[:limit]) - index
            break
        try:
            try:
                extract_offer(gateway, user_id, posting_id)
            except ExtractionError as error:
                code = str(error)
                if code == BUDGET_CODE:
                    result.stopped = "budget"
                    result.waiting += len(pending[:limit]) - index
                    break
                if code in TRANSIENT_CODES:
                    provider_failures += 1
                    result.failed += 1
                    result.waiting += 1
                    continue
                # Réponse invalide deux fois : on note l'offre sans extraction (confiance faible) pour ne
                # pas la repayer à chaque collecte.
            provider_failures = 0
            with user_scope(user_id) as conn:
                score_offer(conn, user_id, posting_id)
            result.scored += 1
        except Exception as exc:  # noqa: BLE001 (une offre en bogue ne bloque pas les autres)
            log.error("analyse d'une offre en échec (%s)", type(exc).__name__)  # type seulement
            result.failed += 1
            result.waiting += 1
    if result.stopped == "budget":
        log.warning("analyse arrêtée : plafond de coût IA atteint, %d offre(s) en attente", result.waiting)
    elif result.stopped:
        log.warning("analyse arrêtée (%s), %d offre(s) en attente", result.stopped, result.waiting)
    log.info("analyse : %d notée(s), %d écartée(s), %d en échec, %d en attente",
             result.scored, result.discarded, result.failed, result.waiting)
    return result
