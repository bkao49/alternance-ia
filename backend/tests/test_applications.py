import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient

from app import db
from app.create_user import create_user
from app.defaults import DEFAULT_STATUSES
from app.main import create_app

PASSWORD = "mot-de-passe-de-test-123"  # fictif, uniquement pour les tests
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"
IMPLEMENTED_PREFIXES = {"auth", "applications", "statuses"}


class Api:
    """Client de test connecté : ajoute le jeton CSRF aux écritures, comme le fera le frontend."""

    def __init__(self, test_client):
        self.client = test_client

    def login(self, email):
        response = self.client.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200
        return response.json()["id"]

    def get(self, path, **kwargs):
        return self.client.get(path, **kwargs)

    def write(self, method, path, json=None):
        return self.client.request(method, path, json=json, headers={"X-CSRF-Token": self.client.cookies["csrf_token"]})

    def post(self, path, json=None):
        return self.write("POST", path, json)

    def patch(self, path, json=None):
        return self.write("PATCH", path, json)


@pytest.fixture
def application(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(32))
    yield create_app()
    db._engine(migrated_db).dispose()
    db._engine.cache_clear()


def make_api(application, email):
    create_user(email, PASSWORD)
    api = Api(TestClient(application, base_url="https://testserver"))
    api.user_id = api.login(email)
    return api


@pytest.fixture
def alice(application):
    return make_api(application, "alice@example.test")


@pytest.fixture
def bob(application, alice):
    return make_api(application, "bob@example.test")


def status_ids(api):
    return {s["system_key"] or s["name"]: s["id"] for s in api.get("/statuses").json()}


def new_application(api, **kwargs):
    body = {"company": "Acme", "title": "Alternant Data", **kwargs}
    response = api.post("/applications", body)
    assert response.status_code == 201, response.text
    return response.json()


def insert_offer(migrated_db, user_id):
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        return str(conn.execute(
            "INSERT INTO job_postings (user_id, source, external_id, url, title, company, description_text, "
            "content_hash) VALUES (%s, 'test', 'o1', 'https://exemple.test/o1', 'Alternance IA', 'Globex', 'd', 'h') "
            "RETURNING id", (user_id,)).fetchone()[0])


# --- Conformité au contrat OpenAPI ----------------------------------------------------------------


@pytest.fixture(scope="module")
def contract():
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def flatten(contract, schema):
    if "$ref" in schema:
        return flatten(contract, resolve(contract, schema["$ref"]))
    properties, required = dict(schema.get("properties", {})), set(schema.get("required", []))
    for part in schema.get("allOf", []):
        sub_properties, sub_required = flatten(contract, part)
        properties.update(sub_properties)
        required |= sub_required
    return properties, required


def resolve(contract, ref):
    node = contract
    for part in ref.removeprefix("#/").split("/"):
        node = node[part]
    return node


def assert_conforms(contract, schema_name, data):
    """Toute réponse contient les champs obligatoires du contrat et aucun champ non documenté."""
    properties, required = flatten(contract, {"$ref": f"#/components/schemas/{schema_name}"})
    assert required <= set(data), f"{schema_name}: champs manquants {required - set(data)}"
    assert set(data) <= set(properties), f"{schema_name}: champs non documentés {set(data) - set(properties)}"
    for key, value in data.items():
        spec = properties[key]
        assert has_expected_type(value, spec), f"{schema_name}.{key}: {value!r} ne correspond pas à {spec.get('type')}"
        if isinstance(value, dict) and "$ref" in spec:
            assert_conforms(contract, spec["$ref"].rsplit("/", 1)[1], value)
        elif isinstance(value, list) and "$ref" in spec.get("items", {}):
            for item in value:
                assert_conforms(contract, spec["items"]["$ref"].rsplit("/", 1)[1], item)


JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list,
              "object": dict, "null": type(None)}


def has_expected_type(value, spec):
    declared = spec.get("type")
    if declared is None:  # $ref, allOf : vérifié par la récursion
        return True
    allowed = [declared] if isinstance(declared, str) else declared
    return any(isinstance(value, JSON_TYPES[t]) and not (t in {"integer", "number"} and isinstance(value, bool))
               for t in allowed)


def normalise(path):
    return "/".join("{}" if part.startswith("{") else part for part in path.split("/"))


def test_routes_match_the_contract(contract):
    declared = {
        (method.upper(), normalise(path)): operation["operationId"]
        for path, item in contract["paths"].items() if path.split("/")[1] in IMPLEMENTED_PREFIXES
        for method, operation in item.items() if method in {"get", "post", "patch", "put", "delete"}
    }
    generated = create_app().openapi()["paths"]
    implemented = {
        (method.upper(), normalise(path)): operation.get("operationId")
        for path, item in generated.items() if path != "/health"
        for method, operation in item.items()
    }
    assert set(implemented) == set(declared)
    for key, operation_id in declared.items():
        if not key[1].startswith("/auth"):
            assert implemented[key] == operation_id, key


def test_default_statuses(alice, contract):
    statuses = alice.get("/statuses").json()
    assert [s["name"] for s in statuses] == [name for _, name, _ in DEFAULT_STATUSES]
    assert [s["system_key"] for s in statuses] == [key for key, _, _ in DEFAULT_STATUSES]
    assert len(statuses) == 10
    for status in statuses:
        assert_conforms(contract, "Status", status)


def test_responses_conform_to_the_contract(alice, contract):
    application = new_application(alice)
    assert_conforms(contract, "Application", application)
    assert_conforms(contract, "Application", alice.get(f"/applications/{application['id']}").json())
    assert_conforms(contract, "ApplicationPage", alice.get("/applications").json())
    assert_conforms(contract, "EventPage", alice.get(f"/applications/{application['id']}/events").json())
    for response in (alice.get("/applications/00000000-0000-0000-0000-000000000000"),
                     alice.post(f"/applications/{application['id']}/confirm-sent", {"confirmed": False})):
        assert_conforms(contract, "Error", response.json())


# --- Statuts personnalisables ----------------------------------------------------------------------


def test_custom_status_lifecycle(alice):
    created = alice.post("/statuses", {"name": "Relance prévue", "color": "#123abc"})
    assert created.status_code == 201
    assert created.json()["system_key"] is None and created.json()["position"] == 11
    assert alice.post("/statuses", {"name": "Relance prévue"}).status_code == 409
    renamed = alice.patch(f"/statuses/{status_ids(alice)['sent']}", {"name": "Postulée"})
    assert renamed.status_code == 200 and renamed.json()["system_key"] == "sent"  # la clé ne change pas
    assert alice.patch(f"/statuses/{created.json()['id']}", {"name": "Postulée"}).status_code == 409
    assert alice.client.delete("/statuses/" + created.json()["id"]).status_code == 405  # pas de suppression
    assert alice.post("/statuses", {"name": "x", "color": "rouge"}).status_code == 422


# --- Candidatures -----------------------------------------------------------------------------------


def test_create_manual_application_records_history(alice):
    application = new_application(alice, notes="à relancer")
    assert application["status"]["system_key"] == "to_prepare"
    assert application["sent_at"] is None and application["offer_id"] is None
    events = alice.get(f"/applications/{application['id']}/events").json()
    assert events["total"] == 1
    assert events["items"][0]["from_status"] is None and events["items"][0]["to_status"] == "À préparer"
    detected = new_application(alice, initial_status="detected")
    assert detected["status"]["system_key"] == "detected"


def test_create_rules(alice, migrated_db):
    assert alice.post("/applications", {"company": "Seule"}).status_code == 422  # ni offre ni titre
    assert alice.post("/applications", {"company": "A", "title": "B", "initial_status": "sent"}).status_code == 422
    assert alice.post("/applications", {"offer_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    offer_id = insert_offer(migrated_db, alice.user_id)
    from_offer = alice.post("/applications", {"offer_id": offer_id})
    assert from_offer.status_code == 201
    assert (from_offer.json()["company"], from_offer.json()["title"]) == ("Globex", "Alternance IA")
    assert from_offer.json()["offer_id"] == offer_id


def test_update_notes_not_status(alice):
    application = new_application(alice)
    updated = alice.patch(f"/applications/{application['id']}", {"notes": "appelé lundi"})
    assert updated.status_code == 200 and updated.json()["notes"] == "appelé lundi"
    assert updated.json()["status"]["id"] == application["status"]["id"]
    assert alice.patch(f"/applications/{application['id']}", {"company": None}).status_code == 422
    assert alice.patch(f"/applications/{application['id']}", {"title": None}).status_code == 422


def test_sent_cannot_be_reached_through_patch_routes(alice):
    application = new_application(alice)
    ids = status_ids(alice)
    for body in ({"status_id": ids["sent"]}, {"sent_at": "2026-01-01T00:00:00Z"},
                 {"status_id": ids["sent"], "sent_at": "2026-01-01T00:00:00Z"}):
        assert alice.patch(f"/applications/{application['id']}", body).status_code == 422
    for body in ({"name": "Piraté", "system_key": "sent"}, {"name": "Piraté", "system_key": None}):
        assert alice.patch(f"/statuses/{ids['interview']}", body).status_code == 422
    assert alice.post("/statuses", {"name": "Faux envoi", "system_key": "sent"}).status_code == 422
    after = alice.get(f"/applications/{application['id']}").json()
    assert after["status"]["system_key"] == "to_prepare" and after["sent_at"] is None
    assert [s["system_key"] for s in alice.get("/statuses").json()].count("sent") == 1


def test_two_simultaneous_confirmations_send_once(alice, application):
    created = new_application(alice)
    clients = []
    for _ in range(2):
        other = TestClient(application, base_url="https://testserver")
        other.cookies.update(alice.client.cookies)
        clients.append(other)

    def confirm(test_client):
        return test_client.post(f"/applications/{created['id']}/confirm-sent", json={"confirmed": True},
                                headers={"X-CSRF-Token": alice.client.cookies["csrf_token"]}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(confirm, clients))
    assert codes == [200, 409]
    events = alice.get(f"/applications/{created['id']}/events").json()
    assert events["total"] == 2  # création + un seul envoi


def test_search_treats_percent_and_underscore_literally(alice):
    new_application(alice, company="100% Data", title="Ingénieur")
    new_application(alice, company="Acme", title="Data_Engineer")
    new_application(alice, company="Globex", title="Analyste")
    assert alice.get("/applications?q=%25").json()["total"] == 1  # %
    assert alice.get("/applications?q=_").json()["total"] == 1  # _
    assert alice.get("/applications?q=c_e").json()["total"] == 0  # « Acme » ne correspond pas : _ n'est pas un joker
    assert alice.get("/applications?q=!").json()["total"] == 0


def test_blank_status_name_is_refused(alice):
    assert alice.post("/statuses", {"name": "   "}).status_code == 422
    assert alice.patch(f"/statuses/{status_ids(alice)['interview']}", {"name": "  "}).status_code == 422


def test_status_changes_are_recorded_newest_first_with_pagination(alice):
    application = new_application(alice)
    ids = status_ids(alice)
    for key in ("analyzed", "human_review", "waiting"):
        response = alice.post(f"/applications/{application['id']}/status", {"status_id": ids[key], "comment": key})
        assert response.status_code == 200 and response.json()["status"]["system_key"] == key
    events = alice.get(f"/applications/{application['id']}/events").json()
    assert [(e["from_status"], e["to_status"]) for e in events["items"]] == [
        ("À valider par un humain", "En attente"), ("Analysée", "À valider par un humain"),
        ("À préparer", "Analysée"), (None, "À préparer")]
    page = alice.get(f"/applications/{application['id']}/events?page=2&page_size=3").json()
    assert page["total"] == 4 and len(page["items"]) == 1
    unchanged = alice.post(f"/applications/{application['id']}/status", {"status_id": ids["waiting"]})
    assert unchanged.status_code == 200
    assert alice.get(f"/applications/{application['id']}/events").json()["total"] == 4  # pas d'événement en double


def test_sent_cannot_be_set_by_a_plain_status_change(alice):
    application = new_application(alice)
    response = alice.post(f"/applications/{application['id']}/status", {"status_id": status_ids(alice)["sent"]})
    assert response.status_code == 409 and response.json()["code"] == "confirmation_required"
    after = alice.get(f"/applications/{application['id']}").json()
    assert after["status"]["system_key"] == "to_prepare" and after["sent_at"] is None
    assert alice.get(f"/applications/{application['id']}/events").json()["total"] == 1


def test_sent_cannot_be_set_even_if_the_status_was_renamed(alice):
    application = new_application(alice)
    sent_id = status_ids(alice)["sent"]
    alice.patch(f"/statuses/{sent_id}", {"name": "Postulée"})
    response = alice.post(f"/applications/{application['id']}/status", {"status_id": sent_id})
    assert response.status_code == 409 and response.json()["code"] == "confirmation_required"


def test_confirm_sent_requires_explicit_confirmation(alice):
    application = new_application(alice)
    for body in ({"confirmed": False}, {"confirmed": "true"}, {"confirmed": 1}, {"confirmed": "yes"},
                 {"confirmed": None}, {"confirmed": [True]}):
        refused = alice.post(f"/applications/{application['id']}/confirm-sent", body)
        assert refused.status_code == 409 and refused.json()["code"] == "confirmation_required", body
    assert alice.post(f"/applications/{application['id']}/confirm-sent", {}).status_code == 422
    assert alice.post(f"/applications/{application['id']}/confirm-sent", {"confirmed": True, "x": 1}).status_code == 422
    assert alice.get(f"/applications/{application['id']}").json()["status"]["system_key"] == "to_prepare"
    confirmed = alice.post(f"/applications/{application['id']}/confirm-sent", {"confirmed": True})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"]["system_key"] == "sent" and confirmed.json()["sent_at"] is not None
    latest = alice.get(f"/applications/{application['id']}/events").json()["items"][0]
    assert (latest["from_status"], latest["to_status"], latest["actor"]) == ("À préparer", "Envoyée", "user")
    again = alice.post(f"/applications/{application['id']}/confirm-sent", {"confirmed": True})
    assert again.status_code == 409 and again.json()["code"] == "already_sent"


def test_leaving_sent_keeps_sent_at(alice):
    application = new_application(alice)
    sent_at = alice.post(f"/applications/{application['id']}/confirm-sent", {"confirmed": True}).json()["sent_at"]
    moved = alice.post(f"/applications/{application['id']}/status", {"status_id": status_ids(alice)["interview"]})
    assert moved.status_code == 200 and moved.json()["sent_at"] == sent_at


def test_list_filters_search_and_pagination(alice):
    ids = status_ids(alice)
    first = new_application(alice, company="Acme", title="Data Engineer")
    new_application(alice, company="Globex", title="ML Engineer")
    new_application(alice, company="Initech", title="Analyste", initial_status="detected")
    assert alice.get("/applications").json()["total"] == 3
    assert alice.get("/applications?q=engineer").json()["total"] == 2
    assert alice.get("/applications?q=acme").json()["items"][0]["id"] == first["id"]
    assert alice.get(f"/applications?status_id={ids['detected']}").json()["total"] == 1
    page = alice.get("/applications?page=2&page_size=2").json()
    assert page["total"] == 3 and len(page["items"]) == 1 and page["page"] == 2
    assert alice.get("/applications?page_size=101").status_code == 422
    assert alice.get("/applications?page=0").status_code == 422


# --- Sécurité : accès, CSRF, isolation entre utilisateurs --------------------------------------------

WRITES = [
    ("POST", "/applications", {"company": "A", "title": "B"}),
    ("PATCH", "/applications/00000000-0000-0000-0000-000000000000", {"notes": "x"}),
    ("POST", "/applications/00000000-0000-0000-0000-000000000000/status",
     {"status_id": "00000000-0000-0000-0000-000000000000"}),
    ("POST", "/applications/00000000-0000-0000-0000-000000000000/confirm-sent", {"confirmed": True}),
    ("POST", "/statuses", {"name": "x"}),
    ("PATCH", "/statuses/00000000-0000-0000-0000-000000000000", {"name": "x"}),
]
READS = ["/applications", "/applications/00000000-0000-0000-0000-000000000000",
         "/applications/00000000-0000-0000-0000-000000000000/events", "/statuses"]


@pytest.mark.parametrize("path", READS)
def test_reads_require_a_session(application, path):
    anonymous = TestClient(application, base_url="https://testserver")
    assert anonymous.get(path).status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_writes_require_a_session_then_a_csrf_token(alice, application, method, path, body):
    anonymous = TestClient(application, base_url="https://testserver")
    assert anonymous.request(method, path, json=body).status_code == 401
    assert alice.client.request(method, path, json=body).status_code == 403  # connecté mais sans jeton CSRF
    forged = alice.client.request(method, path, json=body, headers={"X-CSRF-Token": "faux"})
    assert forged.status_code == 403


def test_users_cannot_see_or_touch_each_others_data(alice, bob):
    application = new_application(alice)
    own_status = status_ids(alice)["interview"]
    assert bob.get("/applications").json()["total"] == 0
    assert bob.get(f"/applications/{application['id']}").status_code == 404
    assert bob.get(f"/applications/{application['id']}/events").status_code == 404
    assert bob.patch(f"/applications/{application['id']}", {"notes": "piraté"}).status_code == 404
    assert bob.post(f"/applications/{application['id']}/status", {"status_id": status_ids(bob)["interview"]}
                    ).status_code == 404
    assert bob.post(f"/applications/{application['id']}/confirm-sent", {"confirmed": True}).status_code == 404
    assert bob.patch(f"/statuses/{own_status}", {"name": "piraté"}).status_code == 404
    mine = new_application(bob)
    cross = bob.post(f"/applications/{mine['id']}/status", {"status_id": own_status})
    assert cross.status_code == 404  # le statut d'un autre utilisateur n'existe pas pour lui
    untouched = alice.get(f"/applications/{application['id']}").json()
    assert untouched["notes"] is None and untouched["status"]["system_key"] == "to_prepare"
    assert alice.get("/applications").json()["total"] == 1


def test_each_user_has_their_own_ten_statuses(alice, bob):
    assert len(alice.get("/statuses").json()) == len(bob.get("/statuses").json()) == 10
    assert not set(status_ids(alice).values()) & set(status_ids(bob).values())


def test_cannot_create_an_application_from_another_users_offer(alice, bob, migrated_db):
    offer_id = insert_offer(migrated_db, alice.user_id)
    assert bob.post("/applications", {"offer_id": offer_id}).status_code == 404
