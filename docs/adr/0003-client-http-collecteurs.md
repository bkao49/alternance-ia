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

## Blocage et expiration (#14)
- `PoliteClient` reconnaît aussi un blocage certain servi en 200 : page de défi (marqueurs propres aux pages de défi, pas les scripts présents sur toutes les pages) ou redirection vers une page de connexion. Un **CAPTCHA** n'arrête la source que s'il remplace le contenu attendu (ni offre ni lien sur la page) : un CAPTCHA sur le formulaire « Postuler » d'une vraie offre ne compte pas. Cause fixe dans `SourceBlocked.message`. Le texte visible est extrait en temps linéaire et seuls les 500 000 premiers caractères sont examinés (pas de ReDoS).
- `handle_blocks` désactive la source (ensemble `disabled`) et notifie une seule fois (`Notifier`, journal par défaut). **La désactivation n'est pas encore persistée** : il faut une table (voir la PR de #14).
- Annonce expirée (`validThrough` passé, mention « offre n'est plus disponible ») : `normalize` lève `OfferExpired`, `collect` range son identifiant dans `CollectResult.expired`. `Collector.check_expired(url)` revérifie une offre enregistrée (404/410 = expirée) ; `expiry.refresh_expired` relit les pages **hors transaction**, marque `job_postings.expired` sous RLS dans une transaction courte (les marquages trouvés avant un blocage sont gardés) et fait tourner un curseur `detected_at` pour ne pas revérifier toujours les mêmes offres.
- Pas encore branché de bout en bout : le planificateur (#13, ADR 0004) appellera `mark_expired` avec `CollectResult.expired`, `refresh_expired` et `handle_blocks`.

## Client des API officielles (#76)
- Les sources à API (Adzuna, France Travail) passent par `ApiClient` (`backend/app/collectors/api_client.py`) et non par `PoliteClient` : `robots.txt` ne s'applique pas à une API documentée et les clés doivent être protégées. Mêmes garanties pour le reste : hôte(s) fixe(s) dans le code, pas de redirection, ni proxy ni `.netrc`, 3 s entre deux appels avec la même clé de domaine (`site_key`) et le même délai partagé que le robot web, corps lu par tranches bornées (`read_body`, 2 Mo décompressés) et 30 s au plus par requête.
- **Clés** : les URL journalisées par `httpx` / `httpcore` sont masquées après le « ? » par un filtre (quel que soit le niveau de journal) ; une erreur réseau ne garde que le type d'exception, sans `__cause__` ni `__context__` (le message d'`httpx` contient l'URL). À prévoir si un outil de suivi d'erreurs arrive : ne pas capturer les variables locales.
- 401/403 d'une API = clé refusée : `SourceBlocked`, la source s'arrête et le PO est notifié.
