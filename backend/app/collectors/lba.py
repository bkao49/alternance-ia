"""Collecteur La Bonne Alternance : API « Recherche d'opportunités d'emploi en alternance » (#11, #12).

`GET https://api.apprentissage.beta.gouv.fr/api/job/v1/search`, clé `LBA_API_TOKEN` en
`Authorization: Bearer` (spécification OpenAPI du dépôt public mission-apprentissage/api-apprentissage).
Les offres viennent de La Bonne Alternance et de ses partenaires, dont France Travail
(`identifier.partner_label`). Fiche : `docs/sources/la-bonne-alternance.md`.

On ne lit jamais `apply.phone` ni `apply.recipient_id` (RGPD). La liste `recruiters`
(entreprises à démarcher sans offre publiée) n'est pas collectée : ce ne sont pas des offres.
"""

import datetime as dt
import os
import re
from collections.abc import Iterator, Mapping
from typing import Any, Self

from app.collectors.api_client import ApiClient
from app.collectors.base import (
    Collector,
    CollectorError,
    ContractType,
    InvalidResponse,
    NormalizedOffer,
    OfferExpired,
    SearchQuery,
)
from app.collectors.web import parse_date

API_HOST = "api.apprentissage.beta.gouv.fr"
SEARCH_PATH = "/api/job/v1/search"
# Métiers ROME de la Data et de l'IA (proposition, à valider par le PO) : études et
# développement informatique, expertise et support SI, études et prospectives
# socio-économiques (data analyst), production et exploitation de SI.
DATA_IA_ROMES = ("M1805", "M1802", "M1403", "M1810")
DEPARTMENT = re.compile(r"\d{2}|2[AB]|97\d")
# Code postal, ville, puis arrondissement (« 11 », « 1er ») ou « Cedex 1 » facultatifs.
POSTAL_CITY = re.compile(
    r"\b\d{5}\s+(?P<city>[^\d,]+?)(\s+\d{1,2}(e|er|ème)?)?(\s+cedex(\s+\d+)?)?\s*$", re.IGNORECASE,
)


class LbaCollector(Collector):
    source = "lba"

    def __init__(
        self, token: str | None = None, romes: tuple[str, ...] = DATA_IA_ROMES,
        client: ApiClient | None = None,
    ):
        self.token = os.environ.get("LBA_API_TOKEN", "") if token is None else token
        self.romes = romes
        self.client = client or ApiClient(self.source, API_HOST)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.client.close()

    def fetch(self, query: SearchQuery) -> Iterator[Mapping[str, Any]]:
        """Un seul appel : l'API renvoie au plus 150 offres par source, sans pagination.
        Toutes les offres sont en alternance : inutile d'appeler pour un autre contrat."""
        if not self.token:
            raise CollectorError(self.source, "clé LBA_API_TOKEN absente")
        if query.contract_types and ContractType.APPRENTICESHIP not in query.contract_types:
            return
        params: dict[str, Any] = {"romes": ",".join(self.romes)}
        if query.location and DEPARTMENT.fullmatch(query.location.strip()):
            params["departements"] = [query.location.strip()]
        payload = self.client.get_json(
            SEARCH_PATH, params, headers={"Authorization": f"Bearer {self.token}"},
        )
        jobs = payload.get("jobs") if isinstance(payload, Mapping) else None
        if not isinstance(jobs, list):
            raise InvalidResponse(self.source, "clé « jobs » absente ou invalide")
        yield from jobs

    def normalize(self, raw: Mapping[str, Any]) -> NormalizedOffer:
        if not isinstance(raw, Mapping):
            raise InvalidResponse(self.source, "offre illisible")
        identifier, offer = _map(raw.get("identifier")), _map(raw.get("offer"))
        workplace, apply = _map(raw.get("workplace")), _map(raw.get("apply"))
        external_id = _external_id(identifier)
        if external_id is None:
            raise InvalidResponse(self.source, "offre sans identifiant")
        publication = _map(offer.get("publication"))
        expiration = parse_date(publication.get("expiration"))
        if offer.get("status") not in (None, "Active") or (
                expiration is not None and expiration < dt.datetime.now(dt.UTC)):
            raise OfferExpired(self.source, external_id)  # pourvue, annulée ou échue
        company = next((workplace.get(k) for k in ("name", "brand", "legal_name")
                        if isinstance(workplace.get(k), str) and workplace.get(k)), None)
        description = offer.get("description")
        return NormalizedOffer(
            source=self.source, external_id=external_id, url=apply.get("url") or "",
            title=offer.get("title") or "", company=company or "Entreprise non communiquée",
            location=city(_map(workplace.get("location")).get("address")),
            contract_type=ContractType.APPRENTICESHIP,
            description_text=description if isinstance(description, str) else "",
            published_at=parse_date(publication.get("creation")),
        )


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _external_id(identifier: Mapping[str, Any]) -> str | None:
    """Identifiant LBA s'il existe ; sinon partenaire + identifiant chez le partenaire, pour
    qu'une offre France Travail et une offre LBA ne se confondent jamais."""
    own = identifier.get("id")
    if isinstance(own, str) and own.strip():
        return own.strip()[:200]
    label, partner_id = identifier.get("partner_label"), identifier.get("partner_job_id")
    if isinstance(label, str) and isinstance(partner_id, str) and label and partner_id:
        return f"{label}:{partner_id}"[:200]
    return None


def city(address: Any) -> str | None:
    """« 12 rue Imaginaire 69003 Lyon » → « Lyon » (ville seule, pour l'empreinte)."""
    if not isinstance(address, str):
        return None
    match = POSTAL_CITY.search(address.strip())
    if not match:
        return None
    return match["city"].strip().title() or None
