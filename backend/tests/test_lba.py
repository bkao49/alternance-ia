"""Collecteur La Bonne Alternance (#11, #12) sur une réponse fictive enregistrée : aucun appel
réseau, aucune vraie clé."""

import datetime as dt
import json
import logging
import time
from pathlib import Path

import httpx
import pytest
from fake_web import FakeClock, no_network, raw_response  # noqa: F401

from app.collectors.api_client import ApiClient
from app.collectors.base import (
    CollectorError,
    ContractType,
    NetworkError,
    QuotaExceeded,
    SearchQuery,
    SourceBlocked,
    collect_all,
)
from app.collectors.fixture import FixtureCollector
from app.collectors.http_client import Throttle
from app.collectors.lba import LbaCollector, city

FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = "jeton-fictif-0000"
NOW = dt.datetime(2026, 10, 30, 12, tzinfo=dt.UTC)
RESPONSE = json.loads((FIXTURES / "lba" / "recherche.json").read_text(encoding="utf-8"))


class FakeLba:
    def __init__(self, status=200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return raw_response(self.status, json_body={"message": "erreur"})
        return raw_response(200, json_body=RESPONSE)


def lba(api, token=TOKEN) -> LbaCollector:
    clock = FakeClock()
    client = ApiClient("lba", "api.apprentissage.beta.gouv.fr",
                       transport=httpx.MockTransport(api), throttle=Throttle(clock, clock.sleep))
    return LbaCollector(token, client=client, now=lambda: NOW)


def test_search_and_normalize_lba_and_partner_offers():
    api = FakeLba()
    result = lba(api).collect(SearchQuery(location="69"))
    assert result.error is None and result.rejected == 1
    (request,) = api.requests
    assert (request.url.host, request.url.path) == ("api.apprentissage.beta.gouv.fr",
                                                     "/api/job/v1/search")
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.url.params["romes"] == "M1805,M1802,M1403,M1810"
    assert request.url.params.get_list("departements") == ["69"]
    own, partner = result.offers
    assert (own.external_id, own.title, own.company, own.location) == (
        "offres_emploi_lba:6720aa0000000000000000a1", "Alternant Data Scientist", "Globex",
        "Lyon")
    assert own.contract_type is ContractType.APPRENTICESHIP
    assert (partner.external_id, partner.company, partner.location) == (
        "France Travail:999FT01", "Initech", "Paris")
    assert partner.url.startswith("https://candidat.francetravail.fr/")


def test_filled_offer_is_reported_as_expired():
    result = lba(FakeLba()).collect(SearchQuery())
    # Pourvue (statut) et échue (date passée) ; l'offre qui expire en décembre reste.
    assert result.expired == ["offres_emploi_lba:6720aa0000000000000000a3", "France Travail:999FT02"]
    assert "offres_emploi_lba:6720aa0000000000000000a1" in {o.external_id for o in result.offers}


def test_recruiter_phone_and_spontaneous_recruiters_are_never_kept():
    for offer in lba(FakeLba()).collect(SearchQuery()).offers:
        dumped = offer.model_dump_json()
        assert "06 00" not in dumped and "recipient" not in dumped and "Vandelay" not in dumped


def test_no_call_when_only_other_contracts_are_wanted():
    api = FakeLba()
    result = lba(api).collect(SearchQuery(contract_types=frozenset({ContractType.PERMANENT})))
    assert result.error is None and result.offers == [] and api.requests == []


def test_missing_token_stops_the_source_without_any_call():
    api = FakeLba()
    result = lba(api, token="").collect(SearchQuery())
    assert isinstance(result.error, CollectorError) and "LBA_API_TOKEN" in result.error.message
    assert api.requests == []


def test_refused_token_blocks_the_source_without_leaking_it(caplog):
    caplog.set_level(logging.DEBUG)
    result = lba(FakeLba(status=401)).collect(SearchQuery())
    assert isinstance(result.error, SourceBlocked) and TOKEN not in str(result.error)
    assert TOKEN not in caplog.text and result.error.__context__ is None


def test_outage_of_lba_does_not_stop_other_sources():
    other = FixtureCollector(FIXTURES / "collectors" / "source_a.json", source="fixture_a")
    down, ok = collect_all([lba(FakeLba(status=503)), other], SearchQuery())
    assert isinstance(down.error, NetworkError) and down.offers == []
    assert ok.error is None and ok.offers


@pytest.mark.parametrize(
    ("address", "expected"),
    [("12 rue Imaginaire 69003 Lyon", "Lyon"), ("75011 PARIS 11", "Paris"),
     ("1 place Fictive 44000 Nantes Cedex 1", "Nantes"), ("75007 PARIS, FRANCE", "Paris"),
     ("69001 Lyon France", "Lyon"), ("75008 Paris 8e Arrondissement", "Paris"),
     ("Lyon", None), (None, None)],
)
def test_city_from_address(address, expected):
    assert city(address) == expected


def test_hostile_address_is_parsed_in_linear_time():
    started = time.monotonic()
    city("00000 a" + " " * 50_000 + ",")
    city("75011 " + "x " * 500_000)
    assert time.monotonic() - started < 1


@pytest.mark.parametrize(("location", "sent"), [("2a", ["2A"]), ("974", ["974"]), ("00", None),
                                                ("99", None), ("Lyon", None)])
def test_only_real_departments_are_sent(location, sent):
    api = FakeLba()
    lba(api).collect(SearchQuery(location=location))
    assert (api.requests[0].url.params.get_list("departements") or None) == sent


def test_rate_limit_419_is_a_quota_to_retry():
    result = lba(FakeLba(status=419)).collect(SearchQuery())
    assert isinstance(result.error, QuotaExceeded) and result.error.retryable


@pytest.mark.parametrize("token", [" jeton-fictif\n", "jeton fictif", "jéton"])
def test_token_is_cleaned_or_refused_without_any_call(token):
    api = FakeLba()
    result = lba(api, token=token).collect(SearchQuery())
    if token.strip() == "jeton-fictif":
        assert api.requests[0].headers["authorization"] == "Bearer jeton-fictif"
    else:
        assert isinstance(result.error, CollectorError) and api.requests == []
        assert token not in str(result.error)
