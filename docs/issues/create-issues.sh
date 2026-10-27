#!/usr/bin/env bash
# Crée les étiquettes puis une issue GitHub par fichier docs/issues/P*.md.
# Prérequis : `gh auth login` fait, et lancé depuis le dépôt (remote GitHub configuré).
# Relançable sans risque : une issue dont le titre existe déjà est ignorée.
set -euo pipefail
cd "$(dirname "$0")"

label() { gh label create "$1" --color "$2" --description "$3" --force >/dev/null; }

for r in chef-de-projet architecte backend frontend ia-data connecteurs devops securite qa; do
  label "role:$r" 1d76db "Rôle de l'agent responsable"
done
for p in 0 1 2 3 4 5 6; do
  label "phase:$p" fbca04 "Phase $p de la roadmap"
done
label contract d93f0b "Modifie contracts/ — revue PO obligatoire"

for f in P*.md; do
  title=$(sed -n '1s/^title: //p' "$f")
  labels=$(sed -n '2s/^labels: //p' "$f")
  if gh issue list --state all --search "\"$title\" in:title" --json title --jq '.[].title' | grep -Fxq "$title"; then
    echo "déjà présente : $title"
    continue
  fi
  sed '1,3d' "$f" | gh issue create --title "$title" --label "$labels" --body-file -
done
