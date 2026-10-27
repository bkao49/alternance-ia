# STATUS

Dernière mise à jour : 2026-10-27

## Phase en cours
Phase 0 — Cadrage

## Fait
- Plan de conception validé (voir le doc partagé dans Claude)

## En cours
-

## Bloqué / décisions attendues du PO
1. Dépôt public ou privé ?
2. Compte bot GitHub créé ?
3. Clés API La Bonne Alternance et France Travail (à fournir en phase 2, jamais dans git)
4. Zone de recherche, dates de début, rythme d'alternance, contrat visé

## Décisions actées
- Monolithe modulaire FastAPI + worker ; PostgreSQL + pgvector ; pas de Redis au départ
- Mono-utilisateur avec `user_id` partout
- Aucun envoi automatique de candidature
