# ADR 0007 : score agrégé, couverture et explication

Statut : proposé (2026-10-30)

## Décision
- `score = 5 × Σ(wᵢ·sᵢ) / Σw` sur les composantes connues : intitulé 30, compétences 20, expérience 15, lieu et télétravail 10, contrat 5, salaire 10, diplôme 10. Réglable sans migration par `MATCH_WEIGHTS` (JSON, variable d'environnement). Une composante inconnue sort du calcul.
- Couverture = poids des composantes connues / poids total. Sous 0,5, le score est ramené vers 2,5 de façon linéaire. Confiance : élevée dès 0,8, moyenne dès 0,5, sinon faible.
- Un critère obligatoire violé (lieu, niveau d'études ; voir ADR 0005) plafonne le score à 2,0.
- Notes de composantes par code (recoupement de mots, pas d'IA). Compétences = tout fait du profil ; expérience = faits de type expérience ou projet seulement.
- L'explication vient d'un gabarit appliqué aux critères calculés et ne cite que des `fact_ids` du profil ; `check_fact_ids` rejette un fait inexistant.
- Écriture dans `scores` (`criteria` jsonb, `blocking_reasons`) ; `GET /offers`, `GET /offers/{id}` et le tableau de bord lisent déjà ces colonnes.

## Écart avec le contrat
`ScoreCriterion.key` est une liste fermée (`technical_skills`, `projects`, `domain`, …) qui ne correspond pas aux sept composantes demandées. Les clés écrites sont `title`, `skills`, `experience`, `location_remote`, `contract`, `salary`, `degree` : une PR étiquetée `contract` doit élargir la liste.
