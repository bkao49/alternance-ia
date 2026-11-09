"""Alertes e-mail par utilisateur : chiffrement, API, test de connexion, collecte sous RLS. Aucun réseau, aucune vraie boîte."""
import logging
from typing import ClassVar

import psycopg
import pytest
from fake_web import PUBLIC_IP
from test_applications import alice, application, assert_conforms, bob, contract  # noqa: F401
from test_mail_collector import FakeMailbox, fixture, message
from test_worker import SETTINGS, Notes, env, sql  # noqa: F401

from app import mailbox
from app.collectors.base import CollectorError, NetworkError
from app.db import user_scope
from app.worker import Worker

SECRET = "mot-de-passe-d-application-fictif"
BOX = {"host": "imap.example.test", "port": 993, "username": "alertes@example.test", "password": SECRET,
       "folder": "INBOX"}


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("app.mailbox.system_resolver", lambda _host: [PUBLIC_IP])


class FakeImap:
    """Remplace la connexion IMAP : garde les identifiants reçus, ou refuse selon `fail`."""

    calls: ClassVar[list] = []
    fail: ClassVar[Exception | None] = None
    box: ClassVar[FakeMailbox | None] = None

    def __new__(cls, host, user, password, port=993, folder="INBOX"):
        cls.calls.append((host, user, password, port, folder))
        if cls.fail:
            raise cls.fail
        return cls.box or FakeMailbox()


@pytest.fixture
def imap(monkeypatch):
    FakeImap.calls, FakeImap.fail, FakeImap.box = [], None, None
    monkeypatch.setattr("app.mailbox.connect_imap", FakeImap)
    return FakeImap


def test_password_is_encrypted_with_a_derived_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a" * 32)
    token = mailbox.encrypt(SECRET)
    assert SECRET not in token and mailbox.decrypt(token) == SECRET
    assert mailbox.encrypt(SECRET) != token  # chaque chiffrement est unique
    monkeypatch.setenv("SECRET_KEY", "b" * 32)  # clé changée : illisible, jamais un mot de passe faux
    with pytest.raises(ValueError):
        mailbox.decrypt(token)


def test_empty_then_saved_box_never_returns_the_password(alice, migrated_db, contract):  # noqa: F811
    assert alice.get("/sources/email/mailbox").json() == {"configured": False}
    saved = alice.put("/sources/email/mailbox", BOX)
    assert saved.status_code == 200, saved.text
    assert_conforms(contract, "Mailbox", saved.json())
    assert SECRET not in saved.text and SECRET not in alice.client.get("/sources/email/mailbox").text
    assert "password" not in saved.json()
    with psycopg.connect(migrated_db) as conn:
        stored = conn.execute("SELECT password_enc FROM email_boxes").fetchone()[0]
    assert SECRET not in stored and mailbox.decrypt(stored) == SECRET


def test_update_without_password_keeps_the_stored_one(alice, migrated_db):  # noqa: F811
    assert alice.put("/sources/email/mailbox", {k: v for k, v in BOX.items() if k != "password"}).status_code == 422
    alice.put("/sources/email/mailbox", BOX)
    changed = {k: v for k, v in BOX.items() if k != "password"} | {"folder": "Alertes"}
    assert alice.put("/sources/email/mailbox", changed).json()["folder"] == "Alertes"
    with psycopg.connect(migrated_db) as conn:
        assert mailbox.decrypt(conn.execute("SELECT password_enc FROM email_boxes").fetchone()[0]) == SECRET


@pytest.mark.parametrize("change", [
    {"port": 143}, {"port": 22}, {"host": "127.0.0.1"}, {"host": "localhost"}, {"host": "10.0.0.5"},
    {"host": "imap.interne.local"}, {"host": ""}, {"username": ""}, {"folder": ""},
    {"username": "a\r\nb@example.test"}, {"password": "x\nA002 DELETE INBOX"}, {"password": ""}, {"extra": 1},
])
def test_rejects_unsafe_or_invalid_settings(alice, change):  # noqa: F811
    assert alice.put("/sources/email/mailbox", BOX | change).status_code == 422
    assert alice.get("/sources/email/mailbox").json() == {"configured": False}


def test_rejects_a_name_that_resolves_to_a_private_address(alice, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.mailbox.system_resolver", lambda _host: ["192.168.0.10"])
    refused = alice.put("/sources/email/mailbox", BOX)
    assert refused.status_code == 422 and "non publique" in refused.json()["message"]


def test_each_user_has_their_own_box_and_delete_switches_the_source_off(alice, bob):  # noqa: F811
    alice.put("/sources/email/mailbox", BOX)
    assert bob.get("/sources/email/mailbox").json() == {"configured": False}
    assert bob.post("/sources/email/mailbox/test").status_code == 404
    alice.put("/sources/email", {"enabled": True, "interval_minutes": None})
    assert alice.delete("/sources/email/mailbox").status_code == 204
    assert alice.get("/sources/email/mailbox").json() == {"configured": False}
    assert not {s["source"]: s for s in alice.get("/sources").json()}["email"]["enabled"]


def test_email_source_needs_a_box_before_it_can_be_enabled(alice):  # noqa: F811
    refused = alice.put("/sources/email", {"enabled": True, "interval_minutes": None})
    assert refused.status_code == 409 and "boîte" in refused.json()["message"]
    alice.put("/sources/email/mailbox", BOX)
    assert alice.put("/sources/email", {"enabled": True, "interval_minutes": 180}).json()["enabled"]


def test_connection_test_success_and_fixed_failure_messages(alice, imap, contract, migrated_db):  # noqa: F811
    alice.put("/sources/email/mailbox", BOX)
    ok = alice.post("/sources/email/mailbox/test")
    assert ok.status_code == 200 and ok.json()["ok"], ok.text
    assert_conforms(contract, "MailboxTest", ok.json())
    assert imap.calls == [("imap.example.test", "alertes@example.test", SECRET, 993, "INBOX")]
    state = alice.get("/sources/email/mailbox").json()
    assert state["last_test_ok"] is True and "last_test_error" not in state
    imap.fail = CollectorError("email", "identifiants IMAP refusés")
    sql(migrated_db, "UPDATE email_boxes SET last_test_at = now() - interval '1 minute'")  # lève le créneau de 10 s
    failed = alice.post("/sources/email/mailbox/test").json()
    assert failed["ok"] is False and "refusés" in failed["message"] and SECRET not in failed["message"]
    assert alice.get("/sources/email/mailbox").json()["last_test_ok"] is False


def test_connection_test_is_rate_limited_and_logs_no_secret(alice, imap, caplog):  # noqa: F811
    alice.put("/sources/email/mailbox", BOX)
    imap.fail = NetworkError("email", "connexion IMAP impossible")
    with caplog.at_level(logging.DEBUG):
        first = alice.post("/sources/email/mailbox/test")
        second = alice.post("/sources/email/mailbox/test")
    assert first.json()["ok"] is False and second.status_code == 429
    assert SECRET not in caplog.text and SECRET not in first.text
    assert len(imap.calls) == 1


def test_connection_test_refuses_a_name_that_became_private(alice, imap, monkeypatch):  # noqa: F811
    alice.put("/sources/email/mailbox", BOX)
    monkeypatch.setattr("app.mailbox.system_resolver", lambda _host: ["169.254.169.254"])
    result = alice.post("/sources/email/mailbox/test").json()
    assert result["ok"] is False and "non publique" in result["message"] and imap.calls == []


# --- Collecte par le worker -------------------------------------------------------------------


def worker():
    return Worker({}, SETTINGS, Notes(), "w1")


def queue_email(url, user):
    sql(url, "INSERT INTO source_settings (user_id, source, enabled) VALUES (%s, 'email', true) "
             "ON CONFLICT DO NOTHING", user)
    sql(url, "INSERT INTO jobs (user_id, kind, source) VALUES (%s, 'collect', 'email')", user)


def add_box(url, user, password=SECRET):
    sql(url, "INSERT INTO email_boxes (user_id, host, username, password_enc) VALUES (%s, %s, %s, %s)",
        user, BOX["host"], BOX["username"], mailbox.encrypt(password))


def test_worker_reads_only_the_box_of_the_job_owner(env, imap):  # noqa: F811
    url, (alice_id, bob_id) = env
    add_box(url, alice_id)
    box = FakeMailbox(message("1", "jobs@linkedin.com", fixture("linkedin"),
                              "mx.example.test; dmarc=pass header.from=linkedin.com"))
    imap.box = box
    queue_email(url, alice_id)
    queue_email(url, bob_id)  # Bob n'a aucune boîte : rien n'est lu
    w = worker()
    assert w.run_one() and w.run_one() and not w.run_one()
    rows = dict(sql(url, "SELECT user_id::text, count(*) FROM job_postings WHERE source = 'email' GROUP BY 1"))
    assert rows == {alice_id: 2} and len(imap.calls) == 1
    assert imap.calls[0][:3] == (BOX["host"], BOX["username"], SECRET)
    assert box.marked == ["1"]
    assert sql(url, "SELECT state FROM jobs WHERE user_id = %s", bob_id) == [("done",)]


def test_worker_reports_an_unreadable_password_without_connecting(env, imap, monkeypatch):  # noqa: F811
    url, (alice_id, _) = env
    add_box(url, alice_id)
    monkeypatch.setenv("SECRET_KEY", "z" * 32)  # clé serveur changée depuis l'enregistrement
    queue_email(url, alice_id)
    assert worker().run_one()
    assert imap.calls == []
    state, error = sql(url, "SELECT state, last_error FROM jobs WHERE user_id = %s", alice_id)[0]
    assert state == "failed" and "ressaisissez" in error and SECRET not in error


def test_collector_is_none_without_a_box(env):  # noqa: F811
    _, (alice_id, _) = env
    with user_scope(alice_id) as conn:
        assert mailbox.email_collector(conn) is None
