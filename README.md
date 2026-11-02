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

## Premier lancement avec de vraies offres
À faire après « Lancer en local » (étapes 1 à 5). Les clés vont dans `.env`, jamais dans git, jamais dans un message. Aucune n'est obligatoire pour démarrer : sans clé, la source ou l'IA concernée reste simplement inactive, et la commande de contrôle (étape 5) vous dit ce qui manque.

1. **Clé d'IA (Claude)** : créez un compte sur console.anthropic.com, ajoutez quelques euros de crédit (Billing), puis « API keys » > « Create key ». Dans `.env` : `ANTHROPIC_API_KEY=` suivie de la clé, et `LLM_PROVIDER=anthropic`. Les modèles sont déjà choisis (Haiku pour lire les annonces, Sonnet pour les CV). Le plafond de dépense par jour est `LLM_DAILY_CAP_EUR` (0,50 € par défaut) : au plafond, le bot s'arrête proprement et reprend le lendemain.
2. **Adzuna** (offres de toute la France) : inscrivez-vous gratuitement sur developer.adzuna.com, copiez l'« Application ID » et l'« Application Key » dans `ADZUNA_APP_ID` et `ADZUNA_APP_KEY`.
3. **La Bonne Alternance** (offres en alternance) : créez un compte sur francetravail.io, demandez l'accès à l'API « La Bonne Alternance » (ou « Recherche d'opportunités d'emploi en alternance »), puis copiez le jeton dans `LBA_API_TOKEN`. Le délai d'obtention est de quelques jours.
4. **Appliquer les changements** : `docker compose up -d --build` (relit `.env` et redémarre l'API et le robot).
5. **Contrôler** :
   ```powershell
   docker compose run --rm doctor
   ```
   Chaque ligne commence par `[OK]`, `[A FAIRE]` ou `[ERREUR]` et explique quoi faire. La commande vérifie que la base répond, que les migrations sont à jour, quelles clés sont renseignées (oui ou non, jamais leur valeur) et qu'un appel de test à chaque source configurée répond. Elle ne dépense aucun jeton d'IA.
6. **Saisir vos critères** dans l'application (« Mes critères » : mots-clés, lieu, contrats) et valider quelques faits dans « Mon profil » : sans critères, le robot ne cherche rien à votre place.
7. **Voir travailler le robot** : `docker compose logs -f worker` (Ctrl+C pour quitter). Après chaque collecte, les nouvelles offres sont filtrées, lues par l'IA une seule fois, puis notées ; l'accueil (« Le bot ») indique combien attendent encore leur analyse.

Si `doctor` signale un problème de base ou de migrations : `docker compose up -d --build`, puis `docker compose run --rm migrate`.

## Principes
- Humain dans la boucle · aucun contournement des protections des sites · données personnelles minimisées
- Scoring évalué sur un jeu de référence, pas seulement « à l'intuition d'un LLM »

## Organisation
Développement avec des agents IA spécialisés (voir `agents/`), un Product Owner humain, `main` protégée.

## Licence
À choisir par le PO (MIT recommandé si le dépôt est public).
