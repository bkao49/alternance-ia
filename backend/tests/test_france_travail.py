"""Collecteur France Travail sur des réponses fictives : aucun appel réseau, aucune vraie clé."""

import json
from pathlib import Path

import httpx
import pytest
from fake_web import FakeClock, no_network, raw_response  # noqa: F401

from app import doctor
from app.collectors.api_client import ApiClient
from app.collectors.base import (
    CollectorError,
    ContractType,
    QuotaExceeded,
    SearchQuery,
    SourceBlocked,
)
from app.collectors.france_travail import (
    API_HOST,
    SCOPE_API,
    TOKEN_HOST,
    FranceTravailCollector,
    NotSubscribed,
)
from app.collectors.http_client import Throttle

FIXTURES = Path(__file__).parent / "fixtures" / "france_travail"
CLIENT_ID, SECRET = "id-fictif", "secret-fictif-0000"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeApi:
    """Serveur fictif : `token` et `search` sont des fonctions requête → réponse."""

    def __init__(self, search=None, token=None):
        self.search = search or (lambda r: raw_response(
            200, {"content-range": "offres 0-1/2"}, json_body=load("page1.json")))
        self.token = token or (lambda r: raw_response(
            200, json_body={"access_token": "jeton-fictif", "expires_in": 1499}))
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        return (self.token if request.url.host == TOKEN_HOST else self.search)(request)

    def searches(self):
        return [r for r in self.requests if r.url.host == API_HOST]


def make(api):
    clock = FakeClock()
    client = ApiClient("france_travail", API_HOST, transport=httpx.MockTransport(api),
                       throttle=Throttle(clock, clock.sleep))
    return FranceTravailCollector(CLIENT_ID, SECRET, client, clock=clock, sleep=clock.sleep), clock


def test_token_request_then_search_and_normalization():
    api = FakeApi()
    collector, _ = make(api)
    result = collector.collect(SearchQuery(keywords=("data", "ia"), location="69", max_results=10))
    assert result.error is None
    token_req = api.requests[0]
    assert token_req.method == "POST" and token_req.url.params["realm"] == "/partenaire"
    form = token_req.content.decode()
    assert "grant_type=client_credentials" in form
    assert f"application_{CLIENT_ID}" in form and SCOPE_API.split()[0] in form
    search = api.searches()[0]
    assert search.headers["authorization"] == "Bearer jeton-fictif"
    assert search.url.params["motsCles"] == "data ia" and search.url.params["departement"] == "69"
    assert search.url.params["range"] == "0-9"
    first, second = result.offers
    assert (first.external_id, first.title, first.company, first.location) == (
        "900AAAA", "Data Analyst H/F", "Globex SAS", "Lyon")
    assert first.contract_type is ContractType.PERMANENT
    assert first.url == "https://exemple.test/offre/900AAAA"  # suivi retiré
    assert second.contract_type is ContractType.APPRENTICESHIP and second.location == "Paris"
    assert second.company == "Initech"
    assert second.url == "https://candidat.francetravail.fr/offres/recherche/detail/900BBBB"
    assert "Personne Fictive" not in repr(result.offers)
    assert "rh@exemple.test" not in repr(result.offers)


def test_token_is_cached_until_expiry():
    api = FakeApi()
    collector, clock = make(api)
    collector.collect(SearchQuery(max_results=2))
    collector.collect(SearchQuery(max_results=2))
    assert sum(r.url.host == TOKEN_HOST for r in api.requests) == 1
    clock.now += 2000  # jeton expiré
    collector.collect(SearchQuery(max_results=2))
    assert sum(r.url.host == TOKEN_HOST for r in api.requests) == 2


def test_pagination_uses_bounded_ranges_and_stops_on_short_page():
    def search(request):
        start = int(request.url.params["range"].split("-")[0])
        count = 150 if start < 300 else 7
        body = {"resultats": [{"id": f"{start + i}", "intitule": "Data", "typeContrat": "CDI"}
                              for i in range(count)]}
        return raw_response(206, {"content-range": f"offres {start}-{start + count - 1}/9999"},
                            json_body=body)

    api = FakeApi(search=search)
    collector, _ = make(api)
    result = collector.collect(SearchQuery(max_results=1000))
    assert [r.url.params["range"] for r in api.searches()] == ["0-149", "150-299", "300-449"]
    assert len(result.offers) == 150 + 150 + 7


def test_first_index_never_exceeds_1000():
    def search(request):
        start = request.url.params["range"].split("-")[0]
        return raw_response(206, json_body={"resultats": [
            {"id": f"{start}-{i}", "intitule": "A", "typeContrat": "CDI"} for i in range(150)]})

    api = FakeApi(search=search)
    collector, _ = make(api)
    collector.collect(SearchQuery(max_results=1000))
    starts = [int(r.url.params["range"].split("-")[0]) for r in api.searches()]
    assert starts == [0, 150, 300, 450, 600, 750, 900]


def test_204_ends_the_collection():
    api = FakeApi(search=lambda r: raw_response(204))
    collector, _ = make(api)
    assert collector.collect(SearchQuery()).offers == []
    assert len(api.searches()) == 1


def test_defensive_mapping_and_contract_rules():
    api = FakeApi(search=lambda r: raw_response(200, json_body=load("page2.json")))
    collector, _ = make(api)
    result = collector.collect(SearchQuery(max_results=10))
    kinds = {o.external_id: o.contract_type for o in result.offers}
    assert kinds == {"900333": ContractType.INTERNSHIP, "900CCCC": ContractType.OTHER}
    assert result.rejected == 1 and result.error is None
    assert all(o.company == "Entreprise non communiquée" for o in result.offers)
    odd = collector.normalize({"id": "x", "intitule": "T", "lieuTravail": "texte", "entreprise": None})
    assert odd.location is None


def test_contract_filters_sent_to_the_api_only_when_safe():
    def params(kinds):
        api = FakeApi()
        collector, _ = make(api)
        collector.collect(SearchQuery(contract_types=frozenset(kinds)))
        return api.searches()[0].url.params

    assert params({ContractType.APPRENTICESHIP})["natureContrat"] == "E1,E2"
    assert params({ContractType.PERMANENT})["typeContrat"] == "CDI"
    assert params({ContractType.PERMANENT, ContractType.FIXED_TERM})["typeContrat"] == "CDI,CDD"
    mixed = params({ContractType.PERMANENT, ContractType.INTERNSHIP})
    assert "typeContrat" not in mixed and "natureContrat" not in mixed


def test_free_text_city_is_not_sent_and_insee_code_is():
    api = FakeApi()
    collector, _ = make(api)
    collector.collect(SearchQuery(location="Lyon"))
    collector.collect(SearchQuery(location="69123"))
    first, second = (r.url.params for r in api.searches())
    assert "commune" not in first and "departement" not in first
    assert second["commune"] == "69123"


def test_429_waits_retry_after_once_then_stops():
    calls = []

    def search(request):
        calls.append(1)
        return raw_response(429, {"retry-after": "7"}, text="")

    collector, clock = make(FakeApi(search=search))
    result = collector.collect(SearchQuery())
    assert isinstance(result.error, QuotaExceeded) and len(calls) == 2
    assert 7.0 in clock.slept


def test_429_with_a_long_retry_after_is_not_waited():
    collector, clock = make(FakeApi(search=lambda r: raw_response(
        429, {"retry-after": "3600"}, text="")))
    result = collector.collect(SearchQuery())
    assert isinstance(result.error, QuotaExceeded) and 3600.0 not in clock.slept


@pytest.mark.parametrize(("status", "kind", "words"), [
    (401, NotSubscribed, "non abonnée"), (403, SourceBlocked, "accès restreint")])
def test_refused_search_stops_the_source_cleanly(status, kind, words):
    collector, _ = make(FakeApi(search=lambda r: raw_response(status, text="x")))
    result = collector.collect(SearchQuery())
    assert type(result.error) is kind and words in result.error.message
    assert SECRET not in result.error.message


def test_refused_token_and_missing_keys_never_leak_secrets():
    collector, _ = make(FakeApi(token=lambda r: raw_response(
        400, json_body={"error": "invalid_scope"})))
    result = collector.collect(SearchQuery())
    assert isinstance(result.error, NotSubscribed) and SECRET not in str(result.error)
    empty = FranceTravailCollector("", "", ApiClient("france_travail", API_HOST))
    assert isinstance(empty.collect(SearchQuery()).error, CollectorError)


def test_doctor_probe_reports_each_case(monkeypatch):
    def run(api):
        monkeypatch.setattr(doctor, "FranceTravailCollector", lambda: make(api)[0])
        return doctor._france_travail_probe()

    ok = run(FakeApi(search=lambda r: raw_response(
        206, {"content-range": "offres 0-0/300749"}, json_body={"resultats": []})))
    assert ok.level == doctor.OK and "300749" in ok.message
    todo = run(FakeApi(search=lambda r: raw_response(401, text="")))
    assert todo.level == doctor.TODO and "pas abonnée" in todo.message
    refused = run(FakeApi(search=lambda r: raw_response(403, text="")))
    assert refused.level == doctor.ERROR and "accès restreint" in refused.message
    assert SECRET not in todo.message + refused.message
    keys = {"FRANCE_TRAVAIL_CLIENT_ID": "a", "FRANCE_TRAVAIL_CLIENT_SECRET": "b"}
    assert set(doctor.default_probes(keys)) == {"France Travail"}
