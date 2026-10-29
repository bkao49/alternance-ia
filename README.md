# Aide à la recherche d'alternance (Data / IA)

Application web qui collecte des offres d'alternance depuis des sources autorisées, les analyse, les score
de façon hybride (règles + embeddings + LLM), prépare un CV et une lettre sans rien inventer, et suit les
candidatures. **Aucun envoi automatique : l'humain décide et clique.**

> Projet en construction. Voir `docs/BACKLOG.md` et `docs/STATUS.md`.

## Lancer en local
Pas à pas, sous Windows (PowerShell). Tout tourne sur votre machine ; rien n'est envoyé nulle part.

1. **Prérequis** : Docker Desktop (démarré) et Node.js 22 pour le Front. Python n'est pas nécessaire.
2. **Préparer la configuration** : `Copy-Item .env.example .env`. Le fichier `.env` est ignoré par git : ne le partagez jamais.
3. **Générer les secrets** : lancez la commande suivante trois fois et collez chaque résultat dans `.env`, respectivement pour `POSTGRES_PASSWORD`, `APP_DB_PASSWORD` et `SECRET_KEY` (aucun espace autour du `=`).
   ```powershell
   docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Laissez `COOKIE_SECURE=false` (développement en http). Un `.env` incomplet donne une erreur en français au démarrage.
4. **Démarrer** : `docker compose up -d --build`. La base démarre, les migrations s'appliquent, puis l'API s'ouvre. Vérifiez avec `docker compose ps` (db et api « healthy ») et `curl.exe http://127.0.0.1:8100/health`.
5. **Créer votre compte** : `docker compose run --rm api python -m app.create_user` (e-mail, puis mot de passe d'au moins 12 caractères, saisi de façon masquée).
6. **Données de démo (facultatif, entièrement fictives)** : mettez `ALLOW_DEMO_DATA=true` dans `.env`, puis `docker compose run --rm api python -m app.seed_demo votre@email`. On peut le rejouer sans créer de doublons.
7. **Ouvrir le Front** : `cd frontend; npm install; npm run dev`, puis http://localhost:5173. Le Front relaie `/api` vers `127.0.0.1:8100`.
8. **Arrêter** : `docker compose down` (les données sont conservées). **Remettre à zéro** : `docker compose down -v` (supprime la base ; les secrets de `.env` ne servent alors qu'à la prochaine création).

Seule l'API est joignable, et seulement depuis votre machine (`127.0.0.1`). La base n'est exposée à aucun port de l'hôte.
Vérifié sous Windows : étapes 4 à 6 et 8 (démarrage, migrations, compte, données de démo, connexion, remise à zéro). Étape 7 : non vérifiée dans cette PR.

## Principes
- Humain dans la boucle · aucun contournement des protections des sites · données personnelles minimisées
- Scoring évalué sur un jeu de référence, pas seulement « à l'intuition d'un LLM »

## Organisation
Développement avec des agents IA spécialisés (voir `agents/`), un Product Owner humain, `main` protégée.

## Licence
À choisir par le PO (MIT recommandé si le dépôt est public).
