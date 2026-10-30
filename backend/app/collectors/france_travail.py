"""Collecteur France Travail : API « Offres d'emploi v2 », OAuth2 client credentials (#12).

Fiche : `docs/sources/france-travail.md`. Clés dans `FRANCE_TRAVAIL_CLIENT_ID` et
`FRANCE_TRAVAIL_CLIENT_SECRET`. Le bloc `contact` des offres (nom, téléphone, courriel du
recruteur) n'est jamais lu (RGPD).
"""

import os
import re
import time
from collections.abc import Callable, Iterator, Mapping
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
from app.collectors.web import contract_type, parse_date

API_HOST = "api.francetravail.io"
AUTH_HOST = "entreprise.francetravail.fr"
TOKEN_PATH = "/connexion/oauth2/access_token"
SEARCH_PATH = "/partenaire/offresdemploi/v2/offres/search"
SCOPE = "api_offresdemploiv2 o2dsoffre"
PAGE_SIZE = 150  # taille maximale d'une plage `range`
MAX_START = 3000  # l'API refuse une plage qui commence au-delà
DETAIL_URL = "https://candidat.francetravail.fr/offres/recherche/detail/{id}"
TYPES = {"CDI": ContractType.PERMANENT, "CDD": ContractType.FIXED_TERM}
QUERY_TYPES = {ContractType.PERMANENT: "CDI", ContractType.FIXED_TERM: "CDD"}


class FranceTravailCollector(Collector):
    source = "france_travail"

    def __init__(
        self, client_id: str | None = None, client_secret: str | None = None,
        client: ApiClient | None = None, clock: Callable[[], float] = time.monotonic,
    ):
        env = os.environ.get
        self.client_id = env("FRANCE_TRAVAIL_CLIENT_ID", "") if client_id is None else client_id
        self.client_secret = (
            env("FRANCE_TRAVAIL_CLIENT_SECRET", "") if client_secret is None else client_secret
        )
        self.client = client or ApiClient(self.source, API_HOST)
        self.clock = clock
        self._token: tuple[str, float] | None = None  # (jeton, échéance)

    def _access_token(self) -> str:
        if self._token and self.clock() < self._token[1]:
            return self._token[0]
        payload = self.client.request_json(
            "POST", TOKEN_PATH, host=AUTH_HOST, params={"realm": "/partenaire"},
            data={"grant_type": "client_credentials", "client_id": self.client_id,
                  "client_secret": self.client_secret, "scope": SCOPE},
        )
        token = payload.get("access_token") if isinstance(payload, Mapping) else None
        if not isinstance(token, str) or not token:
            raise InvalidResponse(self.source, "jeton OAuth2 absent")
        lifetime = payload.get("expires_in")
        lifetime = lifetime if isinstance(lifetime, int) and lifetime > 0 else 600
        self._token = (token, self.clock() + max(lifetime - 60, 30))  # marge d'une minute
        return token

    def fetch(self, query: SearchQuery) -> Iterator[Mapping[str, Any]]:
        if not (self.client_id and self.client_secret):
            raise CollectorError(
                self.source, "clés FRANCE_TRAVAIL_CLIENT_ID / FRANCE_TRAVAIL_CLIENT_SECRET absentes")
        params: dict[str, Any] = {}
        if query.keywords:
            params["motsCles"] = ",".join(query.keywords)
        if query.location and re.fullmatch(r"\d{2}|2[AB]|97\d", query.location.strip()):
            params["departement"] = query.location.strip()  # le libellé libre n'est pas accepté
        if query.contract_types and query.contract_types <= QUERY_TYPES.keys():
            params["typeContrat"] = ",".join(sorted(QUERY_TYPES[t] for t in query.contract_types))
        size = min(PAGE_SIZE, query.max_results)
        for start in range(0, min(query.max_results, MAX_START + PAGE_SIZE), size):
            headers = {"Authorization": f"Bearer {self._access_token()}"}
            payload = self.client.get_json(
                SEARCH_PATH, {**params, "range": f"{start}-{start + size - 1}"}, headers=headers,
            )
            if payload is None:  # 204 : aucun résultat
                return
            results = payload.get("resultats") if isinstance(payload, Mapping) else None
            if not isinstance(results, list):
                raise InvalidResponse(self.source, "clé « resultats » absente ou invalide")
            yield from results
            if len(results) < size or start + size > MAX_START:
                return

    def normalize(self, raw: Mapping[str, Any]) -> NormalizedOffer:
        raw_id = raw.get("id") if isinstance(raw, Mapping) else None
        if not isinstance(raw_id, str) or not re.fullmatch(r"[A-Za-z0-9]{1,20}", raw_id):
            raise InvalidResponse(self.source, "offre sans identifiant valide")
        title = raw.get("intitule") if isinstance(raw.get("intitule"), str) else ""
        company = raw.get("entreprise")
        company = company.get("nom") if isinstance(company, Mapping) else None
        origin = raw.get("origineOffre")
        url = origin.get("urlOrigine") if isinstance(origin, Mapping) else None
        nature = str(raw.get("natureContrat") or "")
        if raw.get("alternance") is True or re.search(
                r"apprentissage|professionnalisation", nature, re.IGNORECASE):
            kind = ContractType.APPRENTICESHIP
        else:
            kind = contract_type(title)
            if kind is ContractType.OTHER:
                kind = TYPES.get(str(raw.get("typeContrat")), ContractType.OTHER)
        return NormalizedOffer(
            source=self.source, external_id=raw_id,
            url=url if isinstance(url, str) and url else DETAIL_URL.format(id=raw_id),
            title=title, company=company or "Entreprise non communiquée",
            location=city(raw.get("lieuTravail")), contract_type=kind,
            description_text=raw.get("description") if isinstance(raw.get("description"), str)
            else "",
            published_at=parse_date(raw.get("dateCreation")),
        )


def city(place: Any) -> str | None:
    """« 69 - LYON 03 » → « Lyon » : sans département ni arrondissement, pour l'empreinte."""
    label = place.get("libelle") if isinstance(place, Mapping) else None
    if not isinstance(label, str):
        return None
    label = re.sub(r"^\s*(\d{2,3}|2[AB])\s*-\s*", "", label)
    label = re.sub(r"\s+\d{1,2}(e|er|ème)?\s*$", "", label, flags=re.IGNORECASE)
    return label.strip().title() or None
