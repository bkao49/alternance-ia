import logging
import secrets

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db, security
from app.create_user import create_user
from app.main import create_app

PASSWORD = "mot-de-passe-de-test-123"  # fictif, uniquement pour les tests


# --- Briques de sécurité, sans base de données -------------------------------------------------


def test_password_is_hashed_with_argon2_and_verified():
    hashed = security.hash_password(PASSWORD)
    assert hashed.startswith("$argon2id$")
    assert PASSWORD not in hashed
    assert security.verify_password(hashed, PASSWORD)
    assert not security.verify_password(hashed, PASSWORD + "x")


def test_unknown_account_never_verifies():
    assert not security.verify_password(None, PASSWORD)


def test_session_token_roundtrip_tamper_and_expiry():
    secret = secrets.token_hex(32)
    token, sid = security.create_session(secret, "user-1")
    assert security.read_session(secret, token, max_age=60) == {"u": "user-1", "s": sid}
    assert security.read_session(secret, token + "x", max_age=60) is None
    assert security.read_session(secrets.token_hex(32), token, max_age=60) is None
    assert security.read_session(secret, token, max_age=-1) is None  # expiré


def test_csrf_token_is_bound_to_the_session():
    secret = secrets.token_hex(32)
    token = security.csrf_token(secret, "sid-a")
    assert security.csrf_is_valid(secret, "sid-a", token)
    assert not security.csrf_is_valid(secret, "sid-b", token)
    assert not security.csrf_is_valid(secret, "sid-a", None)
    assert not security.csrf_is_valid(secret, "sid-a", "")


def test_limiter_blocks_after_max_failures_then_releases():
    now = [1000.0]
    limiter = security.LoginLimiter(max_failures=3, window=60, clock=lambda: now[0])
    for _ in range(2):
        limiter.record_failure("k")
    assert limiter.retry_after("k") == 0
    limiter.record_failure("k")
    assert 0 < limiter.retry_after("k") <= 61
    assert limiter.retry_after("autre") == 0
    now[0] += 61
    assert limiter.retry_after("k") == 0


# --- API, contre un vrai PostgreSQL ------------------------------------------------------------


@pytest.fixture
def client(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(32))
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    # https pour que le client renvoie les cookies marqués Secure.
    with TestClient(create_app(), base_url="https://testserver") as test_client:
        yield test_client
    db._engine(migrated_db).dispose()
    db._engine.cache_clear()


def login(client, email="alice@example.test", password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


@pytest.fixture
def alice(client):
    return create_user("alice@example.test", PASSWORD)


def test_login_sets_hardened_cookies(client, alice):
    response = login(client)
    assert response.status_code == 200
    assert response.json() == {"id": alice, "email": "alice@example.test"}
    cookies = {c.split("=")[0]: c for c in response.headers.get_list("set-cookie")}
    session, csrf = cookies["session"].lower(), cookies["csrf_token"].lower()
    assert "httponly" in session and "secure" in session and "samesite=strict" in session
    assert "httponly" not in csrf and "secure" in csrf  # lisible par le front (double soumission)


def test_wrong_password_and_unknown_account_are_indistinguishable(client, alice):
    wrong = login(client, password="mauvais-mot-de-passe")
    unknown = login(client, email="inconnu@example.test")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"code": "invalid_credentials", "message": "Identifiants invalides"}


def test_blocked_after_five_failures_even_with_the_right_password(client, alice):
    for _ in range(5):
        assert login(client, password="mauvais-mot-de-passe").status_code == 401
    blocked = login(client)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.json()["code"] == "too_many_attempts"


def test_a_success_resets_the_email_counter_but_not_the_ip_counter(client, alice):
    limiter = client.app.state.login_limiter
    for _ in range(4):
        login(client, password="mauvais-mot-de-passe")
    assert login(client).status_code == 200
    assert limiter.retry_after("email:alice@example.test") == 0
    # L'IP garde ses échecs : sinon un compte valide servirait à réinitialiser la limite des essais.
    login(client, password="mauvais-mot-de-passe")
    assert limiter.retry_after("ip:testclient") > 0


@pytest.mark.parametrize(("method", "path"), [("GET", "/auth/me"), ("POST", "/auth/logout")])
def test_protected_routes_reject_missing_and_forged_cookies(client, alice, method, path):
    assert client.request(method, path).status_code == 401
    client.cookies.set("session", "falsifie.cookie.jeton")
    assert client.request(method, path).status_code == 401


def test_me_returns_only_the_signed_in_user(client, alice):
    create_user("bob@example.test", PASSWORD)
    assert login(client, email="bob@example.test").status_code == 200
    assert client.get("/auth/me").json()["email"] == "bob@example.test"


def test_logout_requires_csrf_then_clears_the_session(client, alice):
    login(client)
    assert client.post("/auth/logout").status_code == 403
    assert client.post("/auth/logout", headers={"X-CSRF-Token": "faux"}).status_code == 403
    assert client.get("/auth/me").status_code == 200  # toujours connecté
    token = client.cookies.get("csrf_token")
    assert client.post("/auth/logout", headers={"X-CSRF-Token": token}).status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_csrf_token_of_another_session_is_refused(client, alice):
    login(client)
    other = security.csrf_token(secrets.token_hex(32), "autre-session")
    assert client.post("/auth/logout", headers={"X-CSRF-Token": other}).status_code == 403


def test_session_of_a_deleted_account_is_refused(client, alice, migrated_db):
    login(client)
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute("DELETE FROM users")
    assert client.get("/auth/me").status_code == 401


def test_validation_errors_never_echo_the_password(client):
    response = client.post("/auth/login", json={"email": "x", "password": "SuperSecret-123"})
    assert response.status_code == 422
    assert "SuperSecret-123" not in response.text
    assert client.post("/auth/login", json={"email": "a@example.test", "password": "x" * 2000}).status_code == 422


def test_logs_contain_neither_password_nor_email(client, alice, caplog):
    with caplog.at_level(logging.DEBUG):
        login(client, password="mot-de-passe-secret-xyz")
    assert "mot-de-passe-secret-xyz" not in caplog.text
    assert "alice@example.test" not in caplog.text


def test_login_function_is_the_only_pre_login_read_access(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(32))
    create_user("alice@example.test", PASSWORD)
    with db.user_scope() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 0
        found = conn.execute(text("SELECT user_id FROM auth_lookup_user('alice@example.test')")).all()
        assert len(found) == 1
        assert conn.execute(text("SELECT count(*) FROM auth_lookup_user('autre@example.test')")).scalar() == 0
    db._engine(migrated_db).dispose()
    db._engine.cache_clear()
