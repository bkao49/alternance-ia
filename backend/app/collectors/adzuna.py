"""Collecteur Adzuna : API officielle de recherche d'offres, France (`docs/sources/adzuna.md`).

Clés lues dans l'environnement (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`), jamais écrites ailleurs.
L'API ne renvoie qu'un extrait de la description ; le lien (`redirect_url`) est gardé tel quel
et n'est jamais suivi.
"""

import os
from collections.abc import Iterator, Mapping
from typing import Any

from app.collectors.api_client import ApiClient
from app.collectors.base import (
    Collector,
    CollectorError,
    ContractType,
    InvalidResponse,
    NormalizedOffer,
    SearchQuery,
)
from app.collectors.web import contract_type, html_to_text, parse_date

API_HOST = "api.adzuna.com"
SEARCH_PATH = "/v1/api/jobs/fr/search/{page}"
PAGE_SIZE = 50
MAX_PAGES = 10  # 500 offres au plus par collecte : ménage le quota
CONTRACTS = {"permanent": ContractType.PERMANENT, "contract": ContractType.FIXED_TERM}


class AdzunaCollector(Collector):
    source = "adzuna"

    def __init__(
        self, app_id: str | None = None, app_key: str | None = None,
        client: ApiClient | None = None,
    ):
        self.app_id = os.environ.get("ADZUNA_APP_ID", "") if app_id is None else app_id
        self.app_key = os.environ.get("ADZUNA_APP_KEY", "") if app_key is None else app_key
        self.client = client or ApiClient(self.source, API_HOST)

    def fetch(self, query: SearchQuery) -> Iterator[Mapping[str, Any]]:
        if not (self.app_id and self.app_key):
            raise CollectorError(self.source, "clés ADZUNA_APP_ID / ADZUNA_APP_KEY absentes")
        per_page = min(PAGE_SIZE, query.max_results)
        params: dict[str, Any] = {
            "app_id": self.app_id, "app_key": self.app_key,
            "results_per_page": per_page, "content-type": "application/json",
        }
        if query.keywords:
            params["what"] = " ".join(query.keywords)
        if query.location:
            params["where"] = query.location
        if query.contract_types == {ContractType.PERMANENT}:
            params["permanent"] = 1  # seul filtre de contrat documenté
        for page in range(1, MAX_PAGES + 1):
            payload = self.client.get_json(SEARCH_PATH.format(page=page), params)
            results = payload.get("results") if isinstance(payload, Mapping) else None
            if not isinstance(results, list):
                raise InvalidResponse(self.source, "clé « results » absente ou invalide")
            yield from results
            if len(results) < per_page:
                return

    def normalize(self, raw: Mapping[str, Any]) -> NormalizedOffer:
        raw_id = raw.get("id") if isinstance(raw, Mapping) else None
        if isinstance(raw_id, bool) or not isinstance(raw_id, str | int) or raw_id == "":
            raise InvalidResponse(self.source, "offre sans identifiant")
        title = _inline(raw.get("title"))
        company = raw.get("company")
        company = company.get("display_name") if isinstance(company, Mapping) else None
        # Les mots de l'intitulé (alternance, stage) priment sur le contrat déclaré.
        kind = contract_type(title)
        if kind is ContractType.OTHER:
            kind = CONTRACTS.get(str(raw.get("contract_type")), ContractType.OTHER)
        return NormalizedOffer(
            source=self.source, external_id=str(raw_id), url=raw.get("redirect_url", ""),
            title=title, company=company or "", location=_city(raw.get("location")),
            contract_type=kind, description_text=_inline(raw.get("description")),
            published_at=parse_date(raw.get("created")),
        )


def _city(location: Any) -> str | None:
    """Dernier niveau de `location.area` (la ville), sinon le libellé affiché."""
    if not isinstance(location, Mapping):
        return None
    area = location.get("area")
    if isinstance(area, list) and len(area) > 1 and isinstance(area[-1], str):
        return area[-1]
    name = location.get("display_name")
    return name if isinstance(name, str) else None


def _inline(value: Any) -> str:
    """Texte sur une ligne : Adzuna met des balises (`<strong>`) au milieu des phrases."""
    return " ".join(html_to_text(value).split())
