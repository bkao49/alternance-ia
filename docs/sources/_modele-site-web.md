# Fiche source : <nom du site> (`web_<nom>`)

Modèle à copier pour chaque site lu par le robot web générique (#59). Un site n'est activé
(ajouté au fichier de configuration des sites) qu'après accord du PO sur cette fiche.

| Rubrique | À remplir |
|---|---|
| Site et pages lues | domaine(s) de la liste blanche, URL de départ |
| CGU lues le | date, lien, clause sur la collecte automatisée (citée en une phrase) |
| `robots.txt` lu le | pages autorisées pour `alternance-ia-bot` ou `*`, `Crawl-delay` |
| Données structurées | JSON-LD `JobPosting` présent ? sinon sélecteurs CSS utilisés |
| Volume prévu | pages par collecte (`max_pages`), fréquence |
| Risque | faible / moyen / élevé, et pourquoi |
| Accord du PO | date, ou « en attente » |

## Règles qui s'appliquent toujours
- User-Agent identifiable, au moins 3 s entre deux requêtes vers le domaine, `robots.txt` respecté.
- Premier blocage (403, 429, défi anti-bot, CAPTCHA, page de connexion) : arrêt du site, aucun contournement.
- Aucun compte personnel du PO. On ne garde que l'offre, jamais le nom ni le contact d'un recruteur.
