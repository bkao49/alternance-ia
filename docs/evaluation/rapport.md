# Rapport d'évaluation du score

Jeu de référence : 30 offres et un profil entièrement fictifs (`backend/tests/fixtures/reference/offres.json`). Notes « attendues » écrites à la main. Exécutions : 3, offres mélangées avec une graine fixe (le score ne doit pas dépendre de l'ordre). Régénérer : `cd backend && python -m app.ai.matching.evaluation`.

« À postuler » = score ≥ 3.5.

| Variante | Spearman | Erreur absolue moyenne | Précision | Rappel | Écart-type (3 exécutions) |
|---|---|---|---|---|---|
| règles seules | 0.68 | 0.99 | 0.62 | 1.00 | 0.00 |
| compétences seules | 0.77 | 0.78 | 0.82 | 0.69 | 0.00 |
| hybride (règles + compétences) | 0.75 | 0.71 | 0.65 | 1.00 | 0.00 |
| embeddings locaux | non disponible | | | | |
| LLM pour les cas ambigus | non disponible | | | | |

Part des offres au-dessus de 4/5 : 57% **ALERTE : plus de 40 % des offres dépassent 4/5, le score est trop généreux.**
