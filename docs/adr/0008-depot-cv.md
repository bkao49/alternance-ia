# ADR 0008 — Dépôt de CV : stockage en base et extraction isolée

Statut : proposé (#41, menace T15).

## Décision
- **Stockage** : le fichier est une colonne `bytea` de `cv_documents` (un CV par utilisateur, 5 Mo max). Aucun
  dossier, donc rien à servir publiquement, aucun nom de fichier utilisé comme chemin ; la RLS et la suppression
  du compte (`ON DELETE CASCADE`) s'appliquent sans code en plus.
- **Type** vérifié sur le contenu (`%PDF-` ou zip DOCX avec `word/document.xml`), jamais sur l'extension. Refus des
  PDF avec JavaScript, lancement, fichier embarqué ou chiffrement, des DOCX avec macros, chemins douteux,
  trop d'entrées ou taux de compression de zip bombe.
- **Extraction** dans un processus Python fils (`-I`, environnement vide, dossier temporaire vide, 20 s max,
  mémoire et processeur limités sous Linux). Le script n'importe rien de l'application. Dans ce processus,
  les connexions réseau sont désactivées par code.
- **Téléchargement** : lien signé (`itsdangerous`), 60 s, contenant l'identifiant de l'utilisateur ; la session
  doit correspondre. Nom de fichier de réponse fixe, `nosniff`, `no-store`.
- **Quota** : 5 dépôts par heure et par utilisateur (journal `cv_uploads`, non remis à zéro par une suppression).

## Limite connue
La coupure du réseau est faite dans le processus (Python), pas par le système. Pour une vraie isolation
système, il faudra lancer l'extraction dans un conteneur sans réseau (`network_mode: none`) : à décider avec le
déploiement (#27).
