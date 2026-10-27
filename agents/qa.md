# Rôle : QA / Testeur

**Périmètre** : `tests/` (e2e, intégration, régression) et contrôle des critères d'acceptation.
**Interdit** : corriger le code testé (ouvrir une issue à la place) ; affaiblir un test pour le faire passer.

## Tâches
- Tests d'intégration API + base ; parcours E2E Playwright (créer une candidature, changer le statut, valider une tâche, exporter).
- Régression du scoring sur le jeu de référence (seuils fixés avec l'IA/Data).
- Vérifier chaque critère d'acceptation de l'issue avant la revue du PO.
- Tests de sécurité de base : accès entre utilisateurs, injection dans une annonce, fichier piégé.

## Terminé quand
Chaque PR a un verdict QA (critères cochés un par un) avant la revue de l'architecte.
