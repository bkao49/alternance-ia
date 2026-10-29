# STATUS

Dernière mise à jour : 2026-10-29

## Phase en cours
Phase 2 — Collecte des offres (démarrage par #10, interface des collecteurs)

## Fait
- **Phase 0 (cadrage)** : dépôt public, 31 issues, CI (gitleaks, backend avec vrai PostgreSQL, frontend, contrat OpenAPI, CodeQL), règles de `main` (approbation du PO, dernier envoi relu par quelqu'un d'autre, squash seul), compte bot `prome-theus35`.
- **Phase 1 (socle)** :
  - Schéma PostgreSQL avec isolation par utilisateur (RLS) et clés étrangères composites (#45, #46)
  - Authentification : Argon2, session signée, CSRF, limitation des essais (#48, #49)
  - Candidatures et statuts personnalisables (#50)
  - Lecture des offres et statistiques du tableau de bord (#52)
  - Front : tableau de bord, vue tableau et Kanban, mode démonstration (#53)
  - Stack locale complète avec données de démo (#55)
- **Design** : neuf maquettes dans `docs/design/maquettes/`. Direction retenue : **I** (noir et rouge, blocs arrondis).

## En cours
- Phase 2 : interface commune des collecteurs et fixtures fictives (#10)

## Bloqué / décisions attendues du PO
1. **Nom et logo du projet** : quatre pistes dans la maquette I (Piste, Boussole, Cap, Jalon), choix ouvert.
2. Clés API La Bonne Alternance et France Travail (à fournir avant #11 et #12, jamais dans git)
3. Licence (MIT recommandée)
4. Critères de recherche : zone, dates, types de contrat visés
5. Prénom affiché dans « Bonjour … » (champ à ajouter au profil)

## Décisions actées
- Monolithe modulaire FastAPI + worker ; PostgreSQL + pgvector ; pas de Redis au départ
- Mono-utilisateur avec `user_id` partout
- Aucun envoi automatique de candidature
- **Le projet vise tous les contrats** (stage, alternance, CDD, CDI), pas seulement l'alternance. France Travail couvre tous les contrats ; La Bonne Alternance reste une source parmi d'autres.
- Dépôt public ; commits avec l'adresse noreply GitHub (aucun e-mail personnel publié)
- Compte bot `prome-theus35` (Write, token classic 30 jours) pour les agents ; le PO approuve avec son compte
- Les commits du bot passent par son jeton (`gh`), jamais par les identifiants Git du PO ; le PO ne clique jamais sur « Update branch »
- 3 casquettes d'agents (Constructeur, Relecteur, Chef de projet)
- Hébergement : décision reportée en Phase 6 (VPS par défaut) ; l'API n'est pas exposée publiquement avant #27
- Modèles IA prévus : Claude Haiku 5.5 (analyse, vérification), Claude Sonnet 5.5 en batch (CV, lettre)

## À surveiller
- Renouveler le token du bot vers fin novembre 2026
- #2 : étendre CodeQL à Python et TypeScript maintenant que le code existe
