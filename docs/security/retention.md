# Durées de conservation (RGPD)

Menace T18 (#42). Chaque utilisateur peut tout supprimer à tout moment : `POST /account/delete` (mot de passe redemandé) efface son compte et **toutes** ses lignes, dans toutes les tables (`ON DELETE CASCADE` depuis `users`, vérifié par `tests/test_account.py`).

| Donnée | Durée | Mécanisme |
|---|---|---|
| Profil, faits, critères de recherche | Jusqu'à la suppression par l'utilisateur | `POST /account/delete` |
| Candidatures, historique, tâches, documents | Jusqu'à la suppression par l'utilisateur | `POST /account/delete` |
| Offres détectées **non retenues** par une candidature (avec leurs analyses et scores) | `RETENTION_OFFERS_DAYS` (180 jours par défaut, 30 au moins) après détection | `python -m app.retention` |
| Journal des appels IA (`llm_calls`) et cache IA (`llm_cache`) | `RETENTION_LLM_DAYS` (90 jours par défaut, 30 au moins) | `python -m app.retention` |
| Journaux techniques de l'application | Aucune donnée personnelle (règle AGENTS.md) ; rotation Docker à régler au déploiement | #27 |
| Sauvegardes | Même durée que la donnée la plus longue purgée, **30 jours au plus** de rétention des sauvegardes elles-mêmes : une donnée supprimée disparaît des sauvegardes au plus tard 30 jours après | à mettre en place avec les sauvegardes (Phase 6) |

## Purge
`python -m app.retention` appelle la fonction SQL `purge_expired_data` (migration 0006). Elle appartient au rôle `retention_purger`, qui ne lit que les colonnes d'identifiant et de date de `job_postings`, `llm_calls`, `llm_cache` (et `applications.job_posting_id`) et peut supprimer dans ces trois tables, pour tous les utilisateurs. Elle refuse une durée de moins de 30 jours. **L'API ne peut pas l'appeler** : seul `retention_runner`, dont n'est membre que le rôle des migrations, le peut ; la commande se connecte donc avec `MIGRATION_DATABASE_URL`. Supprimer une offre supprime aussi ses analyses et scores. Le journal de la purge ne contient que des compteurs. À lancer chaque jour par le worker (tâche planifiée, à venir).
