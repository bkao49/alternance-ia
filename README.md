# Aide à la recherche d'alternance (Data / IA)

Application web qui collecte des offres d'alternance depuis des sources autorisées, les analyse, les score
de façon hybride (règles + embeddings + LLM), prépare un CV et une lettre sans rien inventer, et suit les
candidatures. **Aucun envoi automatique : l'humain décide et clique.**

> Projet en construction. Voir `docs/BACKLOG.md` et `docs/STATUS.md`.

## Principes
- Humain dans la boucle · aucun contournement des protections des sites · données personnelles minimisées
- Scoring évalué sur un jeu de référence, pas seulement « à l'intuition d'un LLM »

## Organisation
Développement avec des agents IA spécialisés (voir `agents/`), un Product Owner humain, `main` protégée.

## Licence
À choisir par le PO (MIT recommandé si le dépôt est public).
