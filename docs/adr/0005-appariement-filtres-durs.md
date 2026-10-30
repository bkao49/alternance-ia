# ADR 0005 : filtres durs et niveaux de critère

Statut : proposé (2026-10-30)

## Décision
- Les filtres durs sont du code (`backend/app/ai/matching/filters.py`), sans IA. Chaque contrôle rend ok, échec ou inconnu ; une information absente ou hors liste est « inconnue » et n'écarte jamais l'offre.
- Trois niveaux par critère : **dur** (expirée, mots exclus, contrat : l'offre est écartée, raison écrite dans `scores.blocking_reasons` avec un score 0), **obligatoire** (lieu, niveau d'études : plafonne le score, issue #18), **souhaité** (date de début, salaire : baisse seulement une note).
- La politique est dans le code, pas par utilisateur : la rendre réglable demande une colonne dans `search_preferences` (migration, décision du PO).
- `search_preferences.education_level` est lu comme le niveau du candidat ; une offre qui exige plus est en échec.
- Le rayon exige des coordonnées. Sans géocodeur, un lieu différent reste « inconnu » : le critère « lieu » ne plafonne rien tant qu'un géocodeur (table de communes ou service) n'est pas choisi.
- Mots exclus : titre et description, mot entier, sans accent ni casse. Un mot exclu cité dans la description (« pas de profil senior ») écarte l'offre : à valider.

## Conséquences
Un écart enregistré est un score 0 ; un score écrit plus tard le remplace (le plus récent gagne).
