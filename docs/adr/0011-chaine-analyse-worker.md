# ADR 0011 : chaîne d'analyse dans le worker

Statut : proposé (2026-11-02)

## Contexte
Le worker collectait des offres mais rien ne les analysait : extraction et score existaient en fonctions isolées. Pour que l'application marche de bout en bout dès que les clés sont dans `.env`, il faut les enchaîner, sans payer deux fois la même analyse et sans perdre d'offre quand l'IA est en panne ou que le plafond de coût est atteint.

## Décision
- `backend/app/pipeline.py`, appelé par le worker **après** chaque collecte, pour l'utilisateur de la tâche. Le résultat de la collecte est déjà enregistré : une erreur d'analyse ne le change pas.
- Sont traitées les offres non expirées **sans aucun score**. Pas de migration : « sans score » est l'état « en attente ».
- Pour chaque offre : filtres durs en code (écartée = score 0 avec raisons, **aucun appel IA**) ; sinon extraction par la passerelle (réutilisée si l'offre est inchangée, donc une fois par offre) ; sinon score déterministe.
- Plafond de coût : la passerelle lève `BudgetExceeded` ; la passe s'arrête, le journal le dit, les offres restent en attente et reprennent à la prochaine passe (le lendemain pour le plafond journalier).
- Panne du fournisseur : trois échecs de suite arrêtent la passe. Réponse du modèle invalide deux fois : l'offre est notée sans extraction (confiance faible) pour ne pas être repayée à chaque collecte.
- Sans fournisseur configuré, seuls les filtres durs tournent ; le reste attend.
- 100 offres au plus par passe.
- `GET /bot/status` gagne `analysis` (`pending`, et `paused` : `not_configured` ou `budget`), absent quand tout est analysé. Contrat étendu de façon compatible (étiquette `contract`).

## Conséquences
- Une offre dont l'extraction échoue à cause d'une panne est retentée à chaque collecte, dans la limite du plafond de coût.
- Une offre dont le texte change n'est pas renotée automatiquement (hors périmètre).
