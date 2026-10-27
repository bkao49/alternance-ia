# Premier prompt à coller dans Claude Code (dossier du dépôt)

```
Tu es l'agent Chef de projet de ce dépôt. Lis AGENTS.md, agents/chef-de-projet.md,
docs/BACKLOG.md et docs/STATUS.md.

Phase 0 uniquement :
1. Vérifie que la structure du dépôt correspond à AGENTS.md ; crée les dossiers manquants
   (backend/ frontend/ ai/ collectors/ contracts/ infra/ tests/ docs/adr/ docs/sources/ docs/security/)
   avec un README d'une ligne dans chacun.
2. Crée les issues GitHub P0-1 à P6-5 depuis docs/BACKLOG.md (avec gh issue create, étiquettes
   par rôle et par phase, critères d'acceptation dans le corps).
3. Ne code rien d'autre. Ne fusionne rien.
4. Termine par un compte rendu de 10 lignes et la liste des décisions que j'ai à prendre
   (voir "Bloqué / décisions attendues" dans docs/STATUS.md).

Je suis le Product Owner et je ne code pas : explique-moi chaque choix en une phrase.
```

## Ensuite
1. Une PR par issue, relue par l'agent Architecte, puis par toi.
2. Lance les rôles suivants avec : `claude` dans leur worktree, puis
   « Tu es l'agent <rôle>. Lis AGENTS.md et agents/<rôle>.md. Traite l'issue #N. »
3. Donne-moi (dans la conversation de direction de projet) tes questions de choix, les rapports de PR
   que tu ne comprends pas, et les résultats du jeu de référence.
