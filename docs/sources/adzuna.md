# Fiche source : Adzuna (`adzuna`)

| Rubrique | État |
|---|---|
| Accès | API officielle `https://api.adzuna.com/v1/api/jobs/fr/search/{page}`, clés `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` (compte gratuit sur developer.adzuna.com, sans moyen de paiement) |
| Pages lues le 2026-10-30 | developer.adzuna.com : `overview`, `docs/search`, `docs/terms_of_service` |
| Usage autorisé | Les conditions citent la « recherche d'emploi personnelle » parmi les usages permis. Un usage commercial (produit ou service qui rapporte de l'argent ou des contacts) demande une licence |
| Attribution | Pour afficher les annonces : mention « Adzuna » avec un lien vers adzuna.fr sur chaque annonce. **À ajouter côté front** avant d'afficher ces offres |
| Quotas | Non publiés : ils sont affichés dans le compte et peuvent changer. Le collecteur fait au plus 10 appels par collecte, avec 3 s entre deux appels |
| Lieu | Dernier niveau de `location.area` (la ville en principe) : à vérifier sur une vraie réponse, une région ou un arrondissement fausserait l'empreinte entre sources |
| Données | Extrait de description seulement (l'API ne donne pas le texte complet), titre, entreprise, ville, contrat, date, lien de redirection Adzuna (jamais suivi automatiquement) |
| Stockage | Les conditions ne disent rien d'explicite sur la conservation ; à la résiliation, les données doivent être retirées des pages publiées |
| Points d'attention | Interdiction de contacter un fournisseur tiers d'annonces ; un seul compte par entité ; Adzuna peut suspendre un compte en cas de doute |
| Risque | **Faible** pour un usage personnel de recherche d'emploi (API officielle, clés propres au projet) |
| Accord du PO | **En attente** |

## Avant d'activer la source
1. Créer le compte et reporter les clés dans `.env` (jamais dans git).
2. Relever les quotas affichés dans le compte et les noter ici.
3. Lire les conditions générales complètes d'adzuna.fr (non lues cette nuit) et confirmer l'usage personnel.
4. Ajouter la mention « Adzuna » sur les offres de cette source dans le front.
