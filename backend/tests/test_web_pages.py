"""Source « web » par utilisateur : validation des URL (SSRF), API, collecte sous RLS, blocage. Aucun réseau."""
from pathlib import Path

import pytest
from fake_web import HTML, PUBLIC_IP, FakeSite, make_client
from test_applications import alice, application, assert_conforms, bob, contract  # noqa: F401
from test_worker import SETTINGS, Notes, env, sql  # noqa: F401

from app.db import user_scope
from app.web_pages import check_page_url, web_collector
from app.worker import Worker

PAGES = Path(__file__).parent / "fixtures" / "web"
OK = "https://carrieres.example.com/offres/ds-stage"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("app.web_pages.system_resolver", lambda _host: [PUBLIC_IP])


@pytest.mark.parametrize("url", [
    "http://localhost/jobs", "https://127.0.0.1/jobs", "http://[::1]/jobs", "https://10.0.0.5/x",
    "http://169.254.169.254/latest/meta-data", "https://2130706433/x", "https://0x7f.1/x", "http://intranet/jobs",
    "https://serveur.local/jobs", "https://db.internal/jobs", "https://app.localhost/x", "https://exemple/jobs",
    "ftp://example.com/jobs", "file:///etc/passwd", "javascript:alert(1)",
    "https://example.com:8443/jobs", "", "pas une url",
])
def test_refuses_local_private_and_invalid_urls(url):
    with pytest.raises(ValueError):
        check_page_url(url)


@pytest.mark.parametrize("url", ["https://www.linkedin.com/jobs/search", "https://fr.indeed.com/emplois",
                                 "https://apec.fr/x"])
def test_refuses_closed_sites_and_points_to_email_alerts(url):
    with pytest.raises(ValueError, match="alerte e-mail"):
        check_page_url(url)


def test_refuses_a_name_that_resolves_to_a_private_address():
    with pytest.raises(ValueError, match="non publique"):
        check_page_url("https://piege.example.com/jobs", resolver=lambda _h: ["10.0.0.9"])


def test_accepts_a_normal_page_and_cleans_tracking():
    assert check_page_url(f"{OK}?utm_source=x#haut") == OK
    assert check_page_url("http://carrieres.example.com/offres") == "http://carrieres.example.com/offres"
    assert check_page_url("https://user:pw@example.com/jobs") == "https://example.com/jobs"  # identifiants retirés


def put(api, urls):
    return api.put("/sources/web/pages", {"urls": urls})


def test_pages_are_empty_then_round_trip_and_replace(alice, contract):  # noqa: F811
    assert alice.get("/sources/web/pages").json() == {"urls": [], "max": 10}
    saved = put(alice, [OK, f"{OK}?utm_x=1", "https://jobs.example.org/careers"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["urls"] == [OK, "https://jobs.example.org/careers"]  # doublon fusionné, ordre gardé
    assert_conforms(contract, "WebPages", saved.json())
    assert put(alice, ["https://jobs.example.org/careers"]).json()["urls"] == ["https://jobs.example.org/careers"]


def test_rejects_bad_urls_with_the_line_number_and_too_many(alice):  # noqa: F811
    refused = put(alice, [OK, "https://127.0.0.1/x"])
    assert refused.status_code == 422 and "Page 2" in refused.json()["message"]
    assert alice.get("/sources/web/pages").json()["urls"] == []  # rien n'a été enregistré
    many = [f"https://site{i}.example.com/jobs" for i in range(11)]
    assert put(alice, many).status_code == 422
    assert put(alice, many[:10]).status_code == 200
    assert put(alice, ["https://gouv.fr/emplois"]).status_code == 422  # domaine trop général
    assert alice.put("/sources/web/pages", {"urls": [OK], "x": 1}).status_code == 422


def test_each_user_has_their_own_pages(alice, bob):  # noqa: F811
    put(alice, [OK])
    assert bob.get("/sources/web/pages").json()["urls"] == []
    put(bob, ["https://jobs.example.org/careers"])
    assert alice.get("/sources/web/pages").json()["urls"] == [OK]


def test_web_source_needs_a_page_before_it_can_be_enabled(alice):  # noqa: F811
    web = {s["source"]: s for s in alice.get("/sources").json()}["web"]
    assert not web["configured"] and web["key_env"] == []
    refused = alice.put("/sources/web", {"enabled": True, "interval_minutes": None})
    assert refused.status_code == 409 and "page" in refused.json()["message"]
    put(alice, [OK])
    assert alice.put("/sources/web", {"enabled": True, "interval_minutes": 360}).json()["enabled"]
    put(alice, [])  # sans page, la source s'éteint
    assert not {s["source"]: s for s in alice.get("/sources").json()}["web"]["enabled"]


# --- Collecte par le worker -------------------------------------------------------------------


def add_pages(url, user, *urls):
    for position, page in enumerate(urls):
        sql(url, "INSERT INTO web_pages (user_id, position, url) VALUES (%s, %s, %s)", user, position, page)


def queue_web(url, user):
    sql(url, "INSERT INTO source_settings (user_id, source, enabled) VALUES (%s, 'web', true) "
             "ON CONFLICT DO NOTHING", user)
    sql(url, "INSERT INTO jobs (user_id, kind, source) VALUES (%s, 'collect', 'web')", user)


def web_worker(site, resolver=None, notifier=None):
    def factory(conn):
        return web_collector(conn, lambda cfg: make_client(
            site, resolver=resolver, source="web", domains=cfg.allowed_domains))
    return Worker({}, SETTINGS, notifier or Notes(), "w1", user_registry={"web": factory})


def offer_page():
    return (200, HTML, (PAGES / "offre-jsonld.html").read_text(encoding="utf-8"))


def test_worker_reads_only_the_pages_of_the_job_owner(env):  # noqa: F811
    url, (alice_id, bob_id) = env
    add_pages(url, alice_id, OK)
    site = FakeSite({"/offres/ds-stage": offer_page()})
    queue_web(url, alice_id)
    queue_web(url, bob_id)  # Bob n'a saisi aucune page : aucune requête
    worker = web_worker(site)
    assert worker.run_one() and worker.run_one() and not worker.run_one()
    assert site.paths() == ["/robots.txt", "/offres/ds-stage"]
    rows = dict(sql(url, "SELECT user_id::text, count(*) FROM job_postings WHERE source = 'web' GROUP BY 1"))
    assert rows == {alice_id: 1}
    assert sql(url, "SELECT state FROM jobs WHERE user_id = %s", bob_id) == [("done",)]


def test_worker_stops_at_the_first_protection_and_blocks_the_source(env):  # noqa: F811
    url, (alice_id, _) = env
    add_pages(url, alice_id, OK, "https://carrieres.example.com/offres/autre")
    site = FakeSite({"/offres/ds-stage": (403, {}, "Forbidden"), "/offres/autre": offer_page()})
    queue_web(url, alice_id)
    notes = Notes()
    assert web_worker(site, notifier=notes).run_one()
    assert "/offres/autre" not in site.paths()  # arrêt à la première page bloquée
    assert sql(url, "SELECT enabled, blocked_at IS NOT NULL FROM source_settings "
                    "WHERE user_id = %s AND source = 'web'", alice_id) == [(False, True)]
    assert notes.sent and notes.sent[0][0] == "web"
    assert sql(url, "SELECT state FROM jobs WHERE user_id = %s", alice_id) == [("dead",)]


def test_worker_refuses_a_name_that_now_points_to_a_private_address(env):  # noqa: F811
    url, (alice_id, _) = env
    add_pages(url, alice_id, OK)
    site = FakeSite({"/offres/ds-stage": offer_page()})
    queue_web(url, alice_id)
    assert web_worker(site, resolver=lambda _h: ["192.168.1.10"]).run_one()
    assert site.paths() == []  # aucune requête vers l'adresse privée (DNS changé après l'enregistrement)
    assert sql(url, "SELECT count(*) FROM job_postings WHERE source = 'web'")[0][0] == 0


def test_collector_is_none_without_pages(env):  # noqa: F811
    _, (alice_id, _) = env
    with user_scope(alice_id) as conn:
        assert web_collector(conn) is None
