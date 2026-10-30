# Fiche source : France Travail (`france_travail`)

| Rubrique | État |
|---|---|
| Accès | API « Offres d'emploi v2 » de francetravail.io, OAuth2 *client credentials* (realm `/partenaire`, scope `api_offresdemploiv2 o2dsoffre`). Clés `FRANCE_TRAVAIL_CLIENT_ID` / `FRANCE_TRAVAIL_CLIENT_SECRET` dans `.env` |
| Hôtes appelés | `entreprise.francetravail.fr` (jeton) et `api.francetravail.io` (recherche), écrits dans le code |
| Documentation lue | **Non lue cette nuit** : les pages de francetravail.io ne s'affichent qu'avec JavaScript et sont restées vides, y compris dans un navigateur. Le format utilisé (paramètres, champs, plages `range`) vient de la version connue de l'API et **doit être vérifié** au premier appel avec une vraie clé |
| Quotas | À relever dans l'espace partenaire. Le collecteur fait au plus 7 recherches par collecte (1 000 offres), avec 3 s entre deux appels ; plage `range` de 150 au plus, jamais au-delà de 3 000 |
| Données gardées | Identifiant, intitulé, description, date, ville (`lieuTravail.libelle` sans département ni arrondissement), entreprise, type de contrat, lien d'origine |
| Données jamais lues | Bloc `contact` (nom, adresse, courriel, téléphone du recruteur) : RGPD |
| Couverture | Tous les contrats (CDI, CDD, alternance…), France entière ; filtre de lieu par numéro de département seulement |
| Risque | **Faible** : API publique officielle, prévue pour ce type d'usage |
| CGU | À lire dans l'espace partenaire lors de la création de l'application (mention de la source, conservation) |
| Accord du PO | **En attente** (clés à fournir, voir `docs/STATUS.md`) |

## Avant d'activer la source
1. Créer l'application sur francetravail.io, abonner l'API « Offres d'emploi v2 », reporter les clés dans `.env`.
2. Lire les conditions d'utilisation et noter ici la mention de source et la durée de conservation.
3. Faire un premier appel réel et comparer la réponse à `backend/tests/fixtures/france_travail/recherche.json` ; corriger le collecteur si un champ diffère.
