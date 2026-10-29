"""Données de démonstration ENTIÈREMENT FICTIVES : `python -m app.seed_demo <e-mail>`.

Entreprises inventées, URL en `example.test`. Écrit via `user_scope` : la RLS s'applique comme pour
l'API. Rejouable : une offre déjà présente (source « demo ») n'est pas recréée, ni ses dépendances.
Refuse de tourner sans ALLOW_DEMO_DATA=true.
"""
import datetime as dt
import hashlib
import json
import os
import sys

from sqlalchemy import Connection, text

from app.db import user_scope

SOURCE = "demo"

# (entreprise, intitulé, lieu, score 3-5, confiance, note de base des critères, parcours des statuts de la
# candidature ; vide = offre sans candidature). Le dernier statut du parcours est le statut courant.
OFFERS = [
    ("Acme Analytics", "Alternance Data Analyst", "Paris", 4.6, "high", 0.9,
     ["to_prepare", "human_review", "sent", "waiting", "interview"]),
    ("Globex Labs", "Alternance Data Scientist", "Lyon", 4.2, "high", 0.8,
     ["to_prepare", "human_review", "sent"]),
    ("Initech Data", "Alternance Ingénieur Data", "Nantes", 3.9, "medium", 0.75,
     ["to_prepare", "human_review", "sent", "waiting"]),
    ("Umbrella Systems", "Alternance Machine Learning", "Toulouse", 3.4, "medium", 0.65,
     ["to_prepare", "human_review", "sent", "waiting", "rejected"]),
    ("Hooli Conseil", "Alternance Analyste BI", "Lille", 4.8, "high", 0.95,
     ["to_prepare", "human_review", "sent", "waiting", "interview", "offer_received"]),
    ("Stark Industries Fictives", "Alternance Data Engineer", "Bordeaux", 3.1, "low", 0.6,
     ["to_prepare", "human_review"]),
    ("Wayne Technologies Démo", "Alternance IA appliquée", "Rennes", 3.7, "medium", 0.7,
     ["to_prepare", "abandoned"]),
    ("Soylent Data", "Alternance Data Analyst", "Strasbourg", 4.0, "medium", 0.8, []),
    ("Vandelay Numérique", "Alternance MLOps", "Montpellier", 3.3, "low", 0.55, []),
    ("Cyberdyne Fictive", "Alternance Data Scientist", "Grenoble", 4.4, "high", 0.85, []),
    ("Tyrell Insights", "Alternance Statisticien", "Marseille", 3.0, "low", 0.5, []),
    ("Pied Piper Démo", "Alternance Analytics Engineer", "Paris", 4.1, "medium", 0.8, []),
]

CRITERIA_KEYS = ["technical_skills", "projects", "domain", "level", "education", "contract_location", "ad_quality"]
WEIGHTS = [0.3, 0.2, 0.15, 0.1, 0.1, 0.1, 0.05]
OFFSETS = [0.05, -0.05, 0.0, 0.1, -0.1, 0.05, 0.0]


def _status_ids(conn: Connection) -> dict[str, str]:
    rows = conn.execute(text("SELECT system_key, id FROM status_definitions WHERE system_key IS NOT NULL")).all()
    return {key: str(sid) for key, sid in rows}


def _criteria(base: float) -> list[dict]:
    return [
        {"key": key, "score": round(min(1.0, max(0.0, base + offset)), 2), "weight": weight,
         "explanation": f"Critère fictif de démonstration ({key})."}
        for key, weight, offset in zip(CRITERIA_KEYS, WEIGHTS, OFFSETS, strict=True)
    ]


def _insert_application(conn, user_id, posting_id, company, title, path, statuses, now, index):
    """Candidature + un événement par étape. « Envoyée » pose sent_at ET son événement, comme confirm-sent."""
    start = now - dt.timedelta(days=30 - index * 3)
    last = start + dt.timedelta(days=(len(path) - 1) * 2)
    application_id = conn.execute(
        text(
            "INSERT INTO applications (user_id, job_posting_id, company, title, status_id, notes, "
            "created_at, updated_at) VALUES (:uid, :posting, :company, :title, :status, "
            "'Candidature fictive de démonstration.', :created, :updated) RETURNING id"
        ),
        {"uid": user_id, "posting": posting_id, "company": company, "title": title,
         "status": statuses[path[-1]], "created": start, "updated": last},
    ).scalar_one()
    previous = None
    sent_at = None
    for step, key in enumerate(path):
        occurred = start + dt.timedelta(days=step * 2)
        comment = "Candidature créée" if previous is None else "Étape fictive de démonstration"
        if key == "sent":
            comment = "Envoi confirmé par l'utilisateur"
            sent_at = occurred
        conn.execute(
            text(
                "INSERT INTO events (user_id, application_id, from_status_id, to_status_id, actor, comment, "
                "occurred_at) VALUES (:uid, :app, :from_status, :to_status, 'user', :comment, :t)"
            ),
            {"uid": user_id, "app": application_id, "from_status": previous, "to_status": statuses[key],
             "comment": comment, "t": occurred},
        )
        previous = statuses[key]
    if sent_at is not None:
        conn.execute(text("UPDATE applications SET sent_at = :t WHERE id = :id"), {"t": sent_at, "id": application_id})


def seed(user_id: str) -> tuple[int, int]:
    """Retourne (offres créées, candidatures créées)."""
    now = dt.datetime.now(dt.UTC)
    offers = applications = 0
    with user_scope(user_id) as conn:
        statuses = _status_ids(conn)
        missing = {key for offer in OFFERS for key in offer[6]} - statuses.keys()
        if missing:
            raise RuntimeError(f"Statuts système introuvables : {sorted(missing)}")
        for index, (company, title, location, value, confidence, base, path) in enumerate(OFFERS, start=1):
            description = f"Offre fictive de démonstration : {title} chez {company}. Aucune donnée réelle."
            posting_id = conn.execute(
                text(
                    "INSERT INTO job_postings (user_id, source, external_id, url, title, company, location, "
                    "description_text, content_hash, detected_at) "
                    "VALUES (:uid, :source, :ext, :url, :title, :company, :location, :descr, :hash, :t) "
                    "ON CONFLICT (user_id, source, external_id) DO NOTHING RETURNING id"
                ),
                {"uid": user_id, "source": SOURCE, "ext": f"demo-{index:02d}",
                 "url": f"https://jobs.example.test/{index:02d}", "title": title, "company": company,
                 "location": location, "descr": description,
                 "hash": hashlib.sha256(description.encode()).hexdigest(),
                 "t": now - dt.timedelta(days=35 - index)},
            ).scalar_one_or_none()
            if posting_id is None:
                continue  # créée par un passage précédent, avec ses analyse, score et candidature
            offers += 1
            extraction = {"title": title, "company": company, "contract": "alternance", "fictive": True}
            analysis_id = conn.execute(
                text(
                    "INSERT INTO analyses (user_id, job_posting_id, extraction, prompt_version) "
                    "VALUES (:uid, :posting, CAST(:extraction AS jsonb), 'demo-v1') RETURNING id"
                ),
                {"uid": user_id, "posting": posting_id, "extraction": json.dumps(extraction)},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO scores (user_id, job_posting_id, analysis_id, value, confidence, explanation, "
                    "criteria) VALUES (:uid, :posting, :analysis, :value, :confidence, :explanation, "
                    "CAST(:criteria AS jsonb))"
                ),
                {"uid": user_id, "posting": posting_id, "analysis": analysis_id, "value": value,
                 "confidence": confidence, "explanation": "Score fictif de démonstration.",
                 "criteria": json.dumps(_criteria(base))},
            )
            if path:
                _insert_application(conn, user_id, posting_id, company, title, path, statuses, now, index)
                applications += 1
    return offers, applications


def find_user_id(email: str) -> str | None:
    """Passe par la fonction de connexion : le rôle de l'API n'a pas le droit de lister les comptes."""
    with user_scope() as conn:
        row = conn.execute(
            text("SELECT user_id FROM auth_lookup_user(:email)"), {"email": email.strip().lower()}
        ).first()
    return str(row.user_id) if row else None


def main(argv: list[str]) -> int:
    if os.environ.get("ALLOW_DEMO_DATA", "").lower() != "true":
        print("Refusé : définissez ALLOW_DEMO_DATA=true (dans .env) pour autoriser les données fictives.")
        return 1
    if len(argv) != 1:
        print("Usage : python -m app.seed_demo <e-mail du compte>")
        return 1
    user_id = find_user_id(argv[0])
    if user_id is None:
        print("Compte introuvable : créez-le d'abord avec python -m app.create_user.")
        return 1
    offers, applications = seed(user_id)
    print(f"Données fictives ajoutées : {offers} offres, {applications} candidatures.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
