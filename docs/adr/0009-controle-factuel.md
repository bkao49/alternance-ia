# ADR 0009 : contrôle factuel des CV et lettres générés

Statut : proposé (2026-11-01)

## Décision
- Un texte généré est une liste de sections, chacune une liste de lignes `{texte, fact_ids}` (`ai/generation/schema.py`).
- **Contrôle déterministe** (`factcheck.check_document`, sans modèle, prioritaire) : chaque ligne cite au moins un fait **validé** de l'utilisateur ; nombres (chiffres ou en lettres), mois et couples mois-année, noms propres et sigles, technologies connues (liste fixe + technologies des faits de l'utilisateur), diplômes, employeur après « chez » doivent exister dans les faits **cités**. Chaque écart sort avec un code et une raison en français ; un seul écart bloque le document.
- **Vérificateur** (`verifier.verify_with_llm`) : un second appel via `ai/gateway` (type de donnée `PROFILE`, donc jamais chez un fournisseur qui réutilise les données) juge chaque ligne face à ses faits. Il ne peut qu'**ajouter** des rejets. Une réponse invalide ou incomplète donne `verifier_unavailable` : on refuse plutôt que d'accepter. `full_check` ne l'appelle que si le contrôle déterministe passe.
- Pour une lettre, `extra_names` (intitulé et entreprise de l'offre) excuse les noms propres seulement, jamais un nombre, une date, une technologie ou un diplôme.

## Limites connues (assumées : le contrôle est strict, pas magique)
- Une technologie absente de la liste, écrite en minuscules, n'est vue que par le vérificateur.
- Le premier mot d'une ligne n'est toléré que s'il ressemble à un verbe ou à un nom d'action (suffixes) et n'est le nom d'aucun autre fait.
- Un ordre de dates inversé (deux dates vraies, mal placées) ou une exagération sans chiffre ne sont vus que par le vérificateur et la relecture humaine.
