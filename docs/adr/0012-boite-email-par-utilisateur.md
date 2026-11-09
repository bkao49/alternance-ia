# ADR 0012 : boîte e-mail par utilisateur, mot de passe chiffré (#128)

Statut : **accepté, migration 0013** (2026-11-08)

## Contexte
Les alertes e-mail (#90) lisaient une boîte unique définie par l'environnement : elle mélangerait les offres de plusieurs utilisateurs, donc le collecteur n'était pas branché sur le planificateur. Chaque utilisateur doit brancher sa propre boîte **dédiée** depuis l'application. Son mot de passe d'application est un secret : il doit être relu par le worker, mais jamais par une personne ni par l'API.

## Décision
- Table `email_boxes` (une ligne par utilisateur, RLS forcée, supprimée avec le compte).
- Le mot de passe est chiffré avec **Fernet** (bibliothèque `cryptography`, AES-128-CBC + HMAC-SHA256, jeton authentifié). La clé est **dérivée de `SECRET_KEY`** par HKDF-SHA256 avec un contexte fixe (`ereuna/email-box/v1`) : aucune clé supplémentaire à gérer, et une clé distincte de celle des sessions. `SECRET_KEY` est déjà fournie à l'API et au worker.
- L'API ne renvoie jamais le mot de passe (champ en écriture seule), les messages d'erreur et les journaux sont des textes fixes sans identifiant, omettre le mot de passe à la modification garde celui enregistré.
- L'hôte IMAP est une saisie libre : même garde-fou SSRF que les pages du robot web (nom public, ni IP ni adresse locale), revérifié avant chaque connexion (test ou collecte) ; seul le port 993 (TLS) est accepté ; le test de connexion est limité à un toutes les 10 secondes par utilisateur.
- Pas de dépendance à un service de secrets pour l'instant (un seul serveur, ADR 0001).

## Conséquences
- **Changer `SECRET_KEY` rend les mots de passe illisibles** : la collecte échoue avec « mot de passe illisible : ressaisissez-le », sans deviner ni conserver d'ancienne clé. Une rotation de clé devra ré-chiffrer (non faite : un seul utilisateur réel pour l'instant).
- Qui lit la base **et** `SECRET_KEY` peut déchiffrer : le mot de passe d'application ne donne accès qu'à une boîte dédiée aux alertes, jamais à la boîte personnelle, ce qui borne le risque.
- Un nom de serveur qui change d'adresse entre la vérification et la connexion (« rebinding ») reste possible : même limite que #71.
- `cryptography` est ajoutée aux dépendances épinglées du backend.
