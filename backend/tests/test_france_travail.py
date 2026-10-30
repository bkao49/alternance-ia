"""Collecteur France Travail sur des réponses fictives enregistrées : aucun appel réseau, aucune
vraie clé (#12)."""

import json
import logging
from pathlib import Path

import httpx
import pytest
from fake_web import FakeClock, no_network, raw_response  # noqa: F401

from app.collectors.api_client import ApiClient
from app.collectors.base import (
    CollectorError,
    ContractType,
    NetworkError,
    SearchQuery,
    SourceBlocked,
    collect_all,
)
from app.collectors.fixture import FixtureCollector
from app.collectors.france_travail import FranceTravailCollector, city
from app.collectors.http_client import Throttle

FIXTURES = Path(__file__).parent / "fixtures"
SECRET = "secret-fictif-0000"
RESULTS = json.loads((FIXTURES / "france_travail" / "recherche.json").read_text(encoding="utf-8"))


class FakeFranceTravail:
    def __init__(self, search=None, token_status=200):
        self.search = search or (lambda _request: raw_response(206, json_body=RESULTS))
        self.token_status = token_status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "entreprise.francetravail.fr":
            if self.token_status != 200:
                return raw_response(self.token_status, json_body={"error": "invalid_client"})
            return raw_response(200, json_body={"access_token": "jeton-fictif",
                                                "expires_in": 1499, "token_type": "Bearer"})
        return self.search(request)

    def searches(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == "api.francetravail.io"]


def france_travail(api, client_id="id-fictif", secret=SECRET):
    clock = FakeClock()
    client = ApiClient("france_travail", "api.francetravail.io",
                       transport=httpx.MockTransport(api), throttle=Throttle(clock, clock.sleep))
    return FranceTravailCollector(client_id, secret, client, clock=clock)


def test_oauth2_then_search_and_normalize():
    api = FakeFranceTravail()
    result = france_travail(api).collect(SearchQuery(keywords=("data", "ia"), location="69"))
    assert result.error is None and result.rejected == 1
    token = api.requests[0]
    assert token.method == "POST" and token.url.params["realm"] == "/partenaire"
    form = dict(x.split("=", 1) for x in token.content.decode().split("&"))
    assert form["grant_type"] == "client_credentials" and form["scope"] == "api_offresdemploiv2+o2dsoffre"
    (search,) = api.searches()
    assert search.headers["authorization"] == "Bearer jeton-fictif"
    assert (search.url.params["motsCles"], search.url.params["departement"]) == ("data,ia", "69")
    assert search.url.params["range"] == "0-99"
    ds, alt, ml = result.offers
    assert (ds.title, ds.company, ds.location, ds.contract_type) == (
        "Data Scientist (H/F)", "GLOBEX", "Lyon", ContractType.PERMANENT)
    assert (alt.location, alt.contract_type) == ("Paris", ContractType.APPRENTICESHIP)
    assert (ml.company, ml.location, ml.contract_type) == (
        "Entreprise non communiquée", "Nantes", ContractType.FIXED_TERM)
    assert ml.url == "https://candidat.francetravail.fr/offres/recherche/detail/999AAA3"


def test_recruiter_contact_is_never_kept():
    for offer in france_travail(FakeFranceTravail()).collect(SearchQuery()).offers:
        dumped = offer.model_dump_json()
        assert "Jeanne" not in dumped and "Imaginaire" not in dumped and "@" not in dumped


def test_paging_reuses_the_token_and_stops_on_204():
    pages = iter([raw_response(206, json_body={"resultats": [{"id": f"P{i}"} for i in range(150)]}),
                  raw_response(204)])
    api = FakeFranceTravail(search=lambda _r: next(pages))
    records = list(france_travail(api).fetch(SearchQuery(max_results=1000)))
    assert len(records) == 150
    assert [r.url.params["range"] for r in api.searches()] == ["0-149", "150-299"]
    assert len(api.requests) == 3  # un seul jeton pour les deux pages


def test_range_never_goes_beyond_the_api_limit():
    api = FakeFranceTravail(
        search=lambda _r: raw_response(206, json_body={"resultats": [{"id": "X"}] * 150}))
    list(france_travail(api).fetch(SearchQuery(max_results=1000)))
    starts = [int(r.url.params["range"].split("-")[0]) for r in api.searches()]
    assert starts[-1] <= 3000 and len(starts) == 7  # 1000 résultats au plus : 7 plages


def test_contract_filter_is_sent_only_when_the_api_knows_it():
    api = FakeFranceTravail()
    collector = france_travail(api)
    collector.collect(SearchQuery(contract_types=frozenset({ContractType.PERMANENT,
                                                            ContractType.FIXED_TERM})))
    collector.collect(SearchQuery(contract_types=frozenset({ContractType.APPRENTICESHIP})))
    first, second = api.searches()
    assert first.url.params["typeContrat"] == "CDD,CDI" and "typeContrat" not in second.url.params


def test_missing_keys_stop_the_source_without_any_call():
    api = FakeFranceTravail()
    result = france_travail(api, client_id="", secret="").collect(SearchQuery())
    assert isinstance(result.error, CollectorError) and api.requests == []


def test_refused_credentials_block_the_source_without_leaking_the_secret(caplog):
    caplog.set_level(logging.DEBUG)
    result = france_travail(FakeFranceTravail(token_status=401)).collect(SearchQuery())
    assert isinstance(result.error, SourceBlocked)
    assert SECRET not in str(result.error) and SECRET not in caplog.text
    assert result.error.__context__ is None


def test_france_travail_outage_does_not_stop_other_sources():
    api = FakeFranceTravail(search=lambda _r: raw_response(503))
    other = FixtureCollector(FIXTURES / "collectors" / "source_a.json", source="fixture_a")
    down, ok = collect_all([france_travail(api), other], SearchQuery())
    assert isinstance(down.error, NetworkError) and down.offers == []
    assert ok.error is None and ok.offers


@pytest.mark.parametrize(
    ("label", "expected"),
    [("69 - LYON 03", "Lyon"), ("2A - AJACCIO", "Ajaccio"), ("974 - SAINT-DENIS", "Saint-Denis"),
     ("Télétravail", "Télétravail"), ("75 - PARIS 1er", "Paris")],
)
def test_city_label(label, expected):
    assert city({"libelle": label}) == expected
