# Fiche source : La Bonne Alternance (`lba`)

API « Recherche d'opportunités d'emploi en alternance », produite par La Bonne Alternance (mission apprentissage) et listée dans le catalogue de francetravail.io. Elle remplace l'API « Offres d'emploi v2 » de France Travail, qui n'est plus dans le catalogue ouvert : les offres France Travail en alternance arrivent par cette API comme offres « partenaires ».

| Rubrique | État |
|---|---|
| Accès | `GET https://api.apprentissage.beta.gouv.fr/api/job/v1/search`, clé d'API en `Authorization: Bearer` (`LBA_API_TOKEN` dans `.env`), créée sur api.apprentissage.beta.gouv.fr (compte requis) |
| Spécification lue le 2026-10-30 | OpenAPI du dépôt public `mission-apprentissage/api-apprentissage` (`sdk/src/routes/jobs/job.routes.openapi.ts`, schéma `JobOfferRead`) ; page produit `api.apprentissage.beta.gouv.fr/fr/explorer/recherche-offre`. Le Swagger en ligne ne s'affiche qu'avec JavaScript |
| Paramètres utilisés | `romes` (métiers ROME), `departements` (numéro de département). Disponibles et non utilisés : `latitude`, `longitude`, `radius` (0 à 200 km), `rncp`, `target_diploma_level` (3 à 7), `opco` |
| Quotas | 60 appels par minute et par consommateur (documentation de la route) ; au plus 150 résultats par source, sans pagination. Le collecteur fait **un appel** par collecte |
| Contrats | Alternance seulement (`Apprentissage`, `Professionnalisation`) : tous les stages, CDD et CDI viennent d'autres sources (Adzuna) |
| Données gardées | Identifiant (LBA, ou partenaire + identifiant partenaire), intitulé, description, entreprise, ville (tirée de l'adresse), dates, lien de candidature |
| Données jamais lues | `apply.phone`, `apply.recipient_id` (contact du recruteur) ; la liste `recruiters` (candidatures spontanées, sans offre) n'est pas collectée |
| Offres pourvues | `offer.status` différent de `Active` (`Filled`, `Cancelled`) ou date d'expiration passée : offre écartée et signalée comme expirée |
| Conditions | « L'utilisation de cette API est gratuite et réservée à des usages non lucratifs » ; interdiction de revendre les données ou de facturer l'accès ; site sous licence etalab-2.0. Conservation : non précisée. CGU complètes (`/fr/cgu`) non lues |
| Risque | **Faible** : API publique officielle, usage personnel non lucratif (à confirmer après lecture des CGU) |
| Accord du PO | **En attente** |

## Avant d'activer la source
1. Créer le compte et la clé d'API, la reporter dans `.env` (jamais dans git).
2. Lire les CGU (`https://api.apprentissage.beta.gouv.fr/fr/cgu`).
3. Valider la liste des métiers ROME (`DATA_IA_ROMES` dans `backend/app/collectors/lba.py`).
4. Faire un premier appel réel et le comparer à `backend/tests/fixtures/lba/recherche.json`.
