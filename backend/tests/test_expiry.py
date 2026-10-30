"""Marquage des offres expirées en base (#14), sous RLS. Le site est faux : aucun appel réseau
(les sockets restent permises ici pour joindre PostgreSQL)."""

from pathlib import Path

import psycopg
import pytest
from fake_web import HTML, FakeSite, make_client

from app import db
from app.collectors.base import SourceBlocked
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


def expired_flags(db_url):
    with psycopg.connect(db_url) as conn:
        return conn.execute("SELECT u.email, external_id, expired FROM job_postings j "
                            "JOIN users u ON u.id = j.user_id ORDER BY 1, 2").fetchall()


@pytest.fixture
def two_users(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        users = add_user(conn, "alice@example.test"), add_user(conn, "bob@example.test")
    yield users
    db._engine(migrated_db).dispose()
    db._engine.cache_clear()


def test_refresh_marks_only_expired_offers_of_the_current_user(migrated_db, two_users):
    alice, bob = two_users
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        add_offer(conn, alice, "vivante", "/a")
        add_offer(conn, alice, "retiree", "/b")
        add_offer(conn, bob, "retiree", "/b")
    site = FakeSite({"/a": (200, HTML, (PAGES / "offre-jsonld.html").read_text(encoding="utf-8")),
                     "/b": (404, HTML, "")})
    assert refresh_expired(alice, collector(site)) == (["retiree"], None)
    with db.user_scope(alice) as conn:
        assert mark_expired(conn, "web_globex", ["retiree"]) == 0  # déjà marquée
    assert expired_flags(migrated_db) == [
        ("alice@example.test", "retiree", True), ("alice@example.test", "vivante", False),
        ("bob@example.test", "retiree", False)]


def test_marks_found_before_a_block_are_kept(migrated_db, two_users):
    alice, _ = two_users
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        add_offer(conn, alice, "1-retiree", "/b")
        add_offer(conn, alice, "2-bloquee", "/c")
    site = FakeSite({"/b": (410, HTML, ""), "/c": (403, HTML, "")})
    with pytest.raises(SourceBlocked):
        refresh_expired(alice, collector(site))
    assert expired_flags(migrated_db)[0] == ("alice@example.test", "1-retiree", True)


def test_cursor_rotates_through_offers(migrated_db, two_users):
    alice, _ = two_users
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        for name in ("a", "b", "c"):
            add_offer(conn, alice, name, "/" + name)
    site = FakeSite({"/a": (404, HTML, ""), "/b": (404, HTML, ""), "/c": (404, HTML, "")})
    web = collector(site)
    first, cursor = refresh_expired(alice, web, limit=2)
    second, end = refresh_expired(alice, web, limit=2, after=cursor)
    assert sorted(first + second) == ["a", "b", "c"] and end is None
