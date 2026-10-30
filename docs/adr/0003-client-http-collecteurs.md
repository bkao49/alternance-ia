# ADR 0003 : client HTTP des collecteurs web

Statut : proposé (2026-10-30)

## Contexte
Le PO a ouvert la collecte à tout site web (#60), à condition de respecter le `robots.txt`, de limiter le débit et de ne jamais contourner un anti-bot. Un lien venu d'une annonce ne doit jamais faire visiter le réseau interne (menace T9, #40).

## Décision
- Un seul chemin réseau pour les sites web : `PoliteClient` (`backend/app/collectors/http_client.py`), sur `httpx` (passé en dépendance d'exécution).
- **SSRF** : http(s), port par défaut, hôte dans la liste blanche de la source, toutes les adresses DNS publiques (préfixes IPv6 qui transportent de l'IPv4 refusés) ; chaque redirection est revérifiée, et le passage de https à http est refusé. Ni proxy ni `.netrc` lus depuis l'environnement.
- **robots.txt** (RFC 9309) : 2xx = règles lues ; 4xx = aucune règle ; 401, 403, 429, 5xx ou réponse inattendue = rien n'est lu. `Crawl-delay` respecté jusqu'à 60 s ; au-delà, le site est ignoré.
- **Débit** : au moins 3 s entre deux requêtes vers un même domaine (deux derniers labels du nom), partagé par toutes les sources d'un même processus.
- **Taille et durée** : 2 Mo au plus une fois décompressé (décompression par tranches bornées), 30 s au plus par requête.
- **Erreurs** : en plus de celles de l'ADR 0002, `PageSkipped` et ses sous-classes (`UnsafeUrl`, `RobotsDisallowed`, `PageNotFound`, `PageTooLarge`) concernent une seule page : le collecteur l'ignore et continue. 401, 403, 407 et `cf-mitigated: challenge` donnent `SourceBlocked` ; 429 donne `QuotaExceeded`.

## Pourquoi
- Une seule porte de sortie réseau : les règles de sécurité et de politesse ne dépendent pas de chaque connecteur.
- Les choix ambigus vont du côté prudent : moins de pages lues plutôt qu'un site gêné ou une adresse interne visitée.

## Conséquences
- Rebinding DNS : l'adresse est vérifiée, puis `httpx` résout à nouveau. Correction prévue dans #71 (connexion à l'IP vérifiée), à faire avant d'activer un vrai site.
- Le délai par domaine est en mémoire : deux processus worker ne le partagent pas. Le planificateur (#13) ne lance qu'une collecte à la fois par source.
- La détection d'un CAPTCHA ou d'une page de connexion servis en 200 relève de #14.

## Collecteur `web` (#59, partie 2)
- Un site = une entrée TOML (`[[site]]` : `source`, `allowed_domains`, `start_urls`, `offer_links`, `max_pages`, `selectors`), validée au chargement (URL de départ dans la liste blanche, sélecteurs CSS valides). Pas de code par site.
- Sur chaque page : JSON-LD `schema.org/JobPosting` d'abord (y compris `@graph` et `ItemList`), sélecteurs CSS ensuite. Seuls titre, entreprise, ville, contrat, texte, lien et date sont lus : `applicationContact`, `contactPoint` et le reste sont ignorés.
- Le lien déclaré dans le JSON-LD n'est gardé que s'il reste dans la liste blanche ; il n'est jamais suivi automatiquement.
- Dépendances : `beautifulsoup4` et `soupsieve` (analyseur `html.parser` de la bibliothèque standard).
