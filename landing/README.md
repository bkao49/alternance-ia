# Landing page

Page de présentation d'Ereuna, séparée de l'application (`frontend/`). Une seule police, Inter, auto-hébergée :
aucun appel externe, aucun traceur. Les exemples d'écran sont fictifs.

```powershell
cd landing
npm install
npm run dev      # http://localhost:5173 (ou le port affiché si 5173 est pris)
npm run build    # types + build dans dist/
npm run size     # vérifie < 500 Ko de JavaScript compressé
npm test
```

- **Changer le nom** : `src/brand.ts` (`APP_NAME`), plus le logo SVG dans `index.html` (en-tête).
- **Thème** : clair par défaut, sombre si le système le demande ; le bouton « Mode sombre / Mode clair » mémorise
  le choix (`src/theme.ts`, repris dans le `<head>` d'`index.html` pour éviter un flash).
- **Animations** : la vague de particules (`src/wave.ts`, dessinée en 2D, sans bibliothèque) est poussée par le
  défilement ; chaque étape « déferle » (variable CSS `--p` posée par `src/main.ts`).
- **Sans animation** : avec `prefers-reduced-motion`, la vague est une image fixe et tout le contenu est affiché.
- **Publication** : non activée (décision à prendre avec le PO). Les chemins sont relatifs (`base: "./"`).
