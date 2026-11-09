# Fiche source : pages carrières de l'utilisateur (`web`)

Le robot web générique (#59) lit les pages que **chaque utilisateur** saisit dans « Mes sources » (table `web_pages`, 10 pages au plus). Ce n'est pas un site précis : les CGU de chaque site restent à lire par l'utilisateur, qui en prend la responsabilité ; l'application l'écrit à l'écran.

| Rubrique | État |
|---|---|
| Accès | Pages publiques saisies par l'utilisateur, sans compte ni connexion. Lecture des données structurées `schema.org/JobPosting` (JSON-LD) ; pas de lien suivi d'une page à l'autre |
| CGU | À la charge de l'utilisateur pour chaque site (message affiché sous le champ). Une page qui demande une connexion ou un CAPTCHA arrête la source |
| `robots.txt` | Toujours lu et respecté (`alternance-ia-bot`, puis `*`) ; un `Crawl-delay` supérieur à 60 s fait ignorer le site |
| Débit | Au moins 3 s entre deux requêtes vers un même domaine, User-Agent identifiable, 10 pages au plus par collecte |
| Données | Titre, entreprise, lieu, contrat, texte, lien. Jamais le nom ni le contact d'un recruteur |
| Risque | **Moyen** : le site visé n'est pas connu d'avance. Atténué par les garde-fous ci-dessous |
| Accord du PO | Source générique « ouverte à tout site » (décision du 2026-10-29) ; le PO active la source pour lui-même, chaque ami active la sienne |

## Garde-fous (SSRF et blocages)
- À l'enregistrement : `http` ou `https` seulement, un nom de site (ni adresse IP, ni `localhost`, `.local`, `.internal`…), pas de port particulier, identifiants retirés de l'adresse, adresse non publique refusée si le nom se résout vers une adresse privée.
- À chaque requête du worker, `PoliteClient` refait les contrôles : domaine limité à celui de la page (sous-domaines compris), toutes les adresses résolues doivent être publiques, redirections revérifiées. Le cas d'un nom dont l'adresse change entre deux requêtes (« rebinding ») reste à durcir : issue #71.
- Sites fermés (LinkedIn, Indeed, Glassdoor, APEC) refusés avec renvoi vers les alertes e-mail : aucune collecte directe, aucun contournement.
- Premier blocage (403, 429, défi anti-bot, CAPTCHA, page de connexion) : la source de l'utilisateur est arrêtée et marquée « bloquée » (écran « Mes sources »), l'événement est journalisé ; elle ne se réactive qu'avec une confirmation explicite.
- Limite connue : une page qui n'expose pas de JSON-LD `JobPosting` ne donne aucune offre (les sélecteurs CSS restent réservés aux sites du fichier `WEB_SITES_FILE`).
