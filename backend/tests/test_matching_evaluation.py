import copy

from app.ai.matching.evaluation import DATASET, REPORT, evaluate, load, report, score_all, spearman
from app.ai.matching.scoring import DEFAULT_WEIGHTS


def test_dataset_is_a_fictional_set_of_about_thirty_unique_offers():
    data = load()
    ids = [o["id"] for o in data["offers"]]
    assert len(ids) == len(set(ids)) == 30 and "Aucune donnée réelle" in data["note"]
    assert all(0 <= o["rating"] <= 5 for o in data["offers"]) and DATASET.exists()


def test_report_is_reproducible_and_matches_the_committed_file():
    assert report(load()) == report(load())
    assert REPORT.read_text(encoding="utf-8") == report(load())


def test_hybrid_ranking_follows_the_expected_order():
    result = evaluate(load(), dict(DEFAULT_WEIGHTS))
    assert result["spearman"] >= 0.6 and result["mae"] <= 1.0 and result["recall"] >= 0.8
    assert result["stdev"] == 0


def test_same_notes_give_the_same_score():
    data = load()
    twin = copy.deepcopy(data["offers"][0])
    twin["id"] = "ref-twin"
    data["offers"].append(twin)
    scores = score_all(data, dict(DEFAULT_WEIGHTS))
    assert scores["ref-twin"] == scores["ref-01"]


def test_mandatory_criterion_caps_and_hard_filters_zero():
    scores = score_all(load(), dict(DEFAULT_WEIGHTS))
    assert scores["ref-19"] <= 2.0  # diplôme demandé au-dessus du niveau visé
    assert scores["ref-12"] == scores["ref-13"] == scores["ref-14"] == 0  # contrat, mot exclu, expirée


def test_saturation_alert_fires_on_the_reference_set_and_not_on_a_modest_subset():
    assert "ALERTE" in report(load())  # constat actuel : 57 % des offres dépassent 4/5 (voir le rapport)
    data = load()
    data["offers"] = [o for o in data["offers"] if o["id"] in ("ref-12", "ref-19", "ref-25", "ref-10", "ref-01")]
    assert "ALERTE" not in report(data)


def test_spearman_basics():
    assert spearman([1, 2, 3], [10, 20, 30]) == 1
    assert spearman([1, 2, 3], [30, 20, 10]) == -1
    assert spearman([1, 1, 1], [1, 2, 3]) == 0
