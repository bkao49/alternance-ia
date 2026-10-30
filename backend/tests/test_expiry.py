"""Marquage des offres expirées en base (#14), sous RLS. Le site est faux : aucun appel réseau
(les sockets restent permises ici pour joindre PostgreSQL)."""

from pathlib import Path

import psycopg
from fake_web import HTML, FakeSite, make_client

from app import db
from app.collectors.expiry import mark_expired, refresh_expired
from app.collectors.web import WebCollector, load_sites

PAGES = Path(__file__).parent / "fixtures" / "web"


def collector(site: FakeSite) -> WebCollector:
    config = load_sites(PAGES / "sites.toml")[0]
    return WebCollector(config, make_client(site, source=config.source))


def add_user(conn, email):
    return str(conn.execute("INSERT INTO users (email, password_hash) VALUES (%s, 'x') RETURNING id",
                            (email,)).fetchone()[0])


def add_offer(conn, user_id, external_id, path):
    conn.execute(
        "INSERT INTO job_postings (user_id, source, external_id, url, title, company, "
        "description_text, content_hash) VALUES (%s, 'web_globex', %s, %s, 'T', 'Globex', '', 'h')",
        (user_id, external_id, f"https://carrieres.example.com{path}"))


def test_refresh_marks_only_expired_offers_of_the_current_user(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        alice, bob = add_user(conn, "alice@example.test"), add_user(conn, "bob@example.test")
        add_offer(conn, alice, "vivante", "/a")
        add_offer(conn, alice, "retiree", "/b")
        add_offer(conn, bob, "retiree", "/b")
    site = FakeSite({"/a": (200, HTML, (PAGES / "offre-jsonld.html").read_text(encoding="utf-8")), "/b": (404, HTML, "")})
    try:
        with db.user_scope(alice) as conn:
            assert refresh_expired(conn, collector(site)) == ["retiree"]
            assert mark_expired(conn, "web_globex", ["retiree"]) == 0  # déjà marquée
        with psycopg.connect(migrated_db) as conn:
            rows = conn.execute("SELECT user_id::text, external_id, expired FROM job_postings "
                                "ORDER BY user_id = %s DESC, external_id", (alice,)).fetchall()
        assert rows == [(alice, "retiree", True), (alice, "vivante", False), (bob, "retiree", False)]
    finally:
        db._engine(migrated_db).dispose()
        db._engine.cache_clear()
