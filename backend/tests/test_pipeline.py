"""Chaîne complète du worker : collecte → filtres durs → extraction → score, sur PostgreSQL.
Collecteur de fixtures fictives et faux fournisseur : aucun réseau, aucune vraie donnée."""
import json
import logging

from test_worker import SETTINGS, Notes, Scripted, env, queue, sql  # noqa: F401

from app.ai.gateway import FakeProvider, LLMGateway
from app.worker import Worker

EXTRACTION = json.dumps({
    "skills": ["Python"], "education_level": None, "duration_months": 6, "contract_type": None,
    "location": None, "remote": None, "salary_eur_year": None, "start_date": None, "summary": "Offre fictive."})


def make_worker(provider=None, cap=5.0):
    provider = provider or FakeProvider(reply=lambda request: EXTRACTION)
    gateway = LLMGateway(provider, daily_cap_eur=cap)
    return Worker({"fixture_a": lambda: Scripted("fixture_a")}, SETTINGS, Notes(), "w1", gateway), provider


def totals(url, user):
    postings = sql(url, "SELECT count(*) FROM job_postings WHERE user_id = %s", user)[0][0]
    scored = sql(url, "SELECT count(DISTINCT job_posting_id) FROM scores WHERE user_id = %s", user)[0][0]
    return postings, scored


def test_each_user_gets_collected_filtered_extracted_and_scored(env):  # noqa: F811
    url, (alice, bob) = env
    worker, provider = make_worker()
    queue(url, alice)
    queue(url, bob)
    assert worker.run_one() and worker.run_one()
    for user in (alice, bob):
        postings, scored = totals(url, user)
        assert postings > 0 and scored == postings  # aucune offre sans score
        assert sql(url, "SELECT count(*) FROM analyses WHERE user_id = %s", user)[0][0] == postings
    calls = len(provider.received)
    assert calls == 2 * totals(url, alice)[0]  # une extraction par offre et par utilisateur

    sql(url, "UPDATE jobs SET state = 'done', finished_at = now()")
    queue(url, alice)
    assert worker.run_one()  # même collecte : rien de nouveau
    assert len(provider.received) == calls  # extraction faite une seule fois par offre
    assert sql(url, "SELECT count(*) FROM scores WHERE user_id = %s", alice)[0][0] == totals(url, alice)[0]


def test_hard_filter_discards_without_calling_the_model(env):  # noqa: F811
    url, (alice, _) = env
    sql(url, "UPDATE search_preferences SET excluded_keywords = ARRAY['Stagiaire'] WHERE user_id = %s", alice)
    worker, provider = make_worker()
    queue(url, alice)
    assert worker.run_one()
    postings, scored = totals(url, alice)
    assert scored == postings
    assert len(provider.received) == postings - 1  # « Stagiaire Data Scientist » écartée sans IA
    zero = sql(url, "SELECT count(*) FROM scores s JOIN job_postings p ON p.id = s.job_posting_id "
                    "WHERE p.title LIKE 'Stagiaire%%' AND s.value = 0 AND s.blocking_reasons <> '[]'")
    assert zero[0][0] == 1


def test_cost_cap_stops_cleanly_then_resumes_without_losing_offers(env, caplog):  # noqa: F811
    url, (alice, _) = env
    worker, provider = make_worker(cap=0.0)
    queue(url, alice)
    caplog.set_level(logging.WARNING)
    assert worker.run_one()
    postings, scored = totals(url, alice)
    assert postings > 0 and scored == 0 and provider.received == []  # rien perdu, rien d'envoyé
    assert "plafond de coût" in caplog.text
    assert sql(url, "SELECT state FROM jobs WHERE user_id = %s", alice) == [("done",)]  # la collecte a réussi

    worker.gateway.daily_cap_eur = 5.0  # le lendemain, ou le PO relève le plafond
    sql(url, "UPDATE jobs SET state = 'done', finished_at = now()")
    queue(url, alice)
    assert worker.run_one()
    assert totals(url, alice) == (postings, postings)


def test_provider_outage_stops_the_pass_and_keeps_offers_pending(env):  # noqa: F811
    url, (alice, _) = env

    def down(request):
        raise ConnectionError("panne simulée")

    worker, provider = make_worker(FakeProvider(reply=down))
    queue(url, alice)
    assert worker.run_one()
    postings, scored = totals(url, alice)
    assert scored == 0 and postings > 3
    assert len(provider.received) == 3  # trois échecs de suite : on arrête au lieu d'insister


def test_invalid_model_answers_still_give_a_low_confidence_score(env):  # noqa: F811
    url, (alice, _) = env
    worker, _ = make_worker(FakeProvider(reply=lambda request: "pas du json"))
    queue(url, alice)
    assert worker.run_one()
    postings, scored = totals(url, alice)
    assert scored == postings
    assert sql(url, "SELECT count(*) FROM analyses")[0][0] == 0


def test_without_ai_configured_offers_wait_for_analysis(env):  # noqa: F811
    url, (alice, _) = env
    worker, _ = make_worker()
    worker.gateway = None
    queue(url, alice)
    assert worker.run_one()
    postings, scored = totals(url, alice)
    assert postings > 0 and scored == 0


def test_a_bug_in_analysis_does_not_fail_the_collection(env, monkeypatch):  # noqa: F811
    url, (alice, _) = env
    worker, _ = make_worker()
    monkeypatch.setattr("app.worker.analyse_user_offers", lambda *a, **k: 1 / 0)
    queue(url, alice)
    assert worker.run_one()
    assert sql(url, "SELECT state FROM jobs WHERE user_id = %s", alice) == [("done",)]
