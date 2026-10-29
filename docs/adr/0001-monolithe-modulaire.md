# ADR 0001 : monolithe modulaire

Statut : accepté (2026-10-29)

## Contexte
Un seul développeur (le PO, qui ne code pas) et des agents IA construisent l'application. Le budget et le temps sont limités, et le serveur final est un petit VPS.

## Décision
Un seul dépôt et un seul déploiement : API FastAPI et worker partagent le même code Python (`backend/`), la base est PostgreSQL avec pgvector, la file de tâches s'appuie sur PostgreSQL (pas de Redis au départ). Le frontend React est un second dossier du même dépôt, relié à l'API par le contrat `contracts/openapi.yaml`.

## Pourquoi
- Un seul endroit à lancer, tester et sauvegarder : moins de pièces qui peuvent tomber en panne.
- Les modules (`backend/`, `ai/`, `collectors/`) restent séparés par dossier et par propriétaire, donc on pourra les extraire en services si le besoin apparaît.

## Conséquences
- Pas de communication réseau interne à sécuriser entre services.
- Le worker et l'API ne peuvent pas être mis à l'échelle séparément ; acceptable pour un seul utilisateur.
- Redis ou un broker pourra être ajouté plus tard par un nouvel ADR.
