"""File de tâches PostgreSQL (#13) : prise exclusive, reprise, blocage, isolation. Aucun réseau."""
import random
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from sqlalchemy import text

from app import db, jobs


@pytest.fixture
def env(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        users = [str(conn.execute("INSERT INTO users (email, password_hash) VALUES (%s, 'x') RETURNING id",
                                  (f"{n}@example.test",)).fetchone()[0]) for n in ("alice", "bob")]
    yield migrated_db, users
    db._engine(migrated_db).dispose()
    db._engine.cache_clear()


def sql(url, query, *args):
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.execute(query, args)
        return cur.fetchall() if cur.description else None


def enable(url, user, source="lba", **cols):
    sql(url, "INSERT INTO source_settings (user_id, source, enabled, interval_minutes, blocked_at, last_run_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)", user, source, cols.get("enabled", True),
        cols.get("interval"), cols.get("blocked_at"), cols.get("last_run_at"))


def add_job(url, user, source="lba", **cols):
    return str(sql(url, "INSERT INTO jobs (user_id, kind, source, state, attempts, heartbeat_at, run_at)"
                   " VALUES (%s, 'collect', %s, %s, %s, %s, now() - interval '1 minute') RETURNING id",
                   user, source, cols.get("state", "queued"), cols.get("attempts", 0),
                   cols.get("heartbeat"))[0][0])


def state(url, job_id):
    return sql(url, "SELECT state, attempts, last_error FROM jobs WHERE id = %s", job_id)[0]


def test_two_workers_never_take_the_same_job(env):
    url, (alice, _) = env
    for n in range(12):
        enable(url, alice, f"src_{n:02d}")
        add_job(url, alice, f"src_{n:02d}")
    with ThreadPoolExecutor(4) as pool:
        def drain(worker):
            taken = []
            while job := jobs.claim_job(worker):
                taken.append(job.id)
            return taken
        results = list(pool.map(drain, ["w1", "w2", "w3", "w4"]))
    flat = [i for r in results for i in r]
    assert len(flat) == 12 and len(set(flat)) == 12


def test_claim_skips_disabled_blocked_and_future_jobs(env):
    url, (alice, _) = env
    enable(url, alice, "off", enabled=False)
    enable(url, alice, "blocked", blocked_at="2026-01-01T00:00:00Z")
    enable(url, alice, "later")
    add_job(url, alice, "off")
    add_job(url, alice, "blocked")
    sql(url, "INSERT INTO jobs (user_id, kind, source, run_at) VALUES (%s, 'collect', 'later', now() + interval '1 hour')", alice)
    assert jobs.claim_job("w") is None


def test_crashed_worker_job_is_requeued_then_dead(env):
    url, (alice, _) = env
    enable(url, alice)
    job = add_job(url, alice, state="running", attempts=1, heartbeat="2000-01-01T00:00:00Z")
    fresh = add_job(url, alice, "autre", state="running", attempts=1)  # battement récent (now par défaut : NULL → ignoré)
    sql(url, "UPDATE jobs SET heartbeat_at = now() WHERE id = %s", fresh)
    assert jobs.reap_stale(600) == 1
    assert state(url, job)[:2] == ("queued", 1) and state(url, fresh)[0] == "running"
    claimed = jobs.claim_job("w2")
    assert claimed and claimed.attempts == 2
    sql(url, "UPDATE jobs SET attempts = max_attempts, heartbeat_at = '2000-01-01' WHERE id = %s", job)
    assert jobs.reap_stale(600) == 1 and state(url, job)[0] == "dead"


def test_lost_lease_cannot_overwrite(env):
    url, (alice, _) = env
    enable(url, alice)
    add_job(url, alice)
    job = jobs.claim_job("w1")
    sql(url, "UPDATE jobs SET heartbeat_at = '2000-01-01' WHERE id = %s", job.id)
    jobs.reap_stale(600)
    assert jobs.claim_job("w2")
    assert not jobs.heartbeat(job, "w1") and not jobs.succeed(job, "w1", 1, 1, 0)
    assert state(url, job.id)[0] == "running"


def test_retry_backoff_then_dead(env):
    url, (alice, _) = env
    enable(url, alice)
    add_job(url, alice)
    job = jobs.claim_job("w")
    assert jobs.retry_later(job, "w", "erreur réseau")
    assert state(url, job.id)[:2] == ("queued", 1) and jobs.claim_job("w") is None  # pas avant le délai
    last = jobs.Job(job.id, alice, "collect", "lba", 5, 5)
    sql(url, "UPDATE jobs SET state = 'running', locked_by = 'w' WHERE id = %s", job.id)
    assert jobs.retry_later(last, "w", "erreur réseau") and state(url, job.id)[0] == "dead"
    assert sql(url, "SELECT last_run_at IS NOT NULL, last_success_at IS NULL FROM source_settings")[0] == (True, True)


def test_backoff_grows_and_is_capped():
    rng = random.Random(1)
    delays = [jobs.backoff_seconds(n, rng) for n in (1, 2, 3, 4)]
    assert delays == sorted(delays) and 48 <= delays[0] <= 72
    assert jobs.backoff_seconds(30) <= jobs.MAX_BACKOFF_SECONDS * 1.2


def test_block_stops_source_and_never_retries(env):
    url, (alice, bob) = env
    enable(url, alice)
    enable(url, bob)
    add_job(url, alice)
    other = add_job(url, bob)
    job = jobs.claim_job("w")
    assert job.user_id == alice
    jobs.block_source(job, "w", "HTTP 403")
    assert state(url, job.id)[0] == "dead"
    assert sql(url, "SELECT enabled, blocked_cause, blocked_at IS NOT NULL FROM source_settings "
               "WHERE user_id = %s", alice) == [(False, "HTTP 403", True)]
    assert sql(url, "SELECT enabled FROM source_settings WHERE user_id = %s", bob) == [(True,)]
    assert state(url, other)[0] == "queued"  # l'autre utilisateur n'est pas touché
    assert jobs.schedule_due(120) == 0 and jobs.claim_job("w") is not None  # seule la tâche de bob


def test_schedule_creates_one_job_per_due_source_and_user(env):
    url, (alice, bob) = env
    enable(url, alice, "lba")
    enable(url, bob, "lba")
    enable(url, alice, "adzuna", enabled=False)
    enable(url, alice, "recent", last_run_at="2999-01-01T00:00:00Z")
    enable(url, bob, "old", interval=60, last_run_at="2000-01-01T00:00:00Z")
    assert jobs.schedule_due(120) == 3
    assert jobs.schedule_due(120) == 0  # pas de doublon tant que la tâche est active
    assert sorted(sql(url, "SELECT source FROM jobs")) == [("lba",), ("lba",), ("old",)]


def test_default_interval_applies_only_when_none(env):
    url, (alice, _) = env
    enable(url, alice, "aa", last_run_at="2000-01-01T00:00:00Z")
    sql(url, "UPDATE source_settings SET last_run_at = now() - interval '90 minutes'")
    assert jobs.schedule_due(120) == 0
    sql(url, "UPDATE source_settings SET interval_minutes = 60")
    assert jobs.schedule_due(120) == 1


def test_rls_hides_other_users_jobs(env):
    url, (alice, bob) = env
    enable(url, alice)
    add_job(url, alice)
    with db.user_scope(bob) as conn:
        assert conn.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM source_settings")).scalar_one() == 0
    with db.user_scope() as conn:
        assert conn.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0


def test_dead_by_reaper_keeps_the_source_interval(env):
    url, (alice, _) = env
    enable(url, alice, last_run_at="2000-01-01T00:00:00Z")
    job = add_job(url, alice, state="running", attempts=5, heartbeat="2000-01-01T00:00:00Z")
    assert jobs.reap_stale(600) == 1 and state(url, job)[0] == "dead"
    assert jobs.schedule_due(120) == 0  # pas de relance à la minute suivante


def test_source_retry_after_is_bounded(env):
    url, (alice, _) = env
    enable(url, alice)
    for asked, low, high in ((0, 60, 60), (10**12, 21600, 21600), (3600, 3600, 3600)):
        add_job(url, alice)
        job = jobs.claim_job("w")
        jobs.retry_later(job, "w", "quota", after=asked)
        delay = sql(url, "SELECT extract(epoch FROM run_at - now()) FROM jobs WHERE id = %s", job.id)[0][0]
        assert low - 5 <= delay <= high
        sql(url, "DELETE FROM jobs")
