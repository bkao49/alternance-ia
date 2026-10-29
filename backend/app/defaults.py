from sqlalchemy import Connection, text

# (clé stable, nom affiché, couleur) : les 10 statuts par défaut, dans l'ordre d'affichage.
DEFAULT_STATUSES = [
    ("detected", "Détectée", "#64748b"),
    ("analyzed", "Analysée", "#0ea5e9"),
    ("to_prepare", "À préparer", "#f59e0b"),
    ("human_review", "À valider par un humain", "#8b5cf6"),
    ("sent", "Envoyée", "#4f46e5"),
    ("waiting", "En attente", "#94a3b8"),
    ("interview", "Entretien", "#10b981"),
    ("rejected", "Refusée", "#ef4444"),
    ("offer_received", "Offre reçue", "#22c55e"),
    ("abandoned", "Abandonnée", "#6b7280"),
]


def seed_default_statuses(conn: Connection, user_id: str) -> None:
    for position, (key, name, color) in enumerate(DEFAULT_STATUSES, start=1):
        conn.execute(
            text(
                "INSERT INTO status_definitions (user_id, name, position, color, system_key) "
                "VALUES (:uid, :name, :position, :color, :key)"
            ),
            {"uid": user_id, "name": name, "position": position, "color": color, "key": key},
        )
