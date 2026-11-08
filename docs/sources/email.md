# Fiche source : alertes e-mail (`email`)

| Rubrique | État |
|---|---|
| Accès | Aucun site n'est contacté. L'utilisateur crée lui-même ses alertes (Indeed, LinkedIn, Welcome to the Jungle, JobTeaser, HelloWork, France Travail, Adzuna) et les redirige vers une **boîte dédiée**, jamais sa boîte personnelle. Le collecteur lit cette boîte en IMAP (TLS) |
| CGU | Aucune à respecter côté sites : on lit des e-mails que l'utilisateur reçoit légitimement, sans robot, sans compte de site, sans contournement. Vérifier seulement que les conditions de la boîte (Gmail, Outlook…) autorisent l'accès IMAP avec mot de passe d'application |
| Données | Titre, entreprise, lieu, type de contrat s'il est écrit, lien de l'offre. Jamais le nom ni le contact d'un recruteur, jamais le corps de l'e-mail |
| Liens | Gardés pour que l'utilisateur ouvre l'offre lui-même : **jamais suivis** par le collecteur. Seuls les liens `https` vers le site de l'alerte sont acceptés ; les paramètres de suivi (`utm_*`, `tk`, `trackingId`, `refId`, `trk`, `xtor`…) sont retirés |
| Risque | **Faible** (le seul risque propre à cette source est un e-mail piégé, traité plus bas) |
| Accord du PO | **En attente** |

## Configuration (variables d'environnement, voir `.env.example`)
`EMAIL_ALERTS_HOST`, `EMAIL_ALERTS_USER`, `EMAIL_ALERTS_PASSWORD` (mot de passe d'application), et en option `EMAIL_ALERTS_PORT` (993), `EMAIL_ALERTS_FOLDER` (INBOX), `EMAIL_ALERTS_REQUIRE_AUTH` (voir plus bas).
**Par utilisateur (migration 0013, ADR 0012)** : chaque utilisateur saisit sa propre boîte dédiée dans « Mes sources » (serveur IMAP, adresse, mot de passe d'application, dossier ; port 993 seulement). Le mot de passe est chiffré au repos, jamais renvoyé par l'API ni journalisé, et un bouton « Tester la connexion » vérifie la boîte. Le collecteur est branché sur le planificateur : le worker lit la boîte de l'utilisateur du job, jamais celle d'un autre. Les variables `EMAIL_ALERTS_HOST/USER/PASSWORD` ne servent plus qu'au contrôle `doctor`.
Le serveur IMAP est une saisie de l'utilisateur : nom public seulement (ni IP, ni adresse locale ou privée, revérifié à chaque connexion), pour qu'on ne puisse pas faire sonder le réseau interne par l'application.
**LinkedIn** : aucune connexion au compte de l'utilisateur, aucune collecte sur le site. L'utilisateur crée lui-même l'alerte emploi dans LinkedIn avec l'adresse de la boîte dédiée ; seuls les e-mails reçus sont lus.

## Expéditeurs reconnus (liste blanche)
| Site | Domaine par défaut | Variable pour le remplacer |
|---|---|---|
| Indeed | `indeed.com` | `EMAIL_ALERTS_DOMAINS_INDEED` |
| LinkedIn | `linkedin.com` | `EMAIL_ALERTS_DOMAINS_LINKEDIN` |
| Welcome to the Jungle | `welcometothejungle.com` | `EMAIL_ALERTS_DOMAINS_WTTJ` |
| JobTeaser | `jobteaser.com` | `EMAIL_ALERTS_DOMAINS_JOBTEASER` |
| HelloWork | `hellowork.com` | `EMAIL_ALERTS_DOMAINS_HELLOWORK` |
| France Travail | `francetravail.fr` | `EMAIL_ALERTS_DOMAINS_FRANCETRAVAIL` |
| Adzuna | `adzuna.fr`, `adzuna.com` | `EMAIL_ALERTS_DOMAINS_ADZUNA` |

**À vérifier** : ces domaines sont les domaines principaux des sites, non confirmés par leur documentation (aucun accès réseau lors de l'écriture). Relever l'expéditeur réel d'un premier e-mail reçu et corriger la variable si besoin. Un sous-domaine (`mail.indeed.com`) est accepté ; un domaine ressemblant (`indeed.com.autre.test`) est refusé.

## Gabarits d'extraction
Chaque site a un gabarit (sélecteurs CSS dans `backend/app/collectors/mail.py`). **Ils ont été écrits d'après des e-mails fictifs** (`backend/tests/fixtures/email/`), pas d'après de vrais e-mails : à ajuster sur un premier vrai e-mail, anonymisé, avant de compter sur les résultats. Si un gabarit ne trouve rien, aucune offre n'est créée et un avertissement est journalisé.

## Sécurité : e-mail piégé
- Le contenu est une donnée : le HTML est lu comme du texte, les scripts, images et styles sont ignorés, aucune consigne n'est exécutée.
- L'expéditeur doit être dans la liste blanche **et** authentifié (DMARC réussi, ou DKIM réussi signé par son domaine, lu dans l'en-tête ajouté par votre serveur de messagerie). Sinon l'e-mail est écarté : marqué « lu » pour ne pas être relu (jamais supprimé), et une alerte légitime écartée à tort doit être remise à « non lu » à la main. Seul l'en-tête ajouté par votre serveur compte : **renseigner `EMAIL_ALERTS_AUTHSERV_ID`** (premier mot de l'en-tête `Authentication-Results` de vos e-mails reçus) ; sans lui, on prend l'en-tête le plus récent, et un serveur qui n'en ajoute aucun laisserait un expéditeur en poser un faux. Les e-mails illisibles, trop gros ou sans offre reconnue (gabarit périmé : un avertissement est journalisé) sont aussi écartés sans arrêter la collecte. Si vos e-mails redirigés échouent à cette vérification, `EMAIL_ALERTS_REQUIRE_AUTH=false` la retire : on accepte alors qu'un faux e-mail puisse proposer de fausses offres (le lien reste limité au site de l'alerte).
- Aucune suppression : un e-mail traité reçoit seulement le drapeau « lu » ; le client n'a pas de commande de suppression.
- Les identifiants ne sont ni écrits dans les journaux ni repris dans les messages d'erreur.
