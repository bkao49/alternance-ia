#!/bin/sh
# Exécuté une seule fois, à la création du volume, par l'image PostgreSQL (propriétaire = POSTGRES_USER).
# Crée le rôle de connexion de l'API : membre de app_rw, sans superutilisateur ni BYPASSRLS.
# Il n'est pas propriétaire des tables (créées par les migrations, lancées avec le propriétaire).
# Le mot de passe vient de l'environnement (APP_DB_PASSWORD) : il n'est écrit dans aucun fichier.
set -eu

: "${APP_DB_PASSWORD:?APP_DB_PASSWORD est obligatoire}"

psql -v ON_ERROR_STOP=1 -v app_password="$APP_DB_PASSWORD" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
    CREATE ROLE app_rw NOLOGIN;
  END IF;
END $$;

SELECT format(
  'CREATE ROLE app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS IN ROLE app_rw',
  :'app_password'
) \gexec
SQL
