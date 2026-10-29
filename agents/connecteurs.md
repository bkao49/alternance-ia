# Rôle : Connecteurs / Collecte

**Périmètre** : `collectors/`.
**Interdit** : contourner CAPTCHA, authentification ou anti-bot ; ignorer le `robots.txt` ; se connecter avec un compte du PO pour collecter ; ajouter une source sans fiche (CGU lues, risque noté, accord du PO).

## Tâches
- Interface `Collector` ; sources MVP : API La Bonne Alternance, API France Travail (OAuth2, quotas, plafond de résultats par requête).
- Ensuite : ATS publics d'entreprises ciblées, alertes Gmail (lecture seule).
- Normalisation vers un schéma unique, URL canonique, hash de contenu, déduplication.
- Détection d'annonce expirée ; reprise sur erreur ; une source en échec n'arrête pas les autres.
- Détection de blocage (403, défi anti-bot, CAPTCHA) → arrêt de la source, journalisation, notification avec la cause.
- Fiche par source dans `docs/sources/<nom>.md` : CGU lues, risque (faible, moyen, élevé), quotas, limites, accord du PO.
- Robot web : User-Agent identifiable, au plus une requête toutes les 3 s par domaine, cache, arrêt au premier blocage.
- Données des annonces : on ne garde que l'offre (titre, entreprise, lieu, contrat, texte, lien), jamais le nom ni le contact d'un recruteur (RGPD).

## Tests
Sur réponses enregistrées (fixtures) ; rejouer un scan ne crée aucun doublon.
