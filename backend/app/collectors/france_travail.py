"""Collecteur France Travail : API « Offres d'emploi v2 » (francetravail.io), `docs/sources/france_travail.md`.

Jeton OAuth2 `client_credentials` (`FRANCE_TRAVAIL_CLIENT_ID` / `FRANCE_TRAVAIL_CLIENT_SECRET`),
mis en cache jusqu'à son expiration, puis recherche paginée par plages `range`.

ATTENTION : la documentation officielle n'a pas pu être lue (page vide, et data.gouv signale que
l'API est « plus exposée » le temps d'une analyse des conditions de réutilisation). Les constantes
marquées « À VALIDER » viennent de sources tierces (wrapper, guides) et doivent être confirmées par un
appel réel : `docker compose run --rm doctor`. Le mapping des champs est défensif : un champ absent
ne fait jamais échouer la collecte.

On ne lit jamais `contact` (nom, courriel, téléphone du recruteur : RGPD).
"""

import os
import re
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Self

import httpx

from app.collectors.api_client import ApiClient
from app.collectors.base import (
    Collector,
    CollectorError,
    ContractType,
    InvalidResponse,
    NormalizedOffer,
    QuotaExceeded,
    SearchQuery,
    SourceBlocked,
)
from app.collectors.web import contract_type, parse_date

# --- À VALIDER par un appel réel (doctor) --------------------------------------------------
IDP_HOST = "entreprise.francetravail.fr"
TOKEN_PATH = "/connexion/oauth2/access_token"
TOKEN_PARAMS = {"realm": "/partenaire"}
# Scope : « application_<client_id> » s'ajoute au scope de l'API (format du wrapper et des guides).
OFFERS_SCOPE = "api_offresdemploiv2 o2dsoffre"
OFFERS_HOST = "api.francetravail.io"
SEARCH_PATH = "/partenaire/offresdemploi/v2/offres/search"
# typeContrat de l'API → contrat Ereuna (les autres valeurs : MIS intérim, SAI, LIB… → OTHER).
TYPE_CONTRATS = {"CDI": ContractType.PERMANENT, "CDD": ContractType.FIXED_TERM}
# natureContrat : E1 « contrat apprentissage », E2 « contrat de professionnalisation ».
NATURE_ALTERNANCE = ("E1", "E2")
# Page de détail publique, si l'offre n'a pas d'URL d'origine.
DETAIL_URL = "https://candidat.francetravail.fr/offres/recherche/detail/{id}"
# -------------------------------------------------------------------------------------------

PAGE_SIZE = 150  # plage `range` : au plus 150 offres par requête
MAX_FIRST = 1000  # le premier indice de la plage ne dépasse pas 1000
TOKEN_MARGIN = 60  # secondes : le jeton est renouvelé un peu avant son expiration
MAX_WAIT = 30.0  # attente maximale d'un 429 avant l'unique nouvel essai
DEPARTMENT = re.compile(r"0[1-9]|1\d|2[1-9AB]|[3-8]\d|9[0-5]|97[1-6]", re.IGNORECASE)
INSEE = re.compile(r"\d{5}|2[AB]\d{3}", re.IGNORECASE)
CONTENT_RANGE_TOTAL = re.compile(r"/(\d+)\s*$")
PLACE = re.compile(r"^\s*(?:\d{1,3}[AB]?\s*-\s*)?(?P<city>.*?)(?:\s+\d{1,2})?\s*$", re.IGNORECASE)


class NotSubscribed(SourceBlocked):
    """401 ou jeton refusé : application non abonnée à l'API, ou scope différent."""


class FranceTravailCollector(Collector):
    source = "france_travail"

    def __init__(
        self, client_id: str | None = None, client_secret: str | None = None,
        client: ApiClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        env = os.environ
        self.client_id = (env.get("FRANCE_TRAVAIL_CLIENT_ID", "") if client_id is None
                          else client_id).strip()
        self.client_secret = (env.get("FRANCE_TRAVAIL_CLIENT_SECRET", "") if client_secret is None
                              else client_secret).strip()
        self.client = client or ApiClient(self.source, OFFERS_HOST)
        self.clock, self.sleep = clock, sleep
        self._token: str | None = None
        self._expires_at = 0.0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.client.close()

    # --- Jeton ---------------------------------------------------------------------------

    def token(self) -> str:
        if self._token and self.clock() < self._expires_at:
            return self._token
        if not (self.client_id and self.client_secret):
            raise CollectorError(
                self.source, "clés FRANCE_TRAVAIL_CLIENT_ID / FRANCE_TRAVAIL_CLIENT_SECRET absentes")
        refused = None
        try:
            payload, _ = self.client.request_full(
                "POST", TOKEN_PATH, params=TOKEN_PARAMS, host=IDP_HOST, data={
                    "grant_type": "client_credentials", "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": f"application_{self.client_id} {OFFERS_SCOPE}"})
        except (SourceBlocked, InvalidResponse) as exc:
            refused = exc.message
        if refused is not None:  # 400 (invalid_client, invalid_scope) ou 401
            raise NotSubscribed(
                self.source, f"jeton refusé ({refused}) : identifiants ou scope invalides")
        token = payload.get("access_token") if isinstance(payload, Mapping) else None
        lifetime = payload.get("expires_in") if isinstance(payload, Mapping) else None
        if not isinstance(token, str) or not token:
            raise InvalidResponse(self.source, "jeton absent de la réponse")
        if isinstance(lifetime, bool) or not isinstance(lifetime, int | float):
            lifetime = 0  # durée inconnue : le jeton ne sert qu'une fois
        self._token = token
        self._expires_at = self.clock() + max(0.0, lifetime - TOKEN_MARGIN)
        return token

    # --- Recherche -----------------------------------------------------------------------

    def _search(self, params: Mapping[str, Any]) -> tuple[Any, httpx.Headers]:
        """Un appel de recherche. 429 : une seule nouvelle tentative après `Retry-After`."""
        for attempt in (1, 2):
            problem = None
            try:
                return self.client.request_full(
                    "GET", SEARCH_PATH, params=params,
                    headers={"Authorization": f"Bearer {self.token()}"})
            except QuotaExceeded as exc:
                if attempt == 2 or (exc.retry_after or 5.0) > MAX_WAIT:
                    raise
                wait = exc.retry_after or 5.0
            except SourceBlocked as exc:
                self._token = None  # jeton peut-être révoqué : le prochain appel en demande un autre
                problem = exc.message
                wait = 0.0
            if problem is not None:
                if "HTTP 403" in problem:
                    raise SourceBlocked(
                        self.source, "accès restreint (HTTP 403) : l'API Offres d'emploi "
                        "n'est pas ouverte à cette application")
                raise NotSubscribed(
                    self.source, f"accès refusé ({problem}) : application non abonnée à l'API "
                    "Offres d'emploi v2, ou scope différent")
            self.sleep(wait)
        raise AssertionError("inatteignable")  # pragma: no cover

    def check(self) -> int:
        """Jeton + une recherche de une offre (`range=0-0`) : total d'offres lu dans `Content-Range`."""
        _, headers = self._search({"range": "0-0"})
        match = CONTENT_RANGE_TOTAL.search(headers.get("content-range", ""))
        return int(match[1]) if match else 0

    def fetch(self, query: SearchQuery) -> Iterator[Mapping[str, Any]]:
        params = _filters(query)
        fetched = 0
        for first in range(0, MAX_FIRST + 1, PAGE_SIZE):
            size = min(PAGE_SIZE, query.max_results - fetched)
            if size <= 0:
                return
            payload, headers = self._search({**params, "range": f"{first}-{first + size - 1}"})
            if payload is None:  # 204 : plus aucune offre
                return
            results = payload.get("resultats") if isinstance(payload, Mapping) else None
            if not isinstance(results, list):
                raise InvalidResponse(self.source, "clé « resultats » absente ou invalide")
            yield from results
            fetched += len(results)
            total = CONTENT_RANGE_TOTAL.search(headers.get("content-range", ""))
            if len(results) < size or (total and first + len(results) >= int(total[1])):
                return

    def normalize(self, raw: Mapping[str, Any]) -> NormalizedOffer:
        raw_id = raw.get("id") if isinstance(raw, Mapping) else None
        if isinstance(raw_id, bool) or not isinstance(raw_id, str | int) or raw_id == "":
            raise InvalidResponse(self.source, "offre sans identifiant")
        offer_id = str(raw_id)
        origin = _map(raw.get("origineOffre")).get("urlOrigine")
        description = raw.get("description")
        title = raw.get("intitule")
        return NormalizedOffer(
            source=self.source, external_id=offer_id,
            url=origin if isinstance(origin, str) and origin else DETAIL_URL.format(id=offer_id),
            title=title if isinstance(title, str) else "",
            company=_text(_map(raw.get("entreprise")).get("nom")) or "Entreprise non communiquée",
            location=_city(_map(raw.get("lieuTravail")).get("libelle")),
            contract_type=_contract(raw, title if isinstance(title, str) else ""),
            description_text=description if isinstance(description, str) else "",
            published_at=parse_date(raw.get("dateCreation")),
        )


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _filters(query: SearchQuery) -> dict[str, Any]:
    """Filtres envoyés à l'API (le reste est filtré après coup par `collect`).

    Lieu : département (« 69 ») ou code commune INSEE (« 69123 ») ; un nom de ville libre n'est pas
    transmis (l'API n'accepte pas de texte), faute de table de correspondance. Contrat : un filtre
    serveur seulement quand il est sûr ; l'alternance est un CDD ou un CDI « natureContrat » E1/E2."""
    params: dict[str, Any] = {}
    if query.keywords:
        params["motsCles"] = " ".join(query.keywords)
    place = (query.location or "").strip()
    if DEPARTMENT.fullmatch(place):
        params["departement"] = place.upper()
    elif INSEE.fullmatch(place):
        params["commune"] = place.upper()
    kinds = query.contract_types
    if kinds == {ContractType.APPRENTICESHIP}:
        params["natureContrat"] = ",".join(NATURE_ALTERNANCE)
    elif kinds and kinds <= {ContractType.PERMANENT, ContractType.FIXED_TERM}:
        params["typeContrat"] = ",".join(
            code for code, kind in TYPE_CONTRATS.items() if kind in kinds)
    return params


def _contract(raw: Mapping[str, Any], title: str) -> ContractType:
    nature = str(raw.get("natureContrat") or "")
    if str(raw.get("natureContratCode") or raw.get("natureContrat") or "").upper() in NATURE_ALTERNANCE \
            or contract_type(nature) is ContractType.APPRENTICESHIP:
        return ContractType.APPRENTICESHIP
    from_title = contract_type(title)
    if from_title in (ContractType.APPRENTICESHIP, ContractType.INTERNSHIP):
        return from_title
    return TYPE_CONTRATS.get(str(raw.get("typeContrat") or "").upper(), ContractType.OTHER)


def _city(label: Any) -> str | None:
    """« 69 - LYON 03 » → « Lyon » (ville seule, pour l'empreinte entre sources)."""
    if not isinstance(label, str) or not label.strip():
        return None
    match = PLACE.match(label[:200])
    city = (match["city"] if match else label).strip()
    return city.title() if city else None
