# ADR 0006 : extraction structurée des annonces

Statut : proposé (2026-10-30)

## Décision
- Extraction dans `backend/app/ai/matching/extraction.py`, par `LLMGateway` uniquement, `kind=JOB_POSTING`, sans aucun champ du profil ni des critères.
- Schéma Pydantic strict (`extra="forbid"`), versionné par `PROMPT_VERSION` ; une réponse invalide donne une nouvelle tentative (consigne différente), puis `ExtractionError`.
- Cache : la table `analyses` (empreinte du titre, du lieu et du texte, dans `extraction.content_hash`). Le cache de la passerelle est coupé pour ces appels (`use_cache=False`) : il rejouerait sinon une réponse invalide. Changer de modèle sans changer `PROMPT_VERSION` ne relance pas l'analyse.
- Annonce tronquée à 30 000 caractères avant l'appel. Le lieu de la colonne `job_postings.location` prime sur celui du modèle ; un télétravail « partiel » est « inconnu » pour les filtres.

## Limite connue
« Une offre analysée une fois pour tous les utilisateurs » exige une table commune hors RLS (empreinte → extraction) : migration à décider par le PO. Aujourd'hui : une analyse par utilisateur et par offre.

## Conséquences
Les champs libres extraits (résumé, lieu, compétences) restent des données non fiables : à repasser par `delimit` s'ils sont remis dans un prompt.
