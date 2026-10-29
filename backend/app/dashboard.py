"""Compteurs du tableau de bord, servis par GET /stats."""

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.auth import Session, current_session
from app.db import user_scope

router = APIRouter(tags=["dashboard"])

# Seuil à partir duquel une offre est jugée pertinente (à valider par le PO).
RELEVANT_SCORE = 3.5

# « Atteint » = a eu un événement de changement de statut vers ce statut (table events), même si
# la candidature a avancé depuis. Les statuts personnalisés (system_key nul) ne comptent pas.
# « Préparée » = statut human_review ou un statut ultérieur dans l'entonnoir ; « Abandonnée » est
# exclu : on ne sait pas si l'abandon a eu lieu avant ou après la préparation.
PREPARED_KEYS = ["human_review", "sent", "waiting", "interview", "rejected", "offer_received"]
REPLY_KEYS = ["interview", "rejected", "offer_received"]

# Une seule requête, pas de N+1. Définition de chaque compteur :
#   detected    offres détectées (job_postings)
#   analyzed    offres ayant au moins une analyse
#   relevant    offres dont le DERNIER score est >= RELEVANT_SCORE
#   prepared    candidatures ayant atteint un statut de PREPARED_KEYS
#   to_validate candidatures actuellement en human_review
#   sent        candidatures avec sent_at non nul (renseigné uniquement par confirm-sent)
#   replies     candidatures ayant atteint interview, rejected ou offer_received
#   interviews / rejections / offers  candidatures ayant atteint interview / rejected / offer_received
# Taux de conversion : même définition, mais le numérateur ne compte que les candidatures avec
# sent_at non nul (sent_replies, sent_interviews, sent_offers), pour que taux <= 1 par construction.
# Offres expirées : detected, analyzed et relevant les INCLUENT, alors que GET /offers les masque par
# défaut (décision à valider par le PO).
STATS_SQL = """
    WITH latest AS (
        SELECT DISTINCT ON (job_posting_id) job_posting_id, value
        FROM scores ORDER BY job_posting_id, created_at DESC, id
    ), reached AS (
        SELECT DISTINCT e.application_id, s.system_key, a.sent_at IS NOT NULL AS was_sent
        FROM events e JOIN status_definitions s ON s.id = e.to_status_id
        JOIN applications a ON a.id = e.application_id
        WHERE s.system_key IS NOT NULL
    )
    SELECT
        (SELECT count(*) FROM job_postings) AS detected,
        (SELECT count(DISTINCT job_posting_id) FROM analyses) AS analyzed,
        (SELECT count(*) FROM latest WHERE value >= :relevant) AS relevant,
        (SELECT count(DISTINCT application_id) FROM reached
            WHERE system_key = ANY(CAST(:prepared AS text[]))) AS prepared,
        (SELECT count(*) FROM applications a JOIN status_definitions s ON s.id = a.status_id
            WHERE s.system_key = 'human_review') AS to_validate,
        (SELECT count(*) FROM applications WHERE sent_at IS NOT NULL) AS sent,
        (SELECT count(DISTINCT application_id) FROM reached
            WHERE system_key = ANY(CAST(:replies AS text[]))) AS replies,
        (SELECT count(*) FROM reached WHERE system_key = 'interview') AS interviews,
        (SELECT count(*) FROM reached WHERE system_key = 'rejected') AS rejections,
        (SELECT count(*) FROM reached WHERE system_key = 'offer_received') AS offers,
        (SELECT count(DISTINCT application_id) FROM reached
            WHERE was_sent AND system_key = ANY(CAST(:replies AS text[]))) AS sent_replies,
        (SELECT count(*) FROM reached WHERE was_sent AND system_key = 'interview') AS sent_interviews,
        (SELECT count(*) FROM reached WHERE was_sent AND system_key = 'offer_received') AS sent_offers
"""


def _rate(part: int, sent: int) -> float | None:
    """Taux de conversion depuis « envoyée » ; null si rien n'a été envoyé."""
    return None if sent == 0 else part / sent


@router.get("/dashboard/stats", operation_id="getDashboardStats")
def get_dashboard_stats(session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        counts = dict(conn.execute(
            text(STATS_SQL), {"relevant": RELEVANT_SCORE, "prepared": PREPARED_KEYS, "replies": REPLY_KEYS}
        ).mappings().one())
    from_sent = {key: counts.pop(key) for key in ("sent_replies", "sent_interviews", "sent_offers")}
    sent = counts["sent"]
    return {
        "counts": counts,
        "conversion": {
            "sent_to_reply": _rate(from_sent["sent_replies"], sent),
            "sent_to_interview": _rate(from_sent["sent_interviews"], sent),
            "sent_to_offer": _rate(from_sent["sent_offers"], sent),
        },
    }
