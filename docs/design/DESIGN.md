# DESIGN.md — Direction I (noir et rouge, blocs arrondis)

Référence visuelle : [`maquettes/direction-i.html`](maquettes/direction-i.html), choisie par le PO parmi neuf.
Les jetons vivent dans [`frontend/src/theme/tokens.css`](../../frontend/src/theme/tokens.css) : ce document en
explique le rôle, le code en est la seule source de valeurs.

## Intention

Un outil de travail calme, presque éditorial : beaucoup de noir, un seul rouge, de grands chiffres en
serif. Le rouge signale ce qui compte (le nombre d'offres pertinentes, ce que fait le bot, l'action
principale) et rien d'autre. Pas d'ombres, pas de dégradés : les blocs se distinguent par leur fond et
par des filets fins.

## Nom et logo

Le nom n'est pas décidé (Piste, Boussole, Cap, Jalon). Il vit dans **une seule constante**,
`APP_NAME` dans `frontend/src/brand.ts` (valeur provisoire « Piste »), reprise aussi par le titre de
l'onglet. Le logo est un SVG en ligne dans `frontend/src/components/Logo.tsx` : changer de nom, c'est
modifier ces deux fichiers. Les quatre logos possibles sont dans la maquette I.

## Couleurs

Thème **sombre** par défaut (celui de la maquette) ; thème **clair** dérivé, appliqué quand le système le
demande (`prefers-color-scheme: light`). Mêmes noms de jetons dans les deux thèmes.

| Jeton | Sombre | Clair | Rôle |
|---|---|---|---|
| `--bg` | `#0d0d0f` | `#f6f5f2` | Fond de page |
| `--surface` | `#141416` | `#ffffff` | Barre latérale, bloc des offres, colonnes, fenêtres |
| `--hover` | `#1a1a1d` | `#efeee9` | Survol d'une ligne, fond de champ |
| `--text` | `#f4f4f4` | `#131316` | Texte principal, filet fort en tête de tableau |
| `--muted` | `#a6a6ae` | `#5b5b64` | Texte secondaire, libellés |
| `--line` | `#2a2a2f` | `#dedcd6` | Filets décoratifs entre lignes et blocs |
| `--control` | `#6b6b74` | `#86868f` | Bordure des champs et boutons (composant d'interface) |
| `--accent` | `#d6231e` | `#c41e19` | **Aplats** : bloc du bot, logo, bouton principal |
| `--accent-text` | `#ff5a52` | `#b3140f` | **Texte et traits** rouges : grand chiffre, liens, focus, erreurs |
| `--on-accent` | `#ffffff` | `#ffffff` | Texte posé sur `--accent` |

Deux rouges, parce qu'un seul ne passe pas partout : `--accent` est assez sombre pour porter du texte
blanc, `--accent-text` assez clair (en sombre) ou assez foncé (en clair) pour être lu sur le fond.

### Contrastes vérifiés (WCAG 2.2 AA)

Calculés avec la formule de luminance relative du WCAG.

| Paire | Sombre | Clair | Seuil |
|---|---|---|---|
| `--text` sur `--bg` / `--surface` / `--hover` | 17,7 / 16,7 / 15,8 | 17,0 / 18,5 / 16,0 | 4,5 |
| `--muted` sur `--bg` / `--surface` / `--hover` | 8,0 / 7,6 / 7,2 | 6,2 / 6,7 / 5,8 | 4,5 |
| `--accent-text` sur `--bg` / `--surface` / `--hover` | 6,3 / 6,0 / 5,7 | 6,4 / 7,0 / 6,0 | 4,5 |
| `--on-accent` sur `--accent` | 5,1 | 5,9 | 4,5 |
| `--control` sur `--bg` / `--surface` | 3,7 / 3,5 | 3,3 / 3,6 | 3 (non-texte) |

`--line` sert seulement de séparateur décoratif : un champ ou un bouton a toujours une bordure
`--control`.

### Couleurs de statut

Les statuts sont personnalisables : leur couleur vient de l'API (`Status.color`, filtrée par
`safeColor`). Elle ne sert qu'à la pastille ; le nom du statut est toujours écrit à côté, donc
l'information ne repose jamais sur la couleur seule.

## Typographie

Trois familles, **auto-hébergées** dans le front (paquets `@fontsource/*`, fichiers `woff2` servis avec
l'application, sous-ensemble latin) : aucun appel à Google Fonts. Licence SIL OFL 1.1.

| Jeton | Famille | Usage |
|---|---|---|
| `--serif` | Instrument Serif 400, romain et italique | Titres, grands chiffres, nom du produit |
| `--sans` | Geist 400 et 500 | Texte courant, interface |
| `--mono` | JetBrains Mono 400 | Journal du bot, heures |

| Rôle | Taille | Famille |
|---|---|---|
| Titre de page (`h1`) | `clamp(2.6rem, 6vw, 5.4rem)`, interligne 0,95 | serif |
| Grand chiffre | `clamp(5rem, 10vw, 8.5rem)`, italique | serif |
| Titre de section (`h2`) | `clamp(1.9rem, 3.4vw, 2.8rem)` | serif |
| Titre de bloc | 2rem, italique | serif |
| Texte courant | 1rem, interligne 1,55 | sans |
| Libellé, texte secondaire | 0,85–0,92rem | sans |
| Journal | 0,86rem, interligne 1,9 | mono |

Les nombres utilisent `font-variant-numeric: tabular-nums` (classe `.num`).

## Espacements

Échelle en rem, sur une base de 4 px : `--space-1` 0,25 · `--space-2` 0,5 · `--space-3` 0,75 ·
`--space-4` 1 · `--space-5` 1,5 · `--space-6` 2 · `--space-7` 3 · `--space-8` 4. Les marges de page et
de section sont fluides (`clamp`) pour respirer sur grand écran sans déborder sur mobile.

## Rayons

| Jeton | Valeur | Usage |
|---|---|---|
| `--radius-lg` | 22 px | Grands blocs : offres, bot, colonnes du Kanban, fenêtres, carte de connexion |
| `--radius-md` | 14 px | Cartes du Kanban, encadrés |
| `--radius-sm` | 10 px | Champs et menus |
| `--radius-pill` | 999 px | Boutons, puces, sélecteur de vue |

## Mouvement

Durées courtes (`--dur-fast` 150 ms, `--dur` 250 ms) et une seule courbe (`--ease-out`). Le mouvement
accompagne un survol ou l'arrivée d'une ligne du journal, jamais une information. Avec
`prefers-reduced-motion: reduce`, toutes les transitions et animations sont coupées.

## Composants

**Barre latérale.** Fond `--surface`, collée en haut sur grand écran (14,5 rem de large). Logo et nom en
serif italique, puis la navigation : Accueil, Offres, Candidatures. L'entrée courante est soulignée d'un
trait `--accent-text`. Une entrée sans écran encore disponible reste visible mais inactive, avec la
mention « bientôt ». En bas : l'identité de l'utilisateur et « Se déconnecter ». Sous 54 rem de large,
elle devient une barre horizontale en haut de page.

**En-tête « Bonjour ».** `h1` serif « Bonjour {nom}. » suivi d'une phrase de résumé en `--muted` qui ne
cite que des chiffres réels (offres pertinentes, candidatures à valider).

**Bloc des offres pertinentes.** Fond `--surface`, filet `--line`, rayon 22 px, au moins 17 rem de haut.
Grand chiffre italique `--accent-text`, libellé « offres pertinentes » dessous. Quand une vue des offres
existe, le bloc entier devient un lien : au survol, bordure `--accent-text` et léger soulèvement.

**Bloc « Le bot travaille ».** Aplat `--accent`, texte `--on-accent`, rayon 22 px. Titre serif italique,
indicateur d'état (pastille pulsée « En cours »), journal en mono des dernières actions et heure de la
prochaine collecte. **Tant que l'API n'expose pas les collectes, il affiche un état vide honnête :
« Aucune collecte pour l'instant », sans pastille ni heure inventée.** Le journal animé n'existe qu'en
mode démonstration.

**Chiffres clés.** Une bande de compteurs séparés par des filets, sans cadre ; chiffre en serif, libellé
en `--muted` dessous.

**Tableau à filets.** Pas de cadre ni de fond : un filet `--text` au-dessus de la première ligne, puis des
filets `--line` entre les lignes. Au survol, la ligne se teinte en `--hover` et son contenu s'écarte
légèrement du bord. Les en-têtes de colonnes sont des boutons de tri.

**Puces de statut.** Pastille ronde de la couleur du statut + nom du statut, en ligne. Les puces de
contrat (CDI, stage…) sont des pilules à bordure `--line`, texte `--muted`.

**Kanban.** Colonnes `--surface` à rayon 22 px, cartes `--bg` à rayon 14 px. Déplacement par le menu
« Déplacer vers… », jamais par glisser-déposer.

**Boutons.**
- Principal : pilule pleine `--accent`, texte `--on-accent`.
- Secondaire : pilule à bordure `--control`, texte `--text` ; au survol, fond `--hover`.
- Lien : texte souligné, sans fond.
- Hauteur minimale 2,75 rem (44 px) pour les cibles tactiles principales.

**Champs.** Fond `--hover`, bordure `--control`, rayon 10 px, libellé toujours visible au-dessus.

**Focus.** Anneau de 2 px `--accent-text` décalé de 3 px, sur tous les éléments interactifs
(`:focus-visible`). Dans le bloc du bot, l'anneau passe en `--on-accent`.

## Accessibilité (contrôle à chaque PR)

- Contrastes AA ci-dessus ; aucune information portée par la couleur seule.
- Focus visible partout ; ordre de tabulation = ordre visuel.
- `prefers-reduced-motion` respecté.
- Affichage correct de 320 px à grand écran, sans défilement horizontal de la page (le Kanban et le
  tableau défilent dans leur propre zone).
- Le texte venant d'une annonce est toujours rendu comme du texte.
