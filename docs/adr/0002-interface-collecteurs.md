# ADR 0002 : interface commune des collecteurs

Statut : proposé (2026-10-29)

## Contexte
La phase 2 branche plusieurs sources d'offres (La Bonne Alternance, France Travail, puis d'autres). Chaque source a son format, ses quotas et ses façons d'échouer. Il faut un contrat unique pour que le worker les traite toutes de la même façon, et une règle claire pour ne pas enregistrer deux fois la même offre. Les offres visées sont de tous types : stage, alternance, CDD, CDI.

## Décision
- **Emplacement** : `backend/app/collectors/`. Le worker et l'API importent le même paquet (ADR 0001) et la CI teste déjà `backend/`. Le dossier racine `collectors/` renvoie ici.
- **Interface** `Collector` : `fetch(query)` lit la source (seule partie qui touche au réseau), `normalize(raw)` traduit un enregistrement sans réseau, `collect(query)` enchaîne les deux. Un enregistrement illisible est compté et ignoré ; une erreur de source arrête cette source seulement (`collect_all`).
- **Modèle** `NormalizedOffer` (pydantic, figé, champs inconnus refusés) aligné sur `job_postings`, plus `contract_type` (`internship`, `apprenticeship`, `fixed_term`, `permanent`, `other`) et `published_at`. Texte nettoyé (caractères de contrôle retirés), URL limitée à http(s) et rendue canonique (hôte en minuscules, sans fragment ni `utm_*`).
- **Erreurs typées** : `SourceBlocked` (403, anti-bot, CAPTCHA : arrêt, jamais de contournement), `QuotaExceeded` (429, `retry_after`), `InvalidResponse`, `NetworkError`. `retryable` dit si l'on peut réessayer.
- **Déduplication** :
  1. dans une source : `dedup_key = (source, external_id)`, déjà garantie en base par `UNIQUE (user_id, source, external_id)` ; rejouer un scan ne crée donc aucun doublon ;
  2. entre sources : `fingerprint` = SHA-256 du titre, de l'entreprise (sans forme juridique : SAS, SARL…), du lieu et du type de contrat, tous en minuscules, sans accents ni ponctuation. Un stage et un CDI de même intitulé restent deux offres ;
  3. `content_hash` change quand le texte de l'annonce change (mise à jour, pas nouvelle offre).

## Pourquoi
- `normalize` pur et testable sur fixtures : aucun appel réseau dans les tests.
- L'empreinte est volontairement simple et explicable ; elle signale des doublons probables sans fusionner automatiquement.

## Conséquences
- Pas de migration ici : `contract_type`, `published_at` et `fingerprint` seront ajoutés à `job_postings` par le Backend quand le worker enregistrera les offres.
- `fetch` doit être un générateur paresseux qui respecte `max_results` (quotas) ; la reprise après `QuotaExceeded` (curseur, page) est hors périmètre et sera ajoutée avec les connecteurs réels si l'API la permet.
- Les lieux diffèrent selon les sources (« 69 - LYON 03 » contre « Lyon ») : chaque connecteur devra fournir un lieu normalisé (ville) pour que l'empreinte serve vraiment.
- `CollectorError.message` est un texte fixe ; les journaux ne contiennent que le type d'erreur, jamais le contenu d'une réponse ou d'une annonce.
- Deux offres vraiment différentes avec mêmes titre, entreprise, lieu et contrat auront la même empreinte : cas rare, l'utilisateur tranche.
