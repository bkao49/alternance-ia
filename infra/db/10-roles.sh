#!/bin/sh
# Exécuté une seule fois, à la création du volume, par l'image PostgreSQL (propriétaire = POSTGRES_USER).
# Crée le rôle de connexion de l'API : membre de app_rw, sans superutilisateur ni BYPASSRLS.
# Il n'est pas propriétaire des tables (créées par les migrations, lancées avec le propriétaire).
# Le mot de passe vient de l'environnement (APP_DB_PASSWORD) : il n'est écrit dans aucun fichier.
set -eu

# À améliorer plus tard (relecture Sécurité de la PR #55) : le propriétaire « owner » est superutilisateur
# dans l'image PostgreSQL, donc la fonction SECURITY DEFINER auth_lookup_user l'est aussi (étroite, search_path fixé).
# Un propriétaire non superutilisateur serait préférable.

: "${APP_DB_PASSWORD:?APP_DB_PASSWORD est obligatoire}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
-- Le mot de passe est lu dans l'environnement par psql (pas en argument : invisible dans la liste des processus).
\set app_password `printf %s "$APP_DB_PASSWORD"`
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
