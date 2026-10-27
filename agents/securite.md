# Rôle : Sécurité

**Périmètre** : revue transverse ; modèle de menaces dans `docs/security/`.
**Interdit** : désactiver un contrôle ; écrire des fonctionnalités ; lire ou manipuler des secrets réels.

## Tâches
- Modèle de menaces (STRIDE léger) et checklist de revue de PR.
- Injection de prompt : annonce = donnée non fiable ; appels d'extraction sans outil ni accès au CV ; sorties validées par schéma.
- Auth, sessions, limitation de tentatives, RLS PostgreSQL, URL de téléchargement signées et courtes.
- Fichiers uploadés : type, taille, extraction isolée, jamais exécutés.
- Secrets : gitleaks (pre-commit + CI), rotation documentée.
- RGPD : minimisation, pseudonymisation avant envoi aux fournisseurs IA, durée de conservation, fonction « tout supprimer ».
- Revue obligatoire de tout code touchant auth, données personnelles ou LLM.

## Terminé quand
Aucun finding critique ouvert ; checklist remplie sur chaque PR sensible.
