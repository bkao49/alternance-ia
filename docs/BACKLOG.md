# Backlog initial (à transformer en issues GitHub)

Légende : [R] rôle · [D] dépendances · [A] critères d'acceptation

## Phase 0 — Cadrage (semaine 1)
- **P0-1 Dépôt et règles de branche** [DevOps] — protection de `main` selon `docs/GITHUB_SETUP.md`. [A] une PR d'essai ne peut pas être fusionnée sans revue du PO.
- **P0-2 CI de base** [DevOps] [D P0-1] — lint, tests (vides), gitleaks, CodeQL. [A] CI verte sur `main`.
- **P0-3 Squelette du dépôt** [Architecte] — dossiers `backend/ frontend/ ai/ collectors/ contracts/ infra/ tests/ docs/`, `.env.example`, `.gitignore`. [A] `docker compose up` démarre un service vide.
- **P0-4 Modèle de menaces v1** [Sécurité] — `docs/security/threat-model.md`. [A] revue par le PO.

## Phase 1 — Socle applicatif (semaines 2–3)
- **P1-1 Modèle de données + migrations** [Backend] [D P0-3] — tables du plan (users, profile_facts, job_postings, analyses, scores, applications, status_definitions, events, tasks, llm_calls…). [A] migrations montées et réversibles ; `user_id` partout.
- **P1-2 Authentification** [Backend, Sécurité] — Argon2, cookies sécurisés, limitation de tentatives. [A] tests d'accès non autorisé.
- **P1-3 Contrat OpenAPI v1** [Architecte] — candidatures, offres, statuts, tâches. [A] validé par le PO.
- **P1-4 CRUD candidatures + statuts personnalisables** [Backend] [D P1-1, P1-3]. [A] 10 statuts par défaut ; historique enregistré.
- **P1-5 Dashboard tableau + Kanban** [Frontend] [D P1-3]. [A] E2E « créer une candidature, changer le statut ».

## Phase 2 — Collecte (semaines 4–5)
- **P2-1 Interface Collector + fixtures** [Connecteurs].
- **P2-2 La Bonne Alternance** [Connecteurs] [D P2-1] — fiche légale `docs/sources/lba.md`. [A] rejouer un scan ne crée aucun doublon.
- **P2-3 France Travail** [Connecteurs] — OAuth2, quotas, plafond de résultats. [A] une erreur de source n'arrête pas les autres.
- **P2-4 Planificateur + file de tâches** [Backend] [D P1-1].
- **P2-5 Détection de blocage et d'annonce expirée** [Connecteurs] — arrêt de la source + notification. [A] test simulant un 403 / défi anti-bot.

## Phase 3 — Scoring (semaines 6–8)
- **P3-1 Passerelle LLM** [IA/Data] — cache, plafond de coût, journalisation.
- **P3-2 Extraction structurée** [IA/Data] [D P3-1] — JSON validé, sans CV.
- **P3-3 Filtres durs et matching hybride** [IA/Data] — règles + embeddings + LLM ambigu.
- **P3-4 Agrégation, confiance, explication** [IA/Data].
- **P3-5 Jeu de référence et rapport d'évaluation** [IA/Data, QA] — le PO note 60–100 offres. [A] Spearman, MAE, précision/rappel, écart-type, ablation, en une commande.

## Phase 4 — CV et lettre (semaines 9–10)
- **P4-1 Profil maître en faits atomiques** [Backend, Frontend].
- **P4-2 Génération CV/lettre avec fact_ids** [IA/Data].
- **P4-3 Contrôle factuel déterministe + vérificateur** [IA/Data]. [A] test : une compétence inventée est rejetée.
- **P4-4 PDF lisible par les ATS** [Backend]. [A] extraction de texte fidèle, une colonne.

## Phase 5 — Validation et exports (semaines 11–12)
- **P5-1 Tâches de validation humaine** [Backend, Frontend] — raison, étapes, téléchargements. [A] impossible de passer « Envoyée » sans confirmation.
- **P5-2 Notifications** (Telegram/e-mail) [Backend].
- **P5-3 Exports CSV/XLSX/PDF** [Backend] — onglets Candidatures, Historique, Offres, Scoring, Entonnoir, Sources. [A] s'ouvre dans Excel et Google Sheets.

## Phase 6 — Mise en ligne (semaines 13–14)
- **P6-1 Docker Compose de production + Caddy** [DevOps].
- **P6-2 Sauvegardes chiffrées + test de restauration** [DevOps]. [A] restauration réussie.
- **P6-3 Monitoring, logs, alertes** [DevOps].
- **P6-4 Audit de sécurité final** [Sécurité] — aucun finding critique.
- **P6-5 README, schéma d'architecture, démo avec données fictives, dossier « pourquoi ces choix »** [Chef de projet].

## Plus tard
ATS publics d'entreprises ciblées, alertes Gmail, aide au remplissage de formulaire (validation humaine), multi-utilisateur.
