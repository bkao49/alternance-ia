import datetime as dt
import secrets

import pytest
from sqlalchemy import text

from app import db
from app.ai.matching.filters import (
    Criteria,
    Level,
    MatchPolicy,
    OfferView,
    Status,
    apply_filters,
    load_criteria,
    normalize,
    record_discard,
)
from app.create_user import create_user

TODAY = dt.date(2026, 10, 30)
CRITERIA = Criteria(
    locations=(("Lyon", 30),), remote_accepted=True, contract_types=("apprenticeship", "internship"),
    start_date=dt.date(2027, 9, 1), education_level="bac_plus_4", min_salary_eur=20000,
    excluded_keywords=("senior", "Ingénieur"),
)
OFFER = OfferView(title="Data analyst en alternance", description="SQL et Python.", location="Lyon 3e",
                  contract_type="apprenticeship", start_date=dt.date(2027, 9, 1), education_level="bac_plus_3", salary_eur=24000)


def run(offer=OFFER, criteria=CRITERIA, **kwargs):
    return apply_filters(offer, criteria, today=TODAY, **kwargs)


def status(outcome, name):
    return next(c.status for c in outcome.checks if c.name == name)


def test_matching_offer_passes_everything():
    outcome = run()
    assert not outcome.discarded and outcome.reasons == () and outcome.violated_mandatory == ()
    assert all(c.status is Status.OK for c in outcome.checks)


def test_missing_information_is_unknown_and_never_discards():
    outcome = run(OfferView(title="Data analyst"))
    assert not outcome.discarded
    assert {c.name for c in outcome.checks if c.status is Status.UNKNOWN} == {
        "contract", "location", "start_date", "education", "salary"}


@pytest.mark.parametrize("offer", [
    OfferView(title="Data analyst", expired=True),
    OfferView(title="Data analyst", valid_until=dt.date(2026, 10, 1)),
])
def test_expired_offer_is_discarded_with_reason(offer):
    outcome = run(offer)
    assert outcome.discarded and outcome.reasons == ("L'offre est expirée.",)


def test_valid_until_today_is_not_expired():
    assert not run(OfferView(title="Data analyst", valid_until=TODAY)).discarded


@pytest.mark.parametrize("title, description", [
    ("Data analyst senior", ""), ("Data analyst", "Poste d'INGENIEUR confirmé"), ("Data analyst", "Un SENIOR !"),
])
def test_excluded_keyword_matches_whole_word_without_accent_or_case(title, description):
    outcome = run(OfferView(title=title, description=description))
    assert outcome.discarded and "Mot exclu" in outcome.reasons[0]


def test_excluded_keyword_does_not_match_inside_another_word():
    assert not run(OfferView(title="Data analyst", description="Seniority non requise ; juniors acceptés")).discarded


def test_contract_not_wanted_is_discarded():
    outcome = run(OfferView(title="Data analyst", contract_type="permanent"))
    assert outcome.discarded and "contrat" in outcome.reasons[0]


def test_no_contract_preference_accepts_any_contract():
    assert status(run(OfferView(title="x", contract_type="permanent"), Criteria()), "contract") is Status.OK


def test_location_by_name_ignores_accents_and_case():
    criteria = Criteria(locations=(("Île-de-France", 50),))
    assert status(run(OfferView(title="x", location="ile de france"), criteria), "location") is Status.OK


def test_location_without_geocoder_is_unknown_not_failure():
    assert status(run(OfferView(title="x", location="Brest")), "location") is Status.UNKNOWN


def test_location_radius_with_geocoder():
    coords = {"Lyon": (45.76, 4.84), "Villeurbanne": (45.77, 4.88), "Paris": (48.86, 2.35)}
    near = run(OfferView(title="x", location="Villeurbanne"), geocode=coords.get)
    far = run(OfferView(title="x", location="Paris"), geocode=coords.get)
    assert status(near, "location") is Status.OK
    assert status(far, "location") is Status.FAIL and far.violated_mandatory == ("location",)
    assert not far.discarded  # lieu = critère obligatoire (plafond), pas filtre dur


def test_remote_offer_passes_location_only_if_remote_accepted():
    offer = OfferView(title="x", location="Brest", remote=True)
    assert status(run(offer), "location") is Status.OK
    assert status(run(offer, Criteria(locations=(("Lyon", 30),))), "location") is Status.UNKNOWN


def test_start_date_tolerance():
    early = run(OfferView(title="x", start_date=dt.date(2027, 6, 1)))
    assert status(early, "start_date") is Status.FAIL and not early.discarded
    assert status(run(OfferView(title="x", start_date=dt.date(2027, 8, 15))), "start_date") is Status.OK


def test_education_too_high_is_mandatory_violation():
    outcome = run(OfferView(title="x", education_level="bac_plus_5"))
    assert outcome.violated_mandatory == ("education",) and not outcome.discarded


def test_salary_below_minimum_fails_but_is_only_desired():
    outcome = run(OfferView(title="x", salary_eur=15000))
    assert status(outcome, "salary") is Status.FAIL and not outcome.discarded and outcome.violated_mandatory == ()


def test_policy_can_promote_a_criterion_to_hard():
    policy = MatchPolicy(levels={"salary": Level.HARD})
    outcome = run(OfferView(title="x", salary_eur=15000), policy=policy)
    assert outcome.discarded and "Salaire" in outcome.reasons[0]


def test_all_hard_reasons_are_kept():
    outcome = run(OfferView(title="Senior", expired=True, contract_type="permanent"))
    assert len(outcome.reasons) == 3


@pytest.fixture
def user(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(32))
    yield create_user("alice@example.test", "mot-de-passe-de-test-123")
    db._engine(migrated_db).dispose()
    db._engine.cache_clear()


def test_load_criteria_and_record_discard(user):
    with db.user_scope(user) as conn:
        assert load_criteria(conn) is None
        conn.execute(text(
            "INSERT INTO search_preferences (user_id, locations, contract_types, excluded_keywords, education_level) "
            "VALUES (:uid, CAST('[{\"label\": \"Lyon\", \"radius_km\": 25}]' AS jsonb), "
            "ARRAY['internship'], ARRAY['senior'], 'bac_plus_5')"), {"uid": user})
        criteria = load_criteria(conn)
        assert criteria == Criteria(locations=(("Lyon", 25),), contract_types=("internship",),
                                    excluded_keywords=("senior",), education_level="bac_plus_5")
        posting = conn.execute(text(
            "INSERT INTO job_postings (user_id, source, external_id, url, title, company, description_text, "
            "content_hash) VALUES (:uid, 's', '1', 'https://x.test/1', 'Senior dev', 'Acme', 'texte', 'h') "
            "RETURNING id"), {"uid": user}).scalar_one()
        outcome = apply_filters(OfferView(title="Senior dev"), criteria, today=TODAY)
        record_discard(conn, user, str(posting), outcome)
        row = conn.execute(text("SELECT value, confidence, blocking_reasons FROM scores")).mappings().one()
    assert float(row["value"]) == 0 and row["confidence"] == "high"
    assert row["blocking_reasons"] == ["Mot exclu présent dans l'offre : senior."]


def test_normalize():
    assert normalize("  Île-de-France / Été ") == "ile de france ete"
