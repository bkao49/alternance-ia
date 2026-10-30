"""Collecteur Adzuna sur des réponses fictives enregistrées : aucun appel réseau, aucune vraie clé."""

import datetime as dt
import json
import logging
from pathlib import Path

import httpx
import pytest
from fake_web import FakeClock, no_network, raw_response  # noqa: F401

from app.collectors.adzuna import AdzunaCollector
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

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_ID, FAKE_KEY = "id-fictif", "cle-fictive-0000"


class FakeApi:
    def __init__(self, pages=None, status=200, headers=None):
        self.pages = pages if pages is not None else {
            1: json.loads((FIXTURES / "adzuna" / "page1.json").read_text(encoding="utf-8")),
            2: json.loads((FIXTURES / "adzuna" / "page2.json").read_text(encoding="utf-8")),
        }
        self.status, self.headers = status, headers or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return raw_response(self.status, self.headers, text="<html>erreur</html>")
        page = int(request.url.path.rsplit("/", 1)[1])
        return raw_response(200, json_body=self.pages.get(page, {"results": []}))


def adzuna(api: FakeApi, app_id=FAKE_ID, app_key=FAKE_KEY) -> tuple[AdzunaCollector, FakeClock]:
    clock = FakeClock()
    client = ApiClient("adzuna", "api.adzuna.com", transport=httpx.MockTransport(api),
                       throttle=Throttle(clock, clock.sleep))
    return AdzunaCollector(app_id, app_key, client), clock


def test_collects_and_normalizes_paged_results():
    api = FakeApi()
    collector, _ = adzuna(api)
    result = collector.collect(SearchQuery(keywords=("data", "ia"), location="Lyon", max_results=3))
    assert result.error is None
    assert [o.external_id for o in result.offers] == ["4400000001", "4400000002", "4400000003"]
    first = result.offers[0]
    assert (first.title, first.company, first.location) == ("Data Scientist & IA", "Globex SAS", "Lyon")
    assert first.contract_type is ContractType.PERMANENT
    assert first.description_text.startswith("Nous recherchons un(e) Data Scientist")
    assert first.published_at == dt.datetime(2026, 10, 28, 9, 15, tzinfo=dt.UTC)
    assert first.url.startswith("https://www.adzuna.fr/land/ad/4400000001")
    assert "utm_medium" not in first.url
    # max_results atteint sur la page 1 : la page 2 n'est pas demandée (quota ménagé).
    assert len(api.requests) == 1
    params = api.requests[0].url.params
    assert (params["what"], params["where"], params["results_per_page"]) == ("data ia", "Lyon", "3")
    assert api.requests[0].url.host == "api.adzuna.com"
    assert api.requests[0].url.path == "/v1/api/jobs/fr/search/1"


def test_pages_are_read_until_a_short_page_then_contracts_are_mapped():
    api = FakeApi()
    collector, clock = adzuna(api)
    records = list(collector.fetch(SearchQuery(max_results=3)))  # 3 par page
    assert [r.url.path[-1] for r in api.requests] == ["1", "2"]  # page 2 incomplète : fin
    assert clock.slept == [3.0]  # 3 s entre les deux appels
    offers = [collector.normalize(r) for r in records if "id" in r]
    assert {o.external_id: o.contract_type for o in offers} == {
        "4400000001": ContractType.PERMANENT, "4400000002": ContractType.APPRENTICESHIP,
        "4400000003": ContractType.FIXED_TERM, "4400000004": ContractType.INTERNSHIP,
    }
    assert offers[3].location == "Nantes" and offers[2].location == "France"


def test_record_without_id_is_rejected_alone():
    api = FakeApi(pages={1: json.loads((FIXTURES / "adzuna" / "page2.json").read_text("utf-8"))})
    collector, _ = adzuna(api)
    result = collector.collect(SearchQuery())
    assert [o.external_id for o in result.offers] == ["4400000004"] and result.rejected == 1


def test_permanent_filter_is_sent_to_the_api():
    api = FakeApi()
    collector, _ = adzuna(api)
    collector.collect(SearchQuery(contract_types=frozenset({ContractType.PERMANENT})))
    assert api.requests[0].url.params["permanent"] == "1"


def test_missing_keys_stop_the_source_without_any_call():
    api = FakeApi()
    collector, _ = adzuna(api, app_id="", app_key="")
    result = collector.collect(SearchQuery())
    assert isinstance(result.error, CollectorError) and "ADZUNA_APP_ID" in result.error.message
    assert api.requests == []


def test_keys_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", FAKE_ID)
    monkeypatch.setenv("ADZUNA_APP_KEY", FAKE_KEY)
    collector = AdzunaCollector()
    assert (collector.app_id, collector.app_key) == (FAKE_ID, FAKE_KEY)
    collector.client.close()


@pytest.mark.parametrize(
    ("status", "headers", "error"),
    [(401, {}, SourceBlocked), (403, {}, SourceBlocked), (429, {"retry-after": "60"}, QuotaExceeded),
     (503, {}, NetworkError)],
)
def test_api_errors_are_typed_and_never_leak_the_key(status, headers, error, caplog):
    caplog.set_level(logging.DEBUG)
    collector, _ = adzuna(FakeApi(status=status, headers=headers))
    result = collector.collect(SearchQuery())
    assert isinstance(result.error, error)
    if error is QuotaExceeded:
        assert result.error.retry_after == 60
    assert FAKE_KEY not in str(result.error) and "<html>" not in str(result.error)
    assert FAKE_KEY not in caplog.text


def test_transport_failure_does_not_leak_the_key():
    def boom(request):
        raise httpx.ConnectError(f"échec vers {request.url}")

    client = ApiClient("adzuna", "api.adzuna.com", transport=httpx.MockTransport(boom),
                       throttle=Throttle(FakeClock(), lambda _s: None))
    result = AdzunaCollector(FAKE_ID, FAKE_KEY, client).collect(SearchQuery())
    assert isinstance(result.error, NetworkError)
    assert FAKE_KEY not in str(result.error)
    assert result.error.__cause__ is None and result.error.__context__ is None


def test_adzuna_outage_does_not_stop_other_sources():
    collector, _ = adzuna(FakeApi(status=500))
    other = FixtureCollector(FIXTURES / "collectors" / "source_a.json", source="fixture_a")
    down, ok = collect_all([collector, other], SearchQuery())
    assert isinstance(down.error, NetworkError) and down.offers == []
    assert ok.error is None and ok.offers


def test_httpx_debug_logs_never_show_the_key(caplog):
    logging.getLogger("httpx").setLevel(logging.DEBUG)  # configuration plus bavarde, plus tard
    try:
        caplog.set_level(logging.DEBUG)
        collector, _ = adzuna(FakeApi())
        collector.collect(SearchQuery(max_results=3))
        logging.getLogger("httpx").info("HTTP Request: GET https://api.adzuna.com/x?app_key=%s", FAKE_KEY)
    finally:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    assert FAKE_KEY not in caplog.text and FAKE_ID not in caplog.text


def test_compression_bomb_from_the_api_is_stopped():
    import gzip

    bomb = gzip.compress(b" " * 40_000_000)
    client = ApiClient("adzuna", "api.adzuna.com", throttle=Throttle(FakeClock(), lambda _s: None),
                       transport=httpx.MockTransport(
                           lambda _r: raw_response(200, {"content-encoding": "gzip"}, content=bomb)))
    result = AdzunaCollector(FAKE_ID, FAKE_KEY, client).collect(SearchQuery())
    assert isinstance(result.error, CollectorError) and "volumineuse" in result.error.message


def test_fixed_term_filter_and_apprenticeship_read_from_the_snippet():
    api = FakeApi()
    collector, _ = adzuna(api)
    collector.collect(SearchQuery(contract_types=frozenset({ContractType.FIXED_TERM})))
    assert api.requests[0].url.params["contract"] == "1"
    offer = collector.normalize({"id": "9", "title": "Data Analyst", "contract_type": "contract",
                                 "description": "Poste en contrat d'apprentissage de 24 mois.",
                                 "redirect_url": "https://www.adzuna.fr/land/ad/9"})
    assert offer.contract_type is ContractType.APPRENTICESHIP


def test_api_path_must_stay_on_the_fixed_host():
    with ApiClient("adzuna", "api.adzuna.com") as client, pytest.raises(ValueError):
        client.get_json("@autre-hote.test/x")
