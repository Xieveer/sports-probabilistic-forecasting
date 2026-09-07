#!/bin/sh
# Выполняется одноразовым role-bootstrap service после PostgreSQL healthcheck.
set -eu

read_secret() {
    eval "secret_file=\${$1_FILE:-}"
    test -n "$secret_file" && test -r "$secret_file"
    cat "$secret_file"
}

# psql не получает URL/password в argv. Временный pgpass живёт только в tmpfs
# read-only bootstrap container, имеет 0600 и удаляется при завершении процесса.
pgpass_file=/tmp/pgpass
umask 077
printf 'db:5432:sports_forecast:sf_user:%s\n' "$(read_secret SF_POSTGRES_PASSWORD)" > "$pgpass_file"
export PGPASSFILE="$pgpass_file"
export PGHOST=db PGPORT=5432 PGDATABASE=sports_forecast PGUSER=sf_user

# format(... %L) экранирует password. `\set` читает secret внутри psql через
# private file descriptor: secret values не попадают в argv shell/psql.
psql --set=ON_ERROR_STOP=1 <<'SQL'
\set api_password `cat "$SF_API_DB_PASSWORD_FILE"`
\set worker_password `cat "$SF_WORKER_DB_PASSWORD_FILE"`
\set migrator_password `cat "$SF_MIGRATOR_DB_PASSWORD_FILE"`
SELECT format('CREATE ROLE sf_api_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L', :'api_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sf_api_reader') \gexec
SELECT format('ALTER ROLE sf_api_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L', :'api_password') \gexec
SELECT format('CREATE ROLE sf_refresh_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L', :'worker_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sf_refresh_writer') \gexec
SELECT format('ALTER ROLE sf_refresh_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L', :'worker_password') \gexec
SELECT format('CREATE ROLE sf_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L', :'migrator_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sf_migrator') \gexec
SELECT format('ALTER ROLE sf_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L', :'migrator_password') \gexec
ALTER SCHEMA public OWNER TO sf_migrator;
GRANT CONNECT ON DATABASE sports_forecast TO sf_migrator, sf_api_reader, sf_refresh_writer;
GRANT USAGE, CREATE ON SCHEMA public TO sf_migrator;
GRANT USAGE ON SCHEMA public TO sf_user;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
