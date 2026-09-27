#!/usr/bin/env bash
# Тонкий host bridge: DB-driven dispatcher выбирает только установленный run,
# systemd запускает только template полного Data Cycle.
set -euo pipefail

pipeline="${1:?нужен pipeline id}"
if [[ "$pipeline" != "nhl" ]]; then
  echo "Недопустимый pipeline" >&2
  exit 2
fi

project_dir="${SF_PROJECT_DIR:-/opt/sports-forecast}"
compose_env_file="${SF_COMPOSE_ENV_FILE:-/etc/sports-forecast/refresh/nhl.env}"
cd "$project_dir"
run_id="$(/usr/bin/docker compose --env-file "$compose_env_file" \
  -f docker-compose.prod.yml --profile scheduler \
  run --rm --no-deps data-cycle-dispatcher)"
if [[ -z "$run_id" ]]; then
  exit 0
fi
if [[ "$run_id" =~ ^stalled:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$ ]]; then
  /usr/bin/bash deploy/systemd/recover-data-cycle.sh "${BASH_REMATCH[1]}"
  exit $?
fi
if [[ ! "$run_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "Dispatcher вернул некорректный run id" >&2
  exit 1
fi

/usr/bin/systemctl start --no-block "sports-forecast-data-cycle@${run_id}.service"
