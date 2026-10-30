"""Client HTTP poli (#59) et protection SSRF (#40), sur un faux serveur : aucun appel réseau."""

import httpx
import pytest
from fake_web import HTML, PUBLIC_IP, FakeClock, FakeSite, no_network  # noqa: F401
from fake_web import make_client as client

from app.collectors.base import NetworkError, QuotaExceeded, SourceBlocked
from app.collectors.http_client import (
    MAX_BYTES,
    USER_AGENT,
    PageNotFound,
    PoliteClient,
    RobotsDisallowed,
    UnsafeUrl,
    is_public_address,
)


def test_reads_page_with_identifiable_user_agent_after_robots():
    site = FakeSite({"/offres": (200, HTML, "<h1>Offres</h1>")})
    page = client(site).get("https://jobs.example.com/offres?utm_source=x")
    assert page.text == "<h1>Offres</h1>" and page.content_type == "text/html"
    assert site.paths() == ["/robots.txt", "/offres"]
    assert {r.headers["user-agent"] for r in site.requests} == {USER_AGENT}
    assert "utm_source" not in str(site.requests[1].url)


def test_robots_disallow_is_respected():
    site = FakeSite({"/prive/1": (200, HTML, "secret")})
    with pytest.raises(RobotsDisallowed):
        client(site).get("https://example.com/prive/1")
    assert site.paths() == ["/robots.txt"]


@pytest.mark.parametrize("status", [404, 410])
def test_missing_robots_means_no_rule(status):
    site = FakeSite({"/a": (200, HTML, "ok")}, robots=(status, {}, ""))
    assert client(site).get("https://example.com/a").text == "ok"


def test_robots_server_error_forbids_everything_for_now():
    site = FakeSite({"/a": (200, HTML, "ok")}, robots=(503, {}, ""))
    with pytest.raises(NetworkError):
        client(site).get("https://example.com/a")
    assert site.paths() == ["/robots.txt"]


def test_one_request_every_three_seconds_per_domain_and_crawl_delay():
    clock = FakeClock()
    site = FakeSite({"/a": (200, HTML, "a"), "/b": (200, HTML, "b")})
    web = client(site, clock=clock)
    web.get("https://example.com/a")
    web.get("https://www.example.com/b")  # même domaine de la liste blanche
    assert clock.slept == [3.0, 3.0, 3.0]  # robots.txt de www, puis /b
    slow = FakeSite({"/a": (200, HTML, "a")}, robots=(200, {}, "User-agent: *\nCrawl-delay: 10\n"))
    clock2 = FakeClock()
    client(slow, clock=clock2).get("https://example.com/a")
    assert clock2.slept == [10.0]


def test_cache_avoids_rereading_and_revalidates_with_etag():
    calls = []

    def page(request):
        calls.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"v1"':
            return 304, {}, ""
        return 200, {**HTML, "etag": '"v1"'}, "contenu"

    cache: dict = {}
    site = FakeSite({"/a": (200, {}, page)})
    first = client(site, cache=cache)
    assert first.get("https://example.com/a").text == "contenu"
    assert first.get("https://example.com/a").text == "contenu"  # même collecte : pas relue
    assert client(site, cache=cache).get("https://example.com/a").text == "contenu"
    assert calls == [None, '"v1"']


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, SourceBlocked), (403, SourceBlocked), (407, SourceBlocked), (429, QuotaExceeded),
     (404, PageNotFound), (410, PageNotFound), (500, NetworkError)],
)
def test_status_errors_are_typed(status, error):
    site = FakeSite({"/a": (status, {"retry-after": "120"}, "")})
    with pytest.raises(error) as info:
        client(site).get("https://example.com/a")
    assert "HTTP" in info.value.message and "<" not in info.value.message
    if error is QuotaExceeded:
        assert info.value.retry_after == 120


def test_robots_forbidden_blocks_the_source():
    site = FakeSite({}, robots=(403, {}, ""))
    with pytest.raises(SourceBlocked):
        client(site).get("https://example.com/a")


@pytest.mark.parametrize(
    "url",
    ["https://evil.test/a", "https://example.com.evil.test/a", "https://127.0.0.1/",
     "https://example.com:8443/a", "ftp://example.com/a", "file:///etc/passwd",
     "https://user:pw@notexample.com/"],
)
def test_url_outside_allowlist_is_refused_without_request(url):
    site = FakeSite({})
    with pytest.raises(UnsafeUrl):
        client(site).get(url)
    assert site.requests == []


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "fd00::1",
                "::ffff:127.0.0.1", "100.64.0.1", "0.0.0.0"],
)
def test_allowed_domain_resolving_to_private_address_is_refused(address):
    site = FakeSite({"/a": (200, HTML, "ok")})
    with pytest.raises(UnsafeUrl):
        client(site, resolver=lambda _h: [PUBLIC_IP, address]).get("https://example.com/a")
    assert site.requests == []
    assert not is_public_address(address)


def test_redirect_to_private_address_or_other_domain_is_refused():
    private = {"internal.example.com": ["169.254.169.254"]}
    site = FakeSite({
        "/a": (302, {"location": "https://internal.example.com/latest/meta-data"}, ""),
        "/b": (301, {"location": "https://evil.test/"}, ""),
        "/c": (302, {"location": "/d"}, ""), "/d": (200, HTML, "arrivé"),
    })
    web = client(site, resolver=lambda host: private.get(host, [PUBLIC_IP]))
    for path in ("/a", "/b"):
        with pytest.raises(UnsafeUrl):
            web.get(f"https://example.com{path}")
    page = web.get("https://example.com/c")
    assert page.text == "arrivé" and page.url == "https://example.com/d"
    assert "/latest/meta-data" not in site.paths()


def test_oversized_page_is_refused():
    site = FakeSite({"/a": (200, HTML, "x" * (MAX_BYTES + 1))})
    with pytest.raises(Exception, match="volumineuse"):
        client(site).get("https://example.com/a")


def test_transport_failure_is_a_network_error():
    def boom(_request):
        raise httpx.ConnectTimeout("délai")

    with pytest.raises(NetworkError):
        client(boom).get("https://example.com/a")


def test_allowlist_cannot_contain_ip_addresses():
    with pytest.raises(ValueError):
        PoliteClient("web_test", ["10.0.0.1"])
