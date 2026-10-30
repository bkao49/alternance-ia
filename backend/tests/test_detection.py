"""Détection de blocage et d'annonce expirée (#14), sur des pages fictives : aucun appel réseau."""

import datetime as dt
import time
from pathlib import Path

import pytest
from fake_web import HTML, FakeSite, make_client, no_network  # noqa: F401

from app.collectors.base import CollectResult, SearchQuery, SourceBlocked
from app.collectors.detection import (
    block_cause,
    handle_blocks,
    has_captcha,
    page_says_expired,
    posting_expired,
    visible_text,
)
from app.collectors.web import SiteConfig, WebCollector, load_sites

PAGES = Path(__file__).parent / "fixtures" / "web"
NOW = dt.datetime(2026, 10, 30, 12, tzinfo=dt.UTC)


def html(name: str) -> str:
    return (PAGES / name).read_text(encoding="utf-8")


def collector(site: FakeSite, **overrides) -> WebCollector:
    config = SiteConfig(**(load_sites(PAGES / "sites.toml")[0].model_dump() | overrides))
    return WebCollector(config, make_client(site, source=config.source))


def careers(**routes) -> FakeSite:
    return FakeSite({"/offres": (200, HTML, html("liste.html")),
                     "/offres/ds-stage": (200, HTML, html("offre-jsonld.html")),
                     "/offres/ml-alternance": (200, HTML, html("offre-css.html")), **routes})


# --- Blocage --------------------------------------------------------------------------------


def test_challenge_page_is_a_block_and_captcha_is_left_to_the_collector():
    url = "https://example.com/offres"
    assert block_cause(html("defi.html"), url, url) == "défi anti-bot"
    assert block_cause(html("captcha.html"), url, url) is None
    assert has_captcha(html("captcha.html")) and not has_captcha(html("offre-css.html"))


@pytest.mark.parametrize("name", ["offre-jsonld.html", "offre-css.html"])
def test_captcha_next_to_a_readable_offer_is_not_a_block(name):
    widget = '<div class="g-recaptcha"></div><script src="/recaptcha/api.js"></script></body>'
    site = careers(**{"/offres/ds-stage": (200, HTML, html(name).replace("</body>", widget))})
    result = collector(site).collect(SearchQuery())
    assert result.error is None and len(result.offers) == 2


def test_hostile_page_is_scanned_in_linear_time():
    hostile = "<script" * 150_000 + "<" * 600_000 + "captcha " * 100_000
    started = time.monotonic()
    assert block_cause(hostile, "https://example.com/a", "https://example.com/a") is None
    page_says_expired(hostile)
    visible_text("<" * 2_000_000)
    assert time.monotonic() - started < 2


def test_redirect_to_login_is_a_block_but_a_login_link_is_not():
    assert block_cause("<p>Connexion</p>", "https://example.com/connexion?next=/o",
                       "https://example.com/o") == "page de connexion"
    assert block_cause("<p>Connexion</p>", "https://example.com/connexion",
                       "https://example.com/connexion") is None


@pytest.mark.parametrize("name", ["defi.html", "captcha.html"])
def test_block_served_with_200_stops_the_source_without_retry(name):
    site = FakeSite({"/offres": (200, HTML, html(name)), "/offres/ds-stage": (200, HTML, "x")})
    result = collector(site).collect(SearchQuery())
    assert isinstance(result.error, SourceBlocked) and not result.error.retryable
    assert site.paths() == ["/robots.txt", "/offres"]
    assert "moment" not in result.error.message and "robot" not in result.error.message


def test_login_redirect_stops_the_source():
    site = FakeSite({"/offres": (302, {"location": "/connexion"}, ""),
                     "/connexion": (200, HTML, "<form><input type=password></form>")})
    result = collector(site).collect(SearchQuery())
    assert isinstance(result.error, SourceBlocked) and result.error.message == "page de connexion"


class Recorder:
    def __init__(self):
        self.calls = []

    def notify(self, source, cause):
        self.calls.append((source, cause))


def test_blocked_source_is_disabled_and_notified_once():
    blocked = CollectResult(source="web_a", error=SourceBlocked("web_a", "HTTP 403"))
    results = [blocked, CollectResult(source="web_b"), blocked]
    disabled, notifier = set(), Recorder()
    assert handle_blocks(results, disabled, notifier) == ["web_a"]
    assert disabled == {"web_a"} and notifier.calls == [("web_a", "HTTP 403")]
    assert handle_blocks([blocked], disabled, notifier) == []


# --- Annonce expirée ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valid_through", "expired"),
    [("2026-10-29", True), ("2026-10-30", False), ("20261030", False), ("2026-10-30T11:00:00+00:00", True),
     ("2026-11-15T00:00:00+01:00", False), ("demain", False), (None, False)],
)
def test_valid_through(valid_through, expired):
    assert posting_expired({"validThrough": valid_through}, NOW) is expired


def test_expired_text_is_detected_in_visible_text_only():
    assert page_says_expired(html("expiree.html"))
    assert page_says_expired("<p>This position has been filled.</p>")
    assert not page_says_expired(html("offre-css.html"))
    assert not page_says_expired("<script>'offre n’est plus disponible'</script><p>Ouverte</p>")
    assert not page_says_expired("<p>Applications accepted until the position has been filled.</p>")


def test_expired_offers_are_reported_not_collected():
    old = html("offre-jsonld.html").replace("2099-01-31", "2020-01-31")
    site = FakeSite({"/offres": (200, HTML, html("liste.html")),
                     "/offres/ds-stage": (200, HTML, old),
                     "/offres/ml-alternance": (200, HTML, html("expiree.html"))})
    result = collector(site).collect(SearchQuery())
    assert result.offers == [] and result.error is None
    assert result.expired[0] == "GX-42" and len(result.expired) == 2


def test_check_expired():
    banner = html("offre-jsonld.html").replace(
        "<body>", "<body><p>Cette offre a été pourvue.</p>")
    site = FakeSite({"/a": (200, HTML, html("offre-jsonld.html")), "/b": (410, HTML, ""),
                     "/e": (200, HTML, banner),
                     "/c": (200, HTML, html("expiree.html")), "/prive/d": (200, HTML, "")})
    web = collector(site)
    assert [web.check_expired(f"https://carrieres.example.com{p}") for p in
            ("/a", "/b", "/c", "/prive/d", "/e")] == [False, True, True, None, True]
    assert web.check_expired("https://autre.test/x") is None
