import datetime as dt
import json
import secrets

import pytest
from sqlalchemy import text

from app import db
from app.ai.matching.scoring import (
    DEFAULT_WEIGHTS,
    MANDATORY_CAP,
    Component,
    ScoringError,
    aggregate,
    check_fact_ids,
    score_offer,
    weights_from_env,
)
from app.create_user import create_user

W = DEFAULT_WEIGHTS


def comps(**scores):
    return [Component(key, scores.get(key), "note") for key in W]


def all_known(value):
    return comps(**{key: value for key in W})


def test_default_weights_are_30_20_15_10_5_10_10():
    assert list(W.values()) == [30, 20, 15, 10, 5, 10, 10]


def test_perfect_and_null_notes():
    assert aggregate(all_known(1.0), W).value == 5.0
    assert aggregate(all_known(0.0), W).value == 0.0
    assert aggregate(all_known(1.0), W).confidence == "high"


def test_score_is_weighted_average_on_a_0_to_5_scale():
    result = aggregate(comps(**{**{k: 0.0 for k in W}, "title": 1.0}), W)
    assert result.value == 1.5  # 5 x 30 / 100


def test_unknown_component_leaves_the_calculation_without_penalty():
    full = comps(**{k: 0.8 for k in W})
    partial = comps(**{k: 0.8 for k in W if k != "salary"})
    assert aggregate(full, W).value == aggregate(partial, W).value == 4.0
    assert aggregate(partial, W).coverage == 0.9


def test_low_coverage_pulls_the_score_towards_the_mean_never_perfect():
    result = aggregate(comps(title=1.0), W)  # couverture 0,3 : 2,5 + 2,5 x 0,3 / 0,5
    assert result.coverage == 0.3 and result.value == 4.0 and result.confidence == "low"
    assert aggregate(comps(title=0.0), W).value == 1.0
    assert aggregate(comps(), W).value == 2.5  # rien de connu : la moyenne, confiance faible


def test_coverage_at_half_is_not_shrunk():
    result = aggregate(comps(title=1.0, skills=1.0), W)  # couverture 0,5
    assert result.value == 5.0 and result.confidence == "medium"


def test_violated_mandatory_criterion_caps_the_score():
    result = aggregate(all_known(1.0), W, ["location"], ["Lieu hors de la zone voulue : Paris."])
    assert result.value == MANDATORY_CAP and result.blocking_reasons == ["Lieu hors de la zone voulue : Paris."]
    assert "plafonné" in result.explanation
    assert aggregate(all_known(0.2), W, ["location"]).value == 1.0  # déjà sous le plafond : inchangé


def test_same_notes_give_the_same_score_whatever_the_order():
    forward = comps(title=0.7, skills=0.3, salary=1.0)
    a, b = aggregate(forward, W), aggregate(list(reversed(forward)), W)
    assert (a.value, a.coverage, a.confidence, a.explanation) == (b.value, b.coverage, b.confidence, b.explanation)
    assert aggregate(forward, W) == aggregate(forward, W)


def test_zero_weight_removes_a_component():
    weights = {**W, "salary": 0}
    assert aggregate(comps(**{**{k: 0.5 for k in W}, "salary": 1.0}), weights).value == 2.5


def test_criteria_follow_the_stored_shape():
    criterion = aggregate(all_known(0.5), W).criteria[0]
    assert criterion["key"] == "title" and criterion["weight"] == 30 and criterion["score"] == 0.5


def test_unknown_fact_id_is_rejected():
    check_fact_ids([Component("skills", 1.0, "x", ("f1",))], {"f1"})
    with pytest.raises(ScoringError):
        check_fact_ids([Component("skills", 1.0, "x", ("f1", "inventé"))], {"f1"})


def test_weights_from_env(monkeypatch):
    monkeypatch.setenv("MATCH_WEIGHTS", '{"title": 40, "salary": 0}')
    assert weights_from_env()["title"] == 40 and weights_from_env()["skills"] == 20
    for bad in ('{"titre": 1}', '{"title": -1}', "[1]", "pas du json", '{"title": true}', '{"title": NaN}'):
        monkeypatch.setenv("MATCH_WEIGHTS", bad)
        with pytest.raises(RuntimeError):
            weights_from_env()
    monkeypatch.setenv("MATCH_WEIGHTS", json.dumps({k: 0 for k in W}))
    with pytest.raises(RuntimeError):
        weights_from_env()


@pytest.fixture
def user(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(32))
    yield create_user("alice@example.test", "mot-de-passe-de-test-123")
    db._engine(migrated_db).dispose()
    db._engine.cache_clear()


EXTRACTION = {"skills": ["Python", "SQL", "Spark"], "education_level": "bac_plus_4", "duration_months": 12,
              "contract_type": "apprenticeship", "location": "Lyon", "remote": None, "salary_eur_year": None,
              "start_date": None, "summary": "Alternance data."}


def setup_user(conn, uid, excluded=()):
    conn.execute(text(
        "INSERT INTO search_preferences (user_id, keywords, locations, contract_types, education_level, "
        "excluded_keywords) VALUES (:uid, ARRAY['data'], CAST(:loc AS jsonb), ARRAY['apprenticeship'], "
        "'bac_plus_5', :excluded)"),
        {"uid": uid, "loc": json.dumps([{"label": "Lyon", "radius_km": 30}]), "excluded": list(excluded)})
    rows = [("experience", "Stage data chez Acme Fictive", ["Python", "SQL"]), ("skill", "Notions de R", ["R"])]
    return {kind: str(conn.execute(text(
        "INSERT INTO profile_facts (user_id, kind, text, technologies) VALUES (:uid, :k, :t, :tech) RETURNING id"),
        {"uid": uid, "k": kind, "t": t, "tech": tech}).scalar_one()) for kind, t, tech in rows}


def add_posting(conn, uid, title="Data analyst alternance", location="Lyon", extraction=EXTRACTION):
    posting = conn.execute(text(
        "INSERT INTO job_postings (user_id, source, external_id, url, title, company, location, description_text, "
        "content_hash) VALUES (:uid, 's', :e, 'https://x.test/1', :t, 'Acme', :l, 'texte', 'h') RETURNING id"),
        {"uid": uid, "e": title, "t": title, "l": location}).scalar_one()
    if extraction:
        conn.execute(text("INSERT INTO analyses (user_id, job_posting_id, extraction, prompt_version) "
                          "VALUES (:uid, :p, CAST(:x AS jsonb), 'extraction-v1')"),
                     {"uid": uid, "p": posting, "x": json.dumps(extraction)})
    return str(posting)


def test_score_offer_writes_score_with_explanation_citing_profile_facts(user):
    with db.user_scope(user) as conn:
        facts = setup_user(conn, user)
        posting = add_posting(conn, user)
        result = score_offer(conn, user, posting, today=dt.date(2026, 10, 30))
        row = conn.execute(text("SELECT value, confidence, explanation, criteria, analysis_id FROM scores")
                           ).mappings().one()
    assert float(row["value"]) == result.value and 0 < result.value <= 5
    by_key = {c["key"]: c for c in row["criteria"]}
    assert by_key["skills"]["score"] == 0.67 and by_key["skills"]["fact_ids"] == [facts["experience"]]
    assert by_key["title"]["score"] == 1.0 and not by_key["salary"]["known"]
    assert all(set(c["fact_ids"]) <= set(facts.values()) for c in row["criteria"])
    assert row["analysis_id"] is not None and "fait(s) de votre profil" in row["explanation"]
    assert row["confidence"] in ("medium", "high")


def test_hard_filter_writes_a_zero_with_reasons_and_no_calculation(user):
    with db.user_scope(user) as conn:
        setup_user(conn, user, excluded=["alternance"])
        result = score_offer(conn, user, add_posting(conn, user))
        row = conn.execute(text("SELECT value, blocking_reasons FROM scores")).mappings().one()
    assert result.value == 0 and float(row["value"]) == 0 and "Mot exclu" in row["blocking_reasons"][0]


def test_offer_without_analysis_is_scored_prudently(user):
    with db.user_scope(user) as conn:
        setup_user(conn, user)
        result = score_offer(conn, user, add_posting(conn, user, extraction=None))
    assert result.confidence == "low" and result.coverage == 0.4 and result.value < 5  # titre et lieu seuls : tirée vers 2,5


def test_explanation_announces_the_cap_only_when_it_changed_the_score():
    low = aggregate(all_known(0.2), W, ["location"])
    assert "plafonné" not in low.explanation and aggregate(all_known(1.0), W, ["location"]).value == 2.0


def test_partial_weights_fall_back_to_defaults():
    assert aggregate(all_known(1.0), {"title": 50}).value == 5.0


def test_missing_profile_match_is_a_zero_not_unknown(user):
    with db.user_scope(user) as conn:
        setup_user(conn, user)
        extra = {**EXTRACTION, "skills": ["Cobol"]}
        result = score_offer(conn, user, add_posting(conn, user, extraction=extra))
    skills = next(c for c in result.criteria if c["key"] == "skills")
    assert skills["known"] and skills["score"] == 0 and skills["fact_ids"] == []


def test_education_above_candidate_level_caps_end_to_end(user):
    with db.user_scope(user) as conn:
        setup_user(conn, user)
        extra = {**EXTRACTION, "education_level": "doctorate"}
        result = score_offer(conn, user, add_posting(conn, user, extraction=extra))
    assert result.value <= 2.0 and result.blocking_reasons


def test_salary_below_minimum_scores_zero_on_that_component(user):
    with db.user_scope(user) as conn:
        setup_user(conn, user)
        conn.execute(text("UPDATE search_preferences SET min_salary_eur = 30000"))
        extra = {**EXTRACTION, "salary_eur_year": 15000}
        result = score_offer(conn, user, add_posting(conn, user, extraction=extra))
    salary = next(c for c in result.criteria if c["key"] == "salary")
    assert salary["known"] and salary["score"] == 0


def test_expired_offer_is_written_as_discarded(user):
    with db.user_scope(user) as conn:
        setup_user(conn, user)
        posting = add_posting(conn, user)
        conn.execute(text("UPDATE job_postings SET expired = true"))
        assert score_offer(conn, user, posting).blocking_reasons == ["L'offre est expirée."]


def test_scoring_twice_keeps_the_latest_score_first(user):
    with db.user_scope(user) as conn:
        setup_user(conn, user)
        posting = add_posting(conn, user)
        score_offer(conn, user, posting)
        conn.execute(text("UPDATE search_preferences SET excluded_keywords = ARRAY['alternance']"))
        score_offer(conn, user, posting)
        latest = conn.execute(text(
            "SELECT value FROM scores ORDER BY created_at DESC, id LIMIT 1")).scalar_one()
    assert float(latest) == 0


def test_other_users_posting_and_facts_are_invisible(user):
    other = create_user("bob@example.test", "mot-de-passe-de-test-123")
    with db.user_scope(user) as conn:
        setup_user(conn, user)
        posting = add_posting(conn, user)
    with db.user_scope(other) as conn:
        assert score_offer(conn, other, posting) is None


def test_no_criteria_means_no_score(user):
    with db.user_scope(user) as conn:
        assert score_offer(conn, user, add_posting(conn, user)) is None
        assert conn.execute(text("SELECT count(*) FROM scores")).scalar_one() == 0
