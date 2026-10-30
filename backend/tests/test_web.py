"""Robot web générique (#59) sur des pages HTML fictives enregistrées : aucun appel réseau."""

import datetime as dt
from pathlib import Path

import pytest
from fake_web import HTML, FakeSite, make_client, no_network  # noqa: F401
from pydantic import ValidationError

from app.collectors.base import ContractType, SearchQuery, SourceBlocked
from app.collectors.web import SiteConfig, WebCollector, contract_type, load_sites

PAGES = Path(__file__).parent / "fixtures" / "web"


def page(name: str):
    return (200, HTML, (PAGES / name).read_text(encoding="utf-8"))


def collector(site: FakeSite, **overrides) -> WebCollector:
    config = load_sites(PAGES / "sites.toml")[0]
    config = SiteConfig(**(config.model_dump() | overrides))
    return WebCollector(config, make_client(site, source=config.source))


def careers_site(**routes) -> FakeSite:
    return FakeSite({
        "/offres": page("liste.html"),
        "/offres/ds-stage": page("offre-jsonld.html"),
        "/offres/ml-alternance": page("offre-css.html"),
        **routes,
    })


def test_crawls_listing_then_offer_pages_with_jsonld_first_then_css():
    site = careers_site()
    result = collector(site).collect(SearchQuery())
    assert result.error is None and result.rejected == 0
    jsonld, css = result.offers
    assert (jsonld.external_id, jsonld.title, jsonld.company, jsonld.location) == (
        "GX-42", "Stagiaire Data Scientist", "Globex SAS", "Lyon")
    assert jsonld.contract_type is ContractType.INTERNSHIP
    assert jsonld.url == "https://carrieres.example.com/offres/ds-stage"
    assert jsonld.published_at == dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    assert "modèles de prévision" in jsonld.description_text
    assert "<b>" not in jsonld.description_text
    assert (css.title, css.company, css.location) == (
        "Alternant·e Ingénieur Machine Learning", "Globex", "Paris")
    assert css.contract_type is ContractType.APPRENTICESHIP
    assert "PyTorch" in css.description_text
    # Lien externe, robots.txt et lien en double : aucune requête ; page supprimée : ignorée.
    assert site.paths() == [
        "/robots.txt", "/offres", "/offres/ds-stage", "/offres/ml-alternance", "/offres/disparue",
    ]


def test_recruiter_name_and_contact_are_never_kept():
    for offer in collector(careers_site()).collect(SearchQuery()).offers:
        dumped = offer.model_dump_json()
        assert "Jeanne" not in dumped and "06 00" not in dumped and "@" not in dumped


def test_jsonld_item_list_on_a_single_page():
    site = FakeSite({"/offres": page("liste-jsonld.html")})
    result = collector(site, offer_links=None).collect(SearchQuery())
    remote, bi = result.offers
    assert result.rejected == 1  # JobPosting sans intitulé
    assert (remote.company, remote.location, remote.contract_type) == (
        "Initech", "Télétravail", ContractType.PERMANENT)
    assert remote.url == "https://emplois.example.com/o/1"
    # Lien vers un autre site : on garde la page lue ; entreprise par défaut du site.
    assert bi.url == "https://carrieres.example.com/offres" and bi.company == "Globex"
    assert bi.contract_type is ContractType.FIXED_TERM


def test_rescan_gives_the_same_ids():
    first = [o.dedup_key for o in collector(careers_site()).collect(SearchQuery()).offers]
    second = [o.dedup_key for o in collector(careers_site()).collect(SearchQuery()).offers]
    assert first == second and len(set(first)) == 2


def test_block_on_start_page_stops_the_source_immediately():
    site = careers_site(**{"/offres": (403, HTML, "Accès refusé")})
    result = collector(site).collect(SearchQuery())
    assert isinstance(result.error, SourceBlocked) and result.offers == []
    assert site.paths() == ["/robots.txt", "/offres"]


def test_block_on_offer_page_keeps_earlier_offers_and_stops():
    site = careers_site(**{"/offres/ml-alternance": (403, HTML, "")})
    result = collector(site).collect(SearchQuery())
    assert isinstance(result.error, SourceBlocked)
    assert [o.external_id for o in result.offers] == ["GX-42"]
    assert "/offres/disparue" not in site.paths()


def test_page_budget_is_respected():
    site = careers_site()
    collector(site, max_pages=2).collect(SearchQuery())
    assert site.paths() == ["/robots.txt", "/offres", "/offres/ds-stage"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [({"start_urls": ["https://evil.test/"]}, "hors des domaines"),
     ({"offer_links": "a[["}, ""),
     ({"source": "Web Globex"}, "pattern")],
)
def test_invalid_site_config_is_refused(overrides, message):
    base = load_sites(PAGES / "sites.toml")[0].model_dump()
    with pytest.raises((ValidationError, ValueError), match=message):
        SiteConfig(**(base | overrides))


def test_duplicate_sources_are_refused(tmp_path):
    text = (PAGES / "sites.toml").read_text(encoding="utf-8")
    (tmp_path / "sites.toml").write_text(text + "\n" + text.split("\n", 1)[1], encoding="utf-8")
    with pytest.raises(ValueError, match="même identifiant"):
        load_sites(tmp_path / "sites.toml")


@pytest.mark.parametrize(
    ("texts", "expected"),
    [(("Data Scientist International",), ContractType.OTHER),
     (("Data Analyst", "INTERN"), ContractType.INTERNSHIP),
     (("Alternance Data Analyst",), ContractType.APPRENTICESHIP),
     (("ML Engineer", ["FULL_TIME"]), ContractType.OTHER),
     (("ML Engineer - CDD 12 mois",), ContractType.FIXED_TERM)],
)
def test_contract_type_from_words(texts, expected):
    assert contract_type(*texts) is expected
