import psycopg
import pytest
from test_applications import alice, application, assert_conforms, bob, contract  # noqa: F401

KEYS = {"LBA_API_TOKEN": "fictif", "ADZUNA_APP_ID": "fictif", "ADZUNA_APP_KEY": "fictif"}
OFF = {"enabled": False, "interval_minutes": None}


@pytest.fixture(autouse=True)
def server_keys(monkeypatch):
    """Clés fictives pour lba et adzuna ; France Travail reste sans clé."""
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)
    for name in ("FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)


def by_key(api):
    return {s["source"]: s for s in api.get("/sources").json()}


def block(db_url, user_id, source, cause="blocage détecté (403)"):
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO source_settings (user_id, source, enabled, blocked_at, blocked_cause) "
            "VALUES (%s, %s, false, now(), %s)", (user_id, source, cause))


def test_requires_a_session(application):  # noqa: F811
    from fastapi.testclient import TestClient

    anonymous = TestClient(application, base_url="https://testserver")
    assert anonymous.get("/sources").status_code == 401
    assert anonymous.put("/sources/lba", json=OFF).status_code == 401


def test_catalog_lists_every_source_off_by_default(alice, contract):  # noqa: F811
    sources = alice.get("/sources").json()
    for source in sources:
        assert_conforms(contract, "Source", source)
    found = by_key(alice)
    assert set(found) == {"france_travail", "lba", "adzuna", "web", "email"}
    assert found["lba"]["configured"] and not found["france_travail"]["configured"]
    assert found["france_travail"]["key_env"] == ["FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET"]
    assert not any(s["enabled"] or s["blocked"] for s in sources)
    assert found["lba"]["default_interval_minutes"] == 120 and found["lba"]["interval_minutes"] is None


def test_never_returns_a_key_value(alice):  # noqa: F811
    assert "fictif" not in alice.client.get("/sources").text


def test_enable_set_interval_and_disable(alice, contract):  # noqa: F811
    saved = alice.put("/sources/lba", {"enabled": True, "interval_minutes": 180})
    assert saved.status_code == 200, saved.text
    assert_conforms(contract, "Source", saved.json())
    assert saved.json()["enabled"] and saved.json()["interval_minutes"] == 180
    assert by_key(alice)["lba"]["enabled"]
    off = alice.put("/sources/lba", OFF).json()
    assert not off["enabled"] and off["interval_minutes"] is None


@pytest.mark.parametrize("interval", [59, 0, -5, 10081, "120", 90.5])
def test_interval_must_be_an_hour_or_more(alice, interval):  # noqa: F811
    assert alice.put("/sources/lba", {"enabled": True, "interval_minutes": interval}).status_code == 422


def test_unknown_source_and_extra_fields(alice):  # noqa: F811
    assert alice.put("/sources/inconnue", OFF).status_code == 404
    assert alice.put("/sources/lba", {**OFF, "user_id": "x"}).status_code == 422


def test_needs_a_server_key_to_enable(alice):  # noqa: F811
    refused = alice.put("/sources/france_travail", {"enabled": True, "interval_minutes": None})
    assert refused.status_code == 409 and refused.json()["code"] == "source_not_configured"
    assert alice.put("/sources/france_travail", OFF).status_code == 200  # désactiver reste permis


def test_blocked_source_needs_an_explicit_confirmation(alice, migrated_db, contract):  # noqa: F811
    block(migrated_db, alice.user_id, "adzuna")
    listed = by_key(alice)["adzuna"]
    assert listed["blocked"] and not listed["enabled"] and listed["blocked_cause"] == "blocage détecté (403)"
    refused = alice.put("/sources/adzuna", {"enabled": True, "interval_minutes": None})
    assert refused.status_code == 409 and refused.json()["code"] == "source_blocked"
    assert "blocage détecté (403)" in refused.json()["message"]
    assert by_key(alice)["adzuna"]["blocked"]  # rien n'a bougé
    # Désactiver une source bloquée ne la débloque pas.
    assert alice.put("/sources/adzuna", {"enabled": False, "interval_minutes": None, "confirm_unblock": True}
                     ).json()["blocked"]
    accepted = alice.put("/sources/adzuna", {"enabled": True, "interval_minutes": 240, "confirm_unblock": True})
    assert accepted.status_code == 200 and accepted.json()["enabled"] and not accepted.json()["blocked"]
    assert_conforms(contract, "Source", accepted.json())


def test_each_user_has_their_own_settings(alice, bob, migrated_db):  # noqa: F811
    alice.put("/sources/lba", {"enabled": True, "interval_minutes": 90})
    block(migrated_db, alice.user_id, "adzuna")
    assert not by_key(bob)["lba"]["enabled"] and not by_key(bob)["adzuna"]["blocked"]
    bob.put("/sources/lba", OFF)
    assert by_key(alice)["lba"]["enabled"]


def test_enabled_source_is_scheduled_by_the_worker(alice, migrated_db):  # noqa: F811
    from app import jobs

    alice.put("/sources/lba", {"enabled": True, "interval_minutes": 60})
    assert jobs.schedule_due(120) == 1
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute("SELECT source, state FROM jobs").fetchone()
    assert row == ("lba", "queued")
