"""Évaluation du score sur un jeu de référence (offres et profil fictifs, notes humaines).

Une commande produit le rapport : `python -m app.ai.matching.evaluation`. Tout est déterministe (aucun
tirage hors du mélange à graine fixe, aucun appel réseau, extractions déjà écrites dans le jeu) : trois exécutions donnent des écarts
types nuls et le rapport est identique à chaque fois. Les variantes « embeddings » et « LLM » de l'ablation
n'existent pas encore : elles sont listées comme non disponibles.
"""

import datetime as dt
import json
import random
import statistics
import sys
from pathlib import Path

from app.ai.matching.extraction import Extraction, to_offer_view
from app.ai.matching.filters import Criteria, apply_filters
from app.ai.matching.scoring import DEFAULT_WEIGHTS, aggregate, build_components

ROOT = Path(__file__).resolve().parents[4]
DATASET = ROOT / "backend" / "tests" / "fixtures" / "reference" / "offres.json"
REPORT = ROOT / "docs" / "evaluation" / "rapport.md"
APPLY_THRESHOLD = 3.5  # « à postuler » (identique à RELEVANT_SCORE du tableau de bord)
SATURATION_SHARE = 0.4  # alerte si plus de 40 % des offres dépassent 4/5
RUNS = 3
SEED = 20261030  # graine : l'ordre des offres change à chaque exécution, le score ne doit pas en dépendre
EVAL_DATE = dt.date(2026, 10, 30)  # date fixe : le rapport ne dépend pas du jour d'exécution
VARIANTS = {
    "règles seules": {"skills": 0, "experience": 0},
    "compétences seules": {"title": 0, "location_remote": 0, "contract": 0, "salary": 0, "degree": 0},
    "hybride (règles + compétences)": {},
}
UNAVAILABLE = ("embeddings locaux", "LLM pour les cas ambigus")


def load(path: Path = DATASET) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def score_all(data: dict, weights: dict[str, float], seed: int | None = None) -> dict[str, float]:
    c = data["criteria"]
    criteria = Criteria(
        locations=tuple((loc["label"], loc["radius_km"]) for loc in c["locations"]),
        remote_accepted=c["remote_accepted"], contract_types=tuple(c["contract_types"]),
        education_level=c["education_level"], min_salary_eur=c["min_salary_eur"],
        excluded_keywords=tuple(c["excluded_keywords"]))
    scores = {}
    offers = list(data["offers"])
    if seed is not None:
        random.Random(seed).shuffle(offers)
    for offer in offers:
        extraction = Extraction.model_validate(offer["extraction"], strict=False)
        view = to_offer_view({"title": offer["title"], "description_text": offer["description"],
                              "location": offer["location"], "expired": offer["expired"]}, extraction)
        outcome = apply_filters(view, criteria, today=EVAL_DATE)
        if outcome.discarded:
            scores[offer["id"]] = 0.0
            continue
        components = build_components(offer["title"], extraction, criteria, c["keywords"], data["facts"], outcome)
        reasons = [k.reason for k in outcome.checks if k.name in outcome.violated_mandatory]
        scores[offer["id"]] = aggregate(components, weights, outcome.violated_mandatory, reasons).value
    return scores


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1  # rang moyen des ex æquo
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    spread = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return cov / spread if spread else 0.0


def evaluate(data: dict, weights: dict[str, float]) -> dict:
    runs = [score_all(data, weights, SEED + n) for n in range(RUNS)]
    ids = [o["id"] for o in data["offers"]]
    expected = [float(o["rating"]) for o in data["offers"]]
    computed = [runs[0][i] for i in ids]
    apply_true = [r >= APPLY_THRESHOLD for r in expected]
    apply_pred = [s >= APPLY_THRESHOLD for s in computed]
    true_pos = sum(t and p for t, p in zip(apply_true, apply_pred, strict=True))
    return {
        "spearman": spearman(computed, expected),
        "mae": statistics.fmean(abs(s - r) for s, r in zip(computed, expected, strict=True)),
        "precision": true_pos / sum(apply_pred) if any(apply_pred) else 0.0,
        "recall": true_pos / sum(apply_true) if any(apply_true) else 0.0,
        "stdev": max(statistics.pstdev([run[i] for run in runs]) for i in ids),
        "above_4": sum(s > 4 for s in computed) / len(computed),
    }


def report(data: dict) -> str:
    rows = {}
    for name, off in VARIANTS.items():
        rows[name] = evaluate(data, {**DEFAULT_WEIGHTS, **off})
    main = rows["hybride (règles + compétences)"]
    lines = [
        "# Rapport d'évaluation du score", "",
        (f"Jeu de référence : {len(data['offers'])} offres et un profil entièrement fictifs "
         "(`backend/tests/fixtures/reference/offres.json`). Notes « attendues » écrites à la main. "
         f"Exécutions : {RUNS}, offres mélangées avec une graine fixe (le score ne doit pas dépendre de l'ordre). "
         "Régénérer : `cd backend && python -m app.ai.matching.evaluation`."), "",
        f"« À postuler » = score ≥ {APPLY_THRESHOLD}.", "",
        "| Variante | Spearman | Erreur absolue moyenne | Précision | Rappel | Écart-type (3 exécutions) |",
        "|---|---|---|---|---|---|",
    ]
    for name, r in rows.items():
        lines.append(f"| {name} | {r['spearman']:.2f} | {r['mae']:.2f} | {r['precision']:.2f} | "
                     f"{r['recall']:.2f} | {r['stdev']:.2f} |")
    for name in UNAVAILABLE:
        lines.append(f"| {name} | non disponible | | | | |")
    lines += ["", f"Part des offres au-dessus de 4/5 : {main['above_4']:.0%} "
              + ("**ALERTE : plus de 40 % des offres dépassent 4/5, le score est trop généreux.**"
                 if main["above_4"] > SATURATION_SHARE else "(sous le seuil d'alerte de 40 %).")]
    return "\n".join(lines) + "\n"


def main() -> None:
    text = report(load())
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
