"""Collecteur de référence qui lit un fichier JSON local au format d'une source fictive.

Sert aux tests et au développement, sans aucun appel réseau. Les vrais connecteurs
(La Bonne Alternance, France Travail) suivent le même modèle : `fetch` lit la source,
`normalize` traduit ses champs.
"""

import datetime as dt
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from app.collectors.base import (
    Collector,
    ContractType,
    InvalidResponse,
    NormalizedOffer,
    SearchQuery,
)

# Codes de contrat de la source fictive → type normalisé ; tout code inconnu donne OTHER.
CONTRACT_CODES = {
    "STAGE": ContractType.INTERNSHIP,
    "APPRENTISSAGE": ContractType.APPRENTICESHIP,
    "PROFESSIONNALISATION": ContractType.APPRENTICESHIP,
    "CDD": ContractType.FIXED_TERM,
    "CDI": ContractType.PERMANENT,
}


class FixtureCollector(Collector):
    def __init__(self, path: Path, source: str = "fixture"):
        self.path = path
        self.source = source

    def fetch(self, query: SearchQuery) -> Iterable[Mapping[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InvalidResponse(self.source, f"fichier illisible ({type(exc).__name__})") from exc
        records = payload.get("resultats") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise InvalidResponse(self.source, "clé « resultats » absente ou invalide")
        return records

    def normalize(self, raw: Mapping[str, Any]) -> NormalizedOffer:
        if not isinstance(raw, Mapping) or "id" not in raw:
            raise InvalidResponse(self.source, "enregistrement sans identifiant")
        published = raw.get("date_publication")
        return NormalizedOffer(
            source=self.source,
            external_id=str(raw["id"]),
            url=raw.get("lien", ""),
            title=raw.get("intitule", ""),
            company=raw.get("entreprise", ""),
            location=raw.get("lieu"),
            contract_type=CONTRACT_CODES.get(str(raw.get("contrat")).upper(), ContractType.OTHER),
            description_text=raw.get("description", ""),
            published_at=dt.datetime.fromisoformat(published) if published else None,
        )
