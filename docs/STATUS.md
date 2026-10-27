# STATUS

Dernière mise à jour : 2026-10-27

## Phase en cours
Phase 0 — Cadrage

## Fait
- Plan de conception validé (voir le doc partagé dans Claude)

## Fait (Phase 0, session 1)
- Dépôt local initialisé ; dossiers du squelette créés avec un README d'une ligne
- CI : actions épinglées par SHA de commit ; archive gitleaks vérifiée par SHA-256
- Dépôt public https://github.com/bkao49/alternance-ia créé
- 31 issues P0-1 → P6-5 publiées (#1 à #31), étiquettes `role:*`, `phase:*`, `contract` ; texte source dans `docs/issues/`

## En cours
- PR de Phase 0 (cadrage) en attente de relecture du PO

## Bloqué / décisions attendues du PO
1. Protection de `main` à configurer (issue #1, voir `docs/GITHUB_SETUP.md`)
2. Compte bot GitHub créé ?
3. Clés API La Bonne Alternance et France Travail (à fournir en phase 2, jamais dans git)
4. Licence (MIT recommandée)
5. Zone de recherche, dates de début, rythme d'alternance, contrat visé

## Décisions actées
- Monolithe modulaire FastAPI + worker ; PostgreSQL + pgvector ; pas de Redis au départ
- Mono-utilisateur avec `user_id` partout
- Aucun envoi automatique de candidature
- Dépôt public ; commits avec l'adresse noreply GitHub (aucun e-mail personnel publié)
