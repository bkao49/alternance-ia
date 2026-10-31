from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_applications import (  # noqa: F401  (fixtures et helpers partagés)
    alice,
    application,
    assert_conforms,
    bob,
    contract,
)

from app import profile
from app.db import user_scope

# Faits fictifs, uniquement pour les tests.
FACT = {"kind": "experience", "text": "Stage de data analyst de 6 mois chez Acme (fictif)",
        "start_date": "2026-01-05", "end_date": "2026-06-30", "technologies": ["Python", "SQL"],
        "source": "saisie manuelle"}
SKILL = {"kind": "skill", "text": "Pandas", "start_date": None, "end_date": None, "technologies": [],
         "source": None}
UNKNOWN = "/profile/facts/00000000-0000-0000-0000-000000000000"


def test_create_list_update_delete(alice, contract):  # noqa: F811
    created = alice.post("/profile/facts", FACT)
    assert created.status_code == 201, created.text
    fact = created.json()
    assert_conforms(contract, "ProfileFact", fact)
    assert {k: fact[k] for k in FACT} == FACT

    alice.post("/profile/facts", SKILL)
    listed = alice.get("/profile/facts").json()
    assert [f["kind"] for f in listed] == ["experience", "skill"]  # date décroissante, sans date à la fin
    assert [f["text"] for f in alice.get("/profile/facts", params={"kind": "skill"}).json()] == ["Pandas"]

    changed = alice.put(f"/profile/facts/{fact['id']}", {**FACT, "end_date": None, "technologies": ["R"]})
    assert changed.status_code == 200 and changed.json()["technologies"] == ["R"]
    assert changed.json()["created_at"] == fact["created_at"]

    assert alice.delete(f"/profile/facts/{fact['id']}").status_code == 204
    assert [f["text"] for f in alice.get("/profile/facts").json()] == ["Pandas"]
    assert alice.delete(f"/profile/facts/{fact['id']}").status_code == 404


INVALID = [
    {"kind": "hobby"}, {"text": "  "}, {"text": "x" * 1001}, {"text": "a\u0000"},
    {"start_date": "2026-06-01", "end_date": "2026-01-01"}, {"technologies": ["SQL", "SQL"]},
    {"technologies": [f"t{i}" for i in range(31)]}, {"technologies": ["x" * 61]}, {"source": "x" * 121},
    {"source": " "}, {"extra": 1}, {"technologies": None},
]


@pytest.mark.parametrize("change", INVALID)
def test_invalid_facts_are_refused(alice, change):  # noqa: F811
    assert alice.post("/profile/facts", {**FACT, **change}).status_code == 422, change
    assert alice.get("/profile/facts").json() == []


@pytest.mark.parametrize("missing", sorted(FACT))
def test_every_field_is_required(alice, missing):  # noqa: F811
    assert alice.post("/profile/facts", {k: v for k, v in FACT.items() if k != missing}).status_code == 422


def test_unknown_or_malformed_fact(alice):  # noqa: F811
    assert alice.put(UNKNOWN, FACT).status_code == 404
    assert alice.delete(UNKNOWN).status_code == 404
    assert alice.delete("/profile/facts/pas-un-uuid").status_code == 422


def test_facts_require_a_session_and_csrf(alice, application):  # noqa: F811
    anonymous = TestClient(application, base_url="https://testserver")
    assert anonymous.get("/profile/facts").status_code == 401
    assert anonymous.post("/profile/facts", json=FACT).status_code == 401
    fact_id = alice.post("/profile/facts", FACT).json()["id"]
    for method, body in (("POST", FACT), ("PUT", FACT), ("DELETE", None)):
        path = "/profile/facts" if method == "POST" else f"/profile/facts/{fact_id}"
        assert alice.client.request(method, path, json=body).status_code == 403
        assert alice.client.request(method, path, json=body, headers={"X-CSRF-Token": "faux"}).status_code == 403
    assert len(alice.get("/profile/facts").json()) == 1


def test_users_cannot_see_or_touch_each_others_facts(alice, bob):  # noqa: F811
    fact_id = alice.post("/profile/facts", FACT).json()["id"]
    assert bob.get("/profile/facts").json() == []
    assert bob.put(f"/profile/facts/{fact_id}", SKILL).status_code == 404
    assert bob.delete(f"/profile/facts/{fact_id}").status_code == 404
    assert alice.get("/profile/facts").json()[0]["text"] == FACT["text"]


def test_fact_limit(alice, monkeypatch):  # noqa: F811
    monkeypatch.setattr(profile, "MAX_FACTS", 2)
    assert [alice.post("/profile/facts", FACT).status_code for _ in range(3)] == [201, 201, 409]


def test_database_refuses_an_unknown_kind_even_without_the_api(alice, migrated_db):  # noqa: F811
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO profile_facts (user_id, kind, text) VALUES (%s, 'hobby', 't')", (alice.user_id,))


def test_invalid_kind_filter_and_extra_id_are_refused(alice):  # noqa: F811
    assert alice.get("/profile/facts", params={"kind": "hobby"}).status_code == 422
    fact_id = alice.post("/profile/facts", FACT).json()["id"]
    assert alice.put(f"/profile/facts/{fact_id}", {**FACT, "id": fact_id}).status_code == 422


def test_limit_is_per_user(alice, bob, monkeypatch):  # noqa: F811
    monkeypatch.setattr(profile, "MAX_FACTS", 1)
    assert alice.post("/profile/facts", FACT).status_code == 201
    assert alice.post("/profile/facts", FACT).status_code == 409
    assert bob.post("/profile/facts", FACT).status_code == 201


def test_two_simultaneous_additions_respect_the_limit(alice, application, monkeypatch):  # noqa: F811
    monkeypatch.setattr(profile, "MAX_FACTS", 1)
    clients = []
    for _ in range(2):
        other = TestClient(application, base_url="https://testserver")
        other.cookies.update(alice.client.cookies)
        clients.append(other)

    def add(client):
        return client.post("/profile/facts", json=FACT,
                           headers={"X-CSRF-Token": alice.client.cookies["csrf_token"]}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(add, clients)) == [201, 409]
    assert len(alice.get("/profile/facts").json()) == 1


def test_migration_repairs_existing_rows(migrated_db, alembic_config):
    command.downgrade(alembic_config, "0006")
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        uid = conn.execute("INSERT INTO users (email, password_hash) VALUES ('c@example.test', 'x') "
                           "RETURNING id").fetchone()[0]
        conn.execute("INSERT INTO profile_facts (user_id, kind, text, start_date, end_date, technologies) "
                     "VALUES (%s, 'hobby', %s, '2026-06-01', '2026-01-01', %s)",
                     (uid, "x" * 1500, [f"t{i}" for i in range(40)]))
    command.upgrade(alembic_config, "head")
    with psycopg.connect(migrated_db) as conn:
        kind, length, end, count = conn.execute(
            "SELECT kind, length(text), end_date, cardinality(technologies) FROM profile_facts").fetchone()
    assert (kind, length, end, count) == ("other", 1000, None, 30)


@pytest.mark.parametrize("values", [
    "'skill', 't', '2026-06-01', '2026-01-01', '{}', NULL",
    "'skill', '', NULL, NULL, '{}', NULL",
    "'skill', 't', NULL, NULL, '{}', repeat('s', 121)",
])
def test_database_checks_hold_without_the_api(alice, migrated_db, values):  # noqa: F811
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO profile_facts (user_id, kind, text, start_date, end_date, technologies, source) "
                     f"VALUES (%s, {values})", (alice.user_id,))


def _propose(user_id, text_="Projet fictif : tableau de bord Python"):
    """Insère un fait « à valider », comme le fera l'extraction d'un CV."""
    with user_scope(user_id) as conn:
        return str(conn.execute(
            text("INSERT INTO profile_facts (user_id, kind, text, technologies, status) "
                 "VALUES (:u, 'project', :t, '{Python}', 'proposed') RETURNING id"),
            {"u": user_id, "t": text_}).scalar_one())


def test_manual_facts_are_validated_and_proposed_ones_can_be_filtered(alice):  # noqa: F811
    assert alice.post("/profile/facts", FACT).json()["status"] == "validated"
    proposed = _propose(alice.user_id)
    assert [f["id"] for f in alice.get("/profile/facts", params={"status": "proposed"}).json()] == [proposed]
    assert len(alice.get("/profile/facts").json()) == 2
    assert alice.get("/profile/facts", params={"status": "bof"}).status_code == 422


def test_validate_and_reject(alice, bob, contract):  # noqa: F811
    first, second = _propose(alice.user_id), _propose(alice.user_id, "Autre projet")
    assert bob.post(f"/profile/facts/{first}/validate").status_code == 404  # fait d'un autre utilisateur
    assert bob.post(f"/profile/facts/{first}/reject").status_code == 404
    validated = alice.post(f"/profile/facts/{first}/validate")
    assert validated.status_code == 200 and validated.json()["status"] == "validated"
    assert_conforms(contract, "ProfileFact", validated.json())
    assert alice.post(f"/profile/facts/{first}/reject").status_code == 409  # déjà validé : on le supprime
    assert alice.post(f"/profile/facts/{second}/reject").status_code == 204
    assert alice.post(f"/profile/facts/{second}/reject").status_code == 404
    assert [f["id"] for f in alice.get("/profile/facts").json()] == [first]
