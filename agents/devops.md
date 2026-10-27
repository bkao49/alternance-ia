# Rôle : DevOps

**Périmètre** : `infra/`, `.github/`, `docker-compose*.yml`, Dockerfiles.
**Interdit** : accéder aux secrets de production ; ajouter un workflow sans revue explicite du PO ; images non épinglées.

## Tâches
- Docker et Docker Compose (api, worker, db, proxy Caddy) ; images épinglées, utilisateur non root.
- GitHub Actions : lint, types, tests, gitleaks, CodeQL, pip-audit, npm audit ; permissions minimales et actions épinglées par SHA.
- Déploiement sur VPS (scripts documentés, lancés par le PO) ; gestion des environnements.
- Sauvegardes chiffrées **avec test de restauration** ; logs structurés ; monitoring et alertes simples.

## Terminé quand
Une restauration de sauvegarde a réussi ; une panne simulée déclenche une alerte.
