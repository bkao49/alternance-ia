# Rôle : IA / Data

**Périmètre** : `ai/`.
**Interdit** : appeler un LLM hors `ai/gateway` ; envoyer des données personnelles non pseudonymisées ; produire un score uniquement par LLM.

## Tâches
- Passerelle LLM : interface `LLMProvider`, adaptateurs interchangeables, cache par hash, plafond de coût mensuel, table `llm_calls`.
- Extraction structurée des annonces (JSON validé Pydantic, **sans voir le CV**).
- Filtres durs (code) puis matching par exigence : règles + alias, embeddings multilingues locaux, LLM seulement pour les cas ambigus, avec `fact_ids` obligatoires.
- Agrégation déterministe : `score = 5 × Σ(wᵢ·sᵢ) / Σw`, niveau de confiance, plafond si exigences surtout estimées.
- Génération CV/lettre à partir de faits atomiques ; contrôle factuel déterministe + passe « vérificateur » ; sortie JSON avec `fact_ids`.
- Jeu de référence (offres notées à la main) et rapport : Spearman, erreur absolue moyenne, précision/rappel de « à postuler », écart-type sur 3 runs, ablation règles / embeddings / LLM / hybride.

## Terminé quand
Le rapport d'évaluation est reproductible en une commande ; un test injecte une compétence inventée et le contrôle la rejette.
