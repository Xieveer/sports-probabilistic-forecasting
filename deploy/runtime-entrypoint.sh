#!/bin/sh
# Считывает runtime secret только в окружение дочернего процесса.
set -eu

for secret_name in DATABASE_URL BOT_TOKEN SF_OBJECT_STORAGE_ACCESS_KEY_ID SF_OBJECT_STORAGE_SECRET_ACCESS_KEY ODDS_API_KEY_FREE ODDS_API_KEY_20K ODDS_API_KEY_100K ODDS_API_KEY; do
    eval "secret_file=\${${secret_name}_FILE:-}"
    if [ -n "$secret_file" ]; then
        if [ ! -r "$secret_file" ]; then
            echo "${secret_name}_FILE недоступен" >&2
            exit 64
        fi
        secret_value=$(cat "$secret_file")
        export "$secret_name=$secret_value"
    fi
done

exec "$@"
