# Fiche source : France Travail, API « Offres d'emploi v2 » (`france_travail`)

| Rubrique | État |
|---|---|
| Accès | API officielle sur francetravail.io, OAuth2 `client_credentials` : clés `FRANCE_TRAVAIL_CLIENT_ID` / `FRANCE_TRAVAIL_CLIENT_SECRET` (application créée dans l'espace francetravail.io, abonnée à « Offres d'emploi v2 ») |
| Jeton | `POST https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire`, corps `grant_type`, `client_id`, `client_secret`, `scope`. Mis en cache jusqu'à expiration (`expires_in`, moins 60 s) |
| Recherche | `GET https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search` avec `Authorization: Bearer` |
| Pagination | Paramètre `range=début-fin` : au plus 150 offres par requête, début ≤ 1000. Le collecteur lit donc au plus 7 pages (début 0, 150… 900), soit 1 050 offres. `Content-Range: offres 0-149/N` donne le total ; 204 = plus d'offre |
| Débit | Annoncé : 10 appels/s (data.gouv). Le client poli impose au moins 3 s entre deux appels (marge très large) ; sur 429 on attend `Retry-After` (30 s au plus) puis un seul nouvel essai, sinon la source s'arrête (réessayable) |
| Critères envoyés | `motsCles` (mots-clés), `departement` (« 69 ») ou `commune` (code INSEE) selon ce que contient le lieu ; un nom de ville libre n'est pas transmis. Pas de rayon (`distance`) : `SearchQuery` n'en a pas encore |
| Contrats | Voir le mapping ci-dessous. Le reste du filtrage se fait après coup, dans `collect` |
| Données collectées | Identifiant, intitulé, description, date de création, ville, nom de l'entreprise, type de contrat, lien d'origine (sinon page de détail France Travail). **Jamais** le bloc `contact` (nom, courriel, téléphone du recruteur) : RGPD |
| Identifiant stable | `id` de l'offre (clé de déduplication `france_travail:id`) |
| Statut d'exposition | **À surveiller.** data.gouv indique (lu le 2026-11-08) que l'API « n'est actuellement plus exposée sur francetravail.io le temps d'une analyse des modalités de distribution et de réutilisation du service », à cause d'usages automatisés massifs par des solutions d'IA ne respectant pas les licences. Accès « Restreint », licence non renseignée |
| CGU | **Non lues** : la documentation officielle n'a pu être ni lue (page vide) ni recoupée. Un blog tiers affirme que la licence impose d'afficher le contenu intégral de chaque offre, de citer France Travail comme source avec la date de mise à jour et un lien retour : **non vérifié**. À faire avant d'activer la source, et avant d'afficher ces offres (attribution côté front) |
| Risque | **Moyen** : API officielle avec clés propres au projet, mais accès restreint et conditions de réutilisation en cours de révision. En cas de 401/403 la source s'arrête proprement (`doctor` : `[A FAIRE]` ou `[ERREUR]`), jamais de contournement |
| Accord du PO | **En attente** : c'est le PO qui décide d'activer la source |

## À VALIDER par un appel réel (`docker compose run --rm doctor`)

La documentation officielle étant illisible, ces valeurs viennent de sources tierces (wrapper Python `api-offres-emploi`, guides d'intégration). Elles sont regroupées en haut de `backend/app/collectors/france_travail.py`, sous le titre « À VALIDER » :

- **Scope** : `application_<client_id> api_offresdemploiv2 o2dsoffre`. Un guide dit que ces valeurs « peuvent être différentes » ; le scope exact est affiché dans l'application de l'espace francetravail.io.
- **`typeContrat`** : `CDI` → CDI, `CDD` → CDD ; les autres valeurs (`MIS` intérim, `SAI`, `LIB`…) → « autre ».
- **`natureContrat`** : `E1` (contrat d'apprentissage) et `E2` (contrat de professionnalisation) → alternance. Seul `E1` a été vu dans un exemple.
- **Stage** : aucune valeur de contrat connue ; détecté par le mot « stage » dans l'intitulé.
- **Champs de l'offre lus** : `id`, `intitule`, `description`, `dateCreation`, `lieuTravail.libelle` (« 69 - LYON 03 » → « Lyon »), `entreprise.nom`, `typeContrat`, `natureContrat`, `origineOffre.urlOrigine`. Tout champ absent est toléré (l'offre sans identifiant est seule rejetée).

## Lecture du `doctor`

| Résultat | Sens |
|---|---|
| `[OK]` | Jeton obtenu et recherche de 1 offre (`range=0-0`) réussie ; le total d'offres est lu dans `Content-Range` |
| `[A FAIRE]` | 401 ou jeton refusé (400) : application non abonnée à l'API Offres d'emploi v2, ou scope différent |
| `[ERREUR]` | 403 (accès restreint), réseau, 5xx ou réponse illisible |

## Avant d'activer la source
1. Dans l'espace francetravail.io, vérifier que l'application est abonnée à « Offres d'emploi v2 » et relever le scope affiché.
2. Lancer le `doctor` ; si `[A FAIRE]`, corriger le scope dans le code ou l'abonnement.
3. Lire les conditions d'utilisation officielles et reporter ici les quotas, l'attribution et la durée de conservation.
4. Décider d'activer la source (`source_settings`).
