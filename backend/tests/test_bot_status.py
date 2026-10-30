import datetime as dt

import psycopg
from test_applications import alice, application, assert_conforms, bob, contract  # noqa: F401
from test_offers import BASE_TIME, add_offer, add_score

NOW = dt.datetime.now(dt.UTC)


def add_source(db_url, user_id, source, *, enabled=True, interval=None, blocked_cause=None, last_run=None):
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO source_settings (user_id, source, enabled, interval_minutes, blocked_at, blocked_cause, "
            "last_run_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, source, enabled, interval, NOW if blocked_cause else None, blocked_cause, last_run))


def add_job(db_url, user_id, source, state, *, error=None, found=None, new=None, finished=None, attempts=1,
            run_at=None, created=None):
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO jobs (user_id, kind, source, state, last_error, offers_found, offers_new, finished_at, "
            "attempts, run_at, created_at) VALUES (%s, 'collect', %s, %s, %s, %s, %s, %s, %s, "
            "coalesce(%s, now()), coalesce(%s, now()))",
            (user_id, source, state, error, found, new, finished, attempts, run_at, created))


def by_source(status):
    return {s["source"]: s for s in status["sources"]}


def test_requires_a_session(application):  # noqa: F811
    from fastapi.testclient import TestClient

    assert TestClient(application, base_url="https://testserver").get("/bot/status").status_code == 401


def test_empty_status_is_honest(alice, contract):  # noqa: F811
    status = alice.get("/bot/status").json()
    assert status == {"sources": [], "activity": []}
    assert_conforms(contract, "BotStatus", status)


def test_each_state_and_next_run(alice, migrated_db, contract):  # noqa: F811
    uid, last = alice.user_id, NOW - dt.timedelta(minutes=30)
    add_source(migrated_db, uid, "adzuna", last_run=last, interval=180)
    add_job(migrated_db, uid, "adzuna", "done", found=40, new=3, finished=last)
    add_source(migrated_db, uid, "lba", last_run=last)
    add_job(migrated_db, uid, "lba", "failed", error="réponse illisible", finished=last)
    add_source(migrated_db, uid, "site_x", enabled=False, blocked_cause="blocage détecté (403)")
    add_source(migrated_db, uid, "site_y", enabled=False)
    add_source(migrated_db, uid, "site_z")
    status = alice.get("/bot/status").json()
    assert_conforms(contract, "BotStatus", status)
    sources = by_source(status)
    assert sources["adzuna"]["state"] == "ok" and sources["adzuna"]["offers_found"] == 40
    assert dt.datetime.fromisoformat(sources["adzuna"]["next_run_at"]) == last + dt.timedelta(minutes=180)
    assert sources["lba"]["state"] == "error" and sources["lba"]["cause"] == "réponse illisible"
    assert dt.datetime.fromisoformat(sources["lba"]["next_run_at"]) == last + dt.timedelta(minutes=120)  # défaut
    assert sources["site_x"]["state"] == "blocked" and sources["site_x"]["cause"] == "blocage détecté (403)"
    assert sources["site_y"]["state"] == "disabled" and sources["site_y"]["cause"]
    assert sources["site_z"]["state"] == "pending"
    for name in ("site_x", "site_y", "site_z"):
        assert "next_run_at" not in sources[name]
    assert status["next_run_at"] == sources["adzuna"]["next_run_at"] or status["next_run_at"] == sources["lba"]["next_run_at"]


def test_queued_job_gives_the_next_run(alice, migrated_db):  # noqa: F811
    soon = NOW + dt.timedelta(minutes=7)
    add_source(migrated_db, alice.user_id, "adzuna", last_run=NOW)
    add_job(migrated_db, alice.user_id, "adzuna", "queued", attempts=0, run_at=soon)
    source = by_source(alice.get("/bot/status").json())["adzuna"]
    assert source["state"] == "pending"
    assert dt.datetime.fromisoformat(source["next_run_at"]) == soon


def test_activity_is_recent_first_capped_and_fixed_text(alice, migrated_db, contract):  # noqa: F811
    uid = alice.user_id
    add_source(migrated_db, uid, "adzuna")
    add_source(migrated_db, uid, "site_x", enabled=False, blocked_cause="blocage détecté (403)")
    for minute in range(12):
        add_job(migrated_db, uid, "adzuna", "done", found=minute, new=1, finished=BASE_TIME + dt.timedelta(minutes=minute),
                created=BASE_TIME + dt.timedelta(minutes=minute))
    add_job(migrated_db, uid, "site_x", "dead", error="blocage détecté (403)", finished=BASE_TIME + dt.timedelta(days=1))
    add_job(migrated_db, uid, "adzuna", "dead", error="worker disparu", finished=BASE_TIME + dt.timedelta(hours=1))
    activity = alice.get("/bot/status").json()["activity"]
    assert len(activity) == 10
    assert [a["outcome"] for a in activity[:3]] == ["blocked", "error", "done"]
    assert activity[0]["message"] == "blocage détecté (403)" and activity[1]["message"] == "worker disparu"
    assert activity[2]["message"] == "11 offres lues, 1 nouvelles"
    assert_conforms(contract, "BotActivity", activity[0])


def test_status_is_isolated_per_user(alice, bob, migrated_db):  # noqa: F811
    add_source(migrated_db, alice.user_id, "adzuna")
    add_job(migrated_db, alice.user_id, "adzuna", "done", found=1, new=1, finished=NOW)
    assert bob.get("/bot/status").json() == {"sources": [], "activity": []}


def test_contract_type_filter_and_new_fields(alice, bob, migrated_db, contract):  # noqa: F811
    def typed(external_id, kind, score=None, explanation=None, user=alice):
        offer_id = add_offer(migrated_db, user.user_id, external_id, title=external_id)
        with psycopg.connect(migrated_db, autocommit=True) as conn:
            conn.execute("UPDATE job_postings SET contract_type = %s WHERE id = %s", (kind, offer_id))
        if score is not None:
            add_score(migrated_db, user.user_id, offer_id, score, explanation=explanation)

    typed("stage", "internship", 4.5, "Très proche de votre profil")
    typed("alt", "apprenticeship", 4.0)
    typed("cdi", "permanent", 3.8)
    typed("ancienne", None, 3.0)
    typed("autre-utilisateur", "internship", 5.0, user=bob)
    page = alice.get("/offers?contract_type=internship&contract_type=apprenticeship").json()
    assert [o["title"] for o in page["items"]] == ["stage", "alt"] and page["total"] == 2
    for item in page["items"]:
        assert_conforms(contract, "Offer", item)
    assert page["items"][0]["contract_type"] == "internship"
    assert page["items"][0]["explanation"] == "Très proche de votre profil"
    assert "explanation" not in page["items"][1]
    assert alice.get("/offers?contract_type=permanent&min_score=3.5").json()["total"] == 1
    assert alice.get("/offers").json()["total"] == 4  # sans filtre, l'ancienne offre reste visible
    assert alice.get("/offers?contract_type=cdi").status_code == 422
