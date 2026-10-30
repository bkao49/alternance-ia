import pytest
from fastapi.testclient import TestClient
from test_applications import (  # noqa: F401  (fixtures et helpers partagés)
    alice,
    application,
    assert_conforms,
    bob,
    contract,
)

# Critères fictifs, uniquement pour les tests.
FULL = {
    "keywords": ["data analyst", "machine learning"],
    "locations": [{"label": "Lyon", "radius_km": 30}, {"label": "Grenoble", "radius_km": 0}],
    "remote_accepted": True,
    "contract_types": ["apprenticeship", "internship"],
    "start_date": "2027-09-01",
    "duration_months": 24,
    "alternance_rhythm": "3 semaines entreprise, 1 semaine école",
    "education_level": "bac_plus_5",
    "min_salary_eur": 18000,
    "excluded_keywords": ["commercial"],
}


def test_never_saved_preferences_are_empty(alice, contract):  # noqa: F811
    response = alice.get("/preferences")
    assert response.status_code == 200
    data = response.json()
    assert_conforms(contract, "SearchPreferences", data)
    assert data["updated_at"] is None
    assert data["keywords"] == [] and data["contract_types"] == [] and data["min_salary_eur"] is None


def test_put_then_get_round_trip(alice, contract):  # noqa: F811
    saved = alice.put("/preferences", FULL)
    assert saved.status_code == 200, saved.text
    assert_conforms(contract, "SearchPreferences", saved.json())
    data = alice.get("/preferences").json()
    assert data["updated_at"] is not None
    assert {k: data[k] for k in FULL} == FULL


def test_put_replaces_everything(alice):  # noqa: F811
    alice.put("/preferences", FULL)
    empty = {**FULL, "keywords": [], "locations": [], "start_date": None, "min_salary_eur": None,
             "alternance_rhythm": "   "}
    data = alice.put("/preferences", empty).json()
    assert data["keywords"] == [] and data["locations"] == [] and data["start_date"] is None
    assert data["alternance_rhythm"] is None  # texte vide après rognage : null


def test_text_is_trimmed(alice):  # noqa: F811
    data = alice.put("/preferences", {**FULL, "keywords": ["  data  "]}).json()
    assert data["keywords"] == ["data"]


INVALID = [
    {"keywords": [" "]},
    {"keywords": ["x" * 81]},
    {"keywords": [f"k{i}" for i in range(21)]},
    {"keywords": ["data", "data"]},
    {"locations": [{"label": "Lyon", "radius_km": 201}]},
    {"locations": [{"label": "Lyon", "radius_km": -1}]},
    {"locations": [{"label": "Lyon", "radius_km": 10, "extra": 1}]},
    {"locations": [{"label": "Lyon", "radius_km": 10}, {"label": "Lyon", "radius_km": 10}]},
    {"contract_types": ["freelance"]},
    {"contract_types": ["internship", "internship"]},
    {"duration_months": 0},
    {"duration_months": 61},
    {"education_level": "bac_2"},
    {"min_salary_eur": -1},
    {"start_date": "pas-une-date"},
    {"alternance_rhythm": "x" * 81},
    {"inconnu": True},
]


@pytest.mark.parametrize("change", INVALID)
def test_invalid_fields_are_refused(alice, change):  # noqa: F811
    response = alice.put("/preferences", {**FULL, **change})
    assert response.status_code == 422, change
    assert alice.get("/preferences").json()["updated_at"] is None  # rien n'a été enregistré


@pytest.mark.parametrize("missing", sorted(FULL))
def test_every_field_is_required(alice, missing):  # noqa: F811
    body = {k: v for k, v in FULL.items() if k != missing}
    assert alice.put("/preferences", body).status_code == 422


def test_preferences_require_a_session_and_csrf(alice, application):  # noqa: F811
    anonymous = TestClient(application, base_url="https://testserver")
    assert anonymous.get("/preferences").status_code == 401
    assert anonymous.put("/preferences", json=FULL).status_code == 401
    assert alice.client.put("/preferences", json=FULL).status_code == 403
    assert alice.client.put("/preferences", json=FULL, headers={"X-CSRF-Token": "faux"}).status_code == 403


def test_each_user_has_their_own_preferences(alice, bob):  # noqa: F811
    alice.put("/preferences", FULL)
    assert bob.get("/preferences").json()["updated_at"] is None
    bob.put("/preferences", {**FULL, "keywords": ["devops"], "remote_accepted": False})
    assert alice.get("/preferences").json()["keywords"] == FULL["keywords"]
    assert bob.get("/preferences").json()["keywords"] == ["devops"]
