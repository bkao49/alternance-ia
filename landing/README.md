# Landing page

Page statique de présentation du projet, séparée de l'application (`frontend/`). Direction I : noir et rouge,
Instrument Serif, Geist, JetBrains Mono (polices auto-hébergées, aucun appel externe, aucun traceur).
Les chiffres et l'aperçu du tableau de bord sont fictifs.

```powershell
cd landing
npm install
npm run dev      # http://localhost:5173
npm run build    # types + build dans dist/
npm run size     # vérifie < 500 Ko de JavaScript compressé
npm test
```

- **Changer le nom** : `src/brand.ts` (`APP_NAME`), plus le logo SVG dans `index.html` (en-tête).
- **Animations** : une scène three.js (`src/scene.ts`) liée au défilement, chargée à la demande ; graphiques SVG
  tracés à l'apparition (`src/charts.ts`) ; révélations (`data-reveal`).
- **Sans animation** : avec `prefers-reduced-motion` ou sans WebGL, la scène 3D n'est pas chargée et un dessin 2D
  statique la remplace ; tout le contenu reste visible.
- **Publication** : non activée (décision à prendre avec le PO). Les chemins sont relatifs (`base: "./"`).
