# ADR 0003 : passerelle LLM

Statut : proposé (2026-10-30)

## Contexte
L'application appellera des modèles de langage (extraction d'annonces, brouillons de CV et de lettres). Trois risques : fuite de données personnelles vers un fournisseur (menace T2), facture qui explose (T16), et texte d'annonce qui se fait passer pour une consigne (injection).

## Décision
- **Emplacement** : `backend/app/ai/gateway/`, comme les collecteurs (ADR 0002) : l'API et le worker importent le même paquet. Le dossier racine `ai/` y renvoie.
- **Interface** `LLMProvider` : `complete(request)` est la seule méthode réseau. Chaque fournisseur déclare ses prix, les types de données qu'il accepte (`accepted_data`) et s'il réutilise les données (`reuses_data`). Un fournisseur qui réutilise ne reçoit **jamais** de donnée personnelle, même s'il l'accepte. Aucun vrai fournisseur n'est branché : seul `FakeProvider` existe, pour les tests.
- **Ordre d'un appel** : taille (50 000 caractères au plus, avant tout traitement) → liste blanche (des `known_names` fournis valent donnée personnelle, quelle que soit l'étiquette) → pseudonymisation (e-mail, URL, noms connus et leurs variantes, date de naissance, téléphone, adresse ; motifs bornés ; jetons suffixés d'un sel tiré du texte, qu'une annonce ne peut pas deviner) → données encadrées par `<donnees_non_fiables>` (balise imitée neutralisée), séparées des consignes écrites par notre code → cache → plafond → envoi → valeurs d'origine remises dans la réponse.
- **Cache** : table `llm_cache`, par utilisateur (RLS, jamais partagé), clé = hash du texte pseudonymisé, du fournisseur, du modèle et de la taille de sortie. La réponse est stockée pseudonymisée.
- **Plafond** : par utilisateur et par jour (Europe/Paris), `LLM_DAILY_CAP_EUR` (0,50 € par défaut). Le coût estimé (3 caractères par jeton, sortie maximale) est réservé dans `llm_calls.reserved_eur` avant l'envoi, sous verrou consultatif par utilisateur : deux appels simultanés ne dépassent pas le plafond, et un appel échoué reste compté (choix prudent). L'application ne peut ni supprimer une ligne de `llm_calls` ni modifier `reserved_eur` ; la dépense comptée est `max(coût réel, réservation)`.
- **Journal** : `llm_calls` ne contient que fournisseur, modèle, usage (code court), jetons, coût, cache et hash. Jamais de contenu. Toute erreur d'adaptateur devient `GatewayError` sans le message d'origine (un SDK peut y recopier la requête).
- **Adaptateurs** : `instructions` en rôle système, `data` en rôle utilisateur ; `complete` n'est appelé que par la passerelle (test qui le vérifie).

## Conséquences
- La réponse du modèle reste une donnée non fiable : à valider par schéma et à afficher échappée (T14).
- La pseudonymisation par motifs est un filet de sécurité, pas une garantie : n'envoyer que le strict nécessaire reste la règle (l'extraction ne voit jamais le CV).
- Les noms à masquer doivent être fournis par l'appelant (`known_names`), car la base ne stocke pas encore le nom de l'utilisateur.
- Le plafond mensuel global (`LLM_MONTHLY_BUDGET_EUR`) et le plafond chez le fournisseur restent à ajouter avec le premier vrai fournisseur.
