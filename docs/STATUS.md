# STATUS

Dernière mise à jour : 2026-10-27

## Phase en cours
Phase 0 — Cadrage

## Fait
- Plan de conception validé (voir le doc partagé dans Claude)

## Fait (Phase 0, session 1)
- Dépôt local initialisé ; dossiers du squelette créés avec un README d'une ligne
- CI : actions épinglées par SHA de commit ; archive gitleaks vérifiée par SHA-256
- 31 issues P0-1 → P6-5 rédigées dans `docs/issues/` + script `docs/issues/create-issues.sh`

## En cours
- Publication sur GitHub (bloquée : dépôt distant non créé, `gh` non installé)

## Bloqué / décisions attendues du PO
1. Dépôt public ou privé ?
2. Compte bot GitHub créé ?
3. Clés API La Bonne Alternance et France Travail (à fournir en phase 2, jamais dans git)
4. Installer GitHub CLI, créer le dépôt distant, puis lancer `docs/issues/create-issues.sh`
5. Zone de recherche, dates de début, rythme d'alternance, contrat visé

## Décisions actées
- Monolithe modulaire FastAPI + worker ; PostgreSQL + pgvector ; pas de Redis au départ
- Mono-utilisateur avec `user_id` partout
- Aucun envoi automatique de candidature
