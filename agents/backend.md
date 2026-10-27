# Rôle : Backend

**Périmètre** : `backend/`, migrations de base de données.
**Interdit** : modifier `frontend/`, `contracts/` sans PR `contract`, appeler un LLM hors passerelle.

## Tâches
- FastAPI, API REST conforme à `contracts/openapi.yaml`.
- Modèle PostgreSQL (SQLAlchemy 2 + Alembic), `user_id` sur toutes les tables, Row Level Security.
- Authentification mono-utilisateur sécurisée (Argon2, cookie HttpOnly/Secure/SameSite).
- Gestion des offres, candidatures, statuts personnalisables, historique d'événements.
- Tâches de validation humaine ; génération et stockage de documents ; exports CSV/XLSX/PDF.
- File de tâches adossée à PostgreSQL (planification des scans).

## Terminé quand
Tests pytest verts, migrations réversibles, aucun statut « Envoyée » possible sans confirmation explicite (testé).
