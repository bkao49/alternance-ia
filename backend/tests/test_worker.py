"""Worker de collecte (#13) sur PostgreSQL, avec des collecteurs fictifs : aucun réseau, aucune vraie donnée."""
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest

from app import config, db, jobs
from app.collectors.base import (
    Collector,
    CollectorError,
    NetworkError,
    QuotaExceeded,
    SourceBlocked,
)
from app.collectors.fixture import FixtureCollector
from app.config import WorkerSettings
from app.worker import Worker

FIXTURES = Path(__file__).parent / "fixtures" / "collectors"
SETTINGS = WorkerSettings(heartbeat_seconds=0.2)


class Notes:
    def __init__(self):
        self.sent = []

    def notify(self, source, cause):
        self.sent.append((source, cause))


class Scripted(FixtureCollector):
    """Lit la fixture fictive, puis lève `error` après `before` offres."""

    calls = 0

    def __init__(self, source, error=None, before=0):
        super().__init__(FIXTURES / "source_a.json", source)
        self.error, self.before = error, before

    def fetch(self, query) -> Iterator:
        type(self).calls += 1
        for i, raw in enumerate(super().fetch(query)):
            if self.error and i >= self.before:
                break
            yield raw
        if self.error:
            raise self.error


@pytest.fixture
def env(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    Scripted.calls = 0
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        users = []
        for name in ("alice", "bob"):
            uid = str(conn.execute("INSERT INTO users (email, password_hash) VALUES (%s, 'x') RETURNING id",
                                   (f"{name}@example.test",)).fetchone()[0])
            conn.execute("INSERT INTO search_preferences (user_id, keywords) VALUES (%s, '{data}')", (uid,))
            users.append(uid)
    yield migrated_db, users
    db._engine(migrated_db).dispose()
    db._engine.cache_clear()


def sql(url, query, *args):
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.execute(query, args)
        return cur.fetchall() if cur.description else None


def queue(url, user, source="fixture_a"):
    sql(url, "INSERT INTO source_settings (user_id, source, enabled) VALUES (%s, %s, true)"
        " ON CONFLICT DO NOTHING", user, source)
    sql(url, "INSERT INTO jobs (user_id, kind, source) VALUES (%s, 'collect', %s)", user, source)


def worker(factory, notifier=None, name="w1"):
    return Worker({"fixture_a": factory}, SETTINGS, notifier or Notes(), name)


def job_row(url, user):
    return sql(url, "SELECT state, attempts, last_error, offers_found, offers_new FROM jobs "
               "WHERE user_id = %s ORDER BY created_at DESC", user)[0]


def count(url, user):
    return sql(url, "SELECT count(*) FROM job_postings WHERE user_id = %s", user)[0][0]


def test_collects_for_each_user_and_replaying_creates_no_duplicate(env):
    url, (alice, bob) = env
    queue(url, alice)
    queue(url, bob)
    w = worker(lambda: Scripted("fixture_a"))
    assert w.run_one() and w.run_one() and not w.run_one()
    first = count(url, alice)
    assert first > 0 and count(url, bob) == first  # chacun ses lignes
    assert job_row(url, alice)[0] == "done" and job_row(url, alice)[4] == first
    sql(url, "UPDATE jobs SET state = 'done', finished_at = now()")
    queue(url, alice)
    assert w.run_one()
    assert count(url, alice) == first and job_row(url, alice)[3:] == (first, 0)  # rien de nouveau
    assert sql(url, "SELECT last_success_at IS NOT NULL FROM source_settings WHERE user_id = %s",
               alice) == [(True,)]
    assert sql(url, "SELECT count(*) FROM job_postings "
                    "WHERE contract_type IS NULL OR fingerprint IS NULL")[0][0] == 0


def test_network_error_retries_later_with_backoff(env):
    url, (alice, _) = env
    queue(url, alice)
    w = worker(lambda: Scripted("fixture_a", NetworkError("fixture_a", "délai dépassé"), before=1))
    assert w.run_one()
    state, attempts, error, found, _ = job_row(url, alice)
    assert (state, attempts, error, found) == ("queued", 1, "délai dépassé", 1)
    assert count(url, alice) == 1  # l'offre déjà lue est gardée
    assert not w.run_one()  # pas avant le délai
    assert Scripted.calls == 1


def test_quota_uses_retry_after(env):
    url, (alice, _) = env
    queue(url, alice)
    quota = QuotaExceeded("fixture_a", "quota", retry_after=3600)
    assert worker(lambda: Scripted("fixture_a", quota)).run_one()
    delay = sql(url, "SELECT extract(epoch FROM run_at - now()) FROM jobs")[0][0]
    assert 3500 < delay <= 3600


def test_persistent_quota_blocks_the_source(env):
    url, (alice, _) = env
    notes = Notes()
    queue(url, alice)
    sql(url, "UPDATE jobs SET attempts = max_attempts - 1")
    quota = QuotaExceeded("fixture_a", "quota", retry_after=60)
    assert worker(lambda: Scripted("fixture_a", quota), notes).run_one()
    assert job_row(url, alice)[0] == "dead"
    assert sql(url, "SELECT enabled, blocked_cause FROM source_settings") == [(False, "quota persistant (429)")]
    assert notes.sent == [("fixture_a", "quota persistant (429)")]


def test_result_is_dropped_when_the_job_was_taken_over(env, monkeypatch):
    url, (alice, _) = env
    queue(url, alice)
    monkeypatch.setattr(jobs, "heartbeat", lambda *_: False)
    assert worker(lambda: Scripted("fixture_a")).run_one()
    assert count(url, alice) == 0


def test_block_stops_the_source_and_never_retries(env):
    url, (alice, bob) = env
    notes = Notes()
    queue(url, alice)
    queue(url, bob)
    w = worker(lambda: Scripted("fixture_a", SourceBlocked("fixture_a", "HTTP 403"), before=1), notes)
    assert w.run_one()  # tâche d'alice
    assert job_row(url, alice)[:3] == ("dead", 1, "HTTP 403")
    assert sql(url, "SELECT enabled, blocked_cause FROM source_settings WHERE user_id = %s",
               alice) == [(False, "HTTP 403")]
    assert notes.sent == [("fixture_a", "HTTP 403")]
    assert jobs.schedule_due(120) == 0  # plus de planification pour cette source
    assert w.run_one() and Scripted.calls == 2  # bob : sa propre source n'est pas bloquée
    assert not w.run_one()
    assert sql(url, "SELECT count(*) FROM jobs WHERE user_id = %s AND state = 'dead'", alice)[0][0] == 1


def test_other_errors_are_not_retried(env):
    url, (alice, _) = env
    queue(url, alice)
    assert worker(lambda: Scripted("fixture_a", CollectorError("fixture_a", "clé absente"))).run_one()
    assert job_row(url, alice)[:3] == ("failed", 1, "clé absente")

    def boom():
        raise RuntimeError("annonce secrète")
    sql(url, "UPDATE jobs SET state = 'done'")
    queue(url, alice)
    assert worker(boom).run_one()
    assert job_row(url, alice)[:3] == ("failed", 1, "erreur inattendue (RuntimeError)")  # pas de contenu


def test_unknown_source_and_missing_criteria_make_no_call(env):
    url, (alice, bob) = env
    sql(url, "DELETE FROM search_preferences WHERE user_id = %s", bob)
    queue(url, bob)
    queue(url, alice, "inconnue")
    w = worker(lambda: Scripted("fixture_a"))
    assert w.run_one() and w.run_one()
    assert Scripted.calls == 0
    assert job_row(url, bob)[0] == "done" and job_row(url, alice)[:3] == ("failed", 1, "source inconnue")


def test_job_of_a_crashed_worker_is_resumed(env):
    url, (alice, _) = env
    queue(url, alice)
    assert jobs.claim_job("mort")  # le worker plante ici : plus de battement
    sql(url, "UPDATE jobs SET heartbeat_at = now() - interval '1 hour'")
    w = worker(lambda: Scripted("fixture_a"))
    assert not w.run_one()
    w.tick()
    assert w.run_one()
    assert job_row(url, alice)[:2] == ("done", 2) and count(url, alice) > 0


def test_two_workers_run_each_job_exactly_once(env):
    url, (alice, bob) = env
    for n in range(6):
        queue(url, alice if n % 2 else bob, f"src_{n}")
    seen = []

    def factory(n: int):
        def make() -> Collector:
            seen.append(n)
            return Scripted(f"src_{n}")
        return make

    workers = [Worker({f"src_{n}": factory(n) for n in range(6)}, SETTINGS, Notes(), name)
               for name in ("w1", "w2")]

    def drain(w: Worker) -> None:
        while w.run_one():
            pass

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(drain, workers))
    assert sorted(seen) == list(range(6))
    assert sql(url, "SELECT count(*) FROM jobs WHERE state = 'done' AND attempts = 1")[0][0] == 6


def test_worker_settings_from_environment(monkeypatch):
    assert config.get_worker_settings().collect_interval_minutes == 120
    monkeypatch.setenv("COLLECT_INTERVAL_MINUTES", "240")
    assert config.get_worker_settings().collect_interval_minutes == 240
    monkeypatch.setenv("COLLECT_INTERVAL_MINUTES", "5")
    with pytest.raises(RuntimeError):
        config.get_worker_settings()
    monkeypatch.setenv("COLLECT_INTERVAL_MINUTES", "120")
    monkeypatch.setenv("WORKER_HEARTBEAT_SECONDS", "300")  # plus lent que le délai de péremption
    with pytest.raises(RuntimeError):
        config.get_worker_settings()
