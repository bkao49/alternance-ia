# Rôle : Connecteurs / Collecte

**Périmètre** : `collectors/`.
**Interdit** : contourner CAPTCHA, authentification ou anti-bot ; scraper une source dont les CGU ou le `robots.txt` l'interdisent ; ajouter une source sans fiche légale.

## Tâches
- Interface `Collector` ; sources MVP : API La Bonne Alternance, API France Travail (OAuth2, quotas, plafond de résultats par requête).
- Ensuite : ATS publics d'entreprises ciblées, alertes Gmail (lecture seule).
- Normalisation vers un schéma unique, URL canonique, hash de contenu, déduplication.
- Détection d'annonce expirée ; reprise sur erreur ; une source en échec n'arrête pas les autres.
- Détection de blocage (403, défi anti-bot, CAPTCHA) → arrêt de la source, journalisation, notification avec la cause.
- Fiche par source dans `docs/sources/<nom>.md` : CGU lues, quotas, limites.

## Tests
Sur réponses enregistrées (fixtures) ; rejouer un scan ne crée aucun doublon.
