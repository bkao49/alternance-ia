# frontend

Interface React + Vite + TypeScript du suivi d'alternance. Propriété : agent Frontend.

## Voir le résultat sans backend (données fictives)

```bash
cd frontend
npm install
npm run dev:mock
```

Ouvrir http://localhost:5173, mot de passe de démonstration : `demo-demo`. Les données sont fictives et gardées en mémoire (rechargez la page pour repartir de zéro).

## Avec le vrai backend

Lancer l'API (voir le README racine), puis `npm run dev` : les appels vers `/api` sont relayés vers `http://127.0.0.1:8100`. Pour se connecter en `http`, démarrer l'API avec `COOKIE_SECURE=false`.

## Commandes

| Commande | Rôle |
|---|---|
| `npm run gen:api` | Génère `src/api/schema.d.ts` depuis `../contracts/openapi.yaml` (fichier jamais édité à la main ni commité) |
| `npm run lint` | ESLint |
| `npm run typecheck` | Génère le client puis vérifie les types |
| `npm test` | Tests (Vitest, Testing Library) |
| `npm run build` | Vérification des types puis build de production |

## Principes

- Le client d'API est **généré depuis le contrat** : si le backend et le contrat divergent, le typage ou les tests deviennent rouges.
- **« Envoyée » ne se choisit jamais dans un menu** : seul le bouton « J'ai envoyé cette candidature », avec case de confirmation, appelle `confirm-sent`.
- Le texte venant d'une annonce est toujours affiché comme du texte (jamais comme du HTML).
- Pas de glisser-déposer : tout se fait au clavier (menu « Déplacer vers… », fenêtres natives `<dialog>`).
