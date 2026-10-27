# Rôle : Frontend

**Périmètre** : `frontend/`.
**Interdit** : modifier le backend ou les contrats ; stocker des secrets côté client.

## Tâches
- React + Vite + TypeScript ; client d'API généré depuis `contracts/openapi.yaml`.
- Pages : dashboard (compteurs, entonnoir, taux de conversion), offres, détail d'offre et score, candidatures (tableau + Kanban), tâches de validation, profil/CV maître, documents, sources et scans, paramètres, journal, exports.
- États de chargement, vide et erreur sur chaque écran ; accessibilité de base (clavier, contrastes).
- Tests Vitest et un parcours Playwright.

## Terminé quand
Lint, types et tests verts ; démo avec données fictives ; aucun texte d'annonce rendu en HTML non échappé.
