# Configuration GitHub (à faire par le PO, ~15 min)

1. **Créer le dépôt** (public recommandé : aucune donnée personnelle n'y entre ; atout pour le CV). Si privé, vérifie que la protection de branche est disponible sur ton plan.
2. **Compte des agents** : crée un second compte GitHub « bot » (ou une GitHub App) et ajoute-le comme collaborateur avec le rôle **Write**. Les agents poussent avec son token, jamais avec le tien : GitHub interdit d'approuver sa propre PR.
3. **Token du bot** : fine-grained, limité à ce dépôt, permissions `Contents: write` et `Pull requests: write`, rien d'autre. Expiration courte.
4. **Protection de `main`** (Settings → Branches → Add rule, ou Rulesets) :
   - Require a pull request before merging, **1 approbation**
   - Require review from Code Owners
   - Require status checks to pass (lint, tests, gitleaks, CodeQL)
   - Require conversation resolution
   - Block force pushes, restrict deletions
   - **Do not allow bypassing** (y compris administrateurs)
   - Squash merge uniquement
5. **Secrets du dépôt** : aucun secret de production accessible aux workflows lancés depuis des branches d'agents.
6. **Actions** : autoriser uniquement les actions épinglées ; `GITHUB_TOKEN` en lecture seule par défaut.
7. **Remplacer `@TON_PSEUDO_GITHUB`** dans `.github/CODEOWNERS` par ton identifiant.

## Lancer un agent
```bash
git worktree add ../wt-backend feat/backend-<sujet>
cd ../wt-backend && claude
```
Un worktree par rôle actif. Vise 2 à 3 sessions simultanées : les quotas de ton abonnement se vident vite.
