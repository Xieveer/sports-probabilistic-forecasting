#!/usr/bin/env bash
# Stop exactly one stale Data Cycle owner and every Compose one-off it launched.
set -euo pipefail

run_id="${1:?нужен run UUID}"
if [[ ! "$run_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "Некорректный run UUID" >&2
  exit 2
fi

project_dir="${SF_PROJECT_DIR:-/opt/sports-forecast}"
compose_env_file="${SF_COMPOSE_ENV_FILE:-/etc/sports-forecast/refresh/nhl.env}"
unit="sports-forecast-data-cycle@${run_id}.service"
cd "$project_dir"
compose=(/usr/bin/docker compose --env-file "$compose_env_file" -f docker-compose.prod.yml)

export SF_WORKER_RUN_ID="$run_id"
unset SF_DATA_CYCLE_RUN_ID SF_DATA_CYCLE_GENERATION SF_DATA_CYCLE_OWNER_ID
owner_json="$("${compose[@]}" --profile worker run --rm --no-deps worker \
  /app/.venv/bin/python -m sports_forecast.orchestration.data_cycle_cli \
  owner-info --run-id "$run_id")"
mapfile -t owner_values < <(python3 -c '
import json, re, sys
owner = json.loads(sys.argv[1])
if owner.get("run_id") != sys.argv[2] or owner.get("status") != "stalled":
    raise SystemExit(2)
owner_id = owner.get("owner_id")
generation = owner.get("generation")
if not isinstance(owner_id, str) or re.fullmatch(r"[0-9a-f]{32}", owner_id) is None:
    raise SystemExit(2)
if not isinstance(generation, int) or generation < 1:
    raise SystemExit(2)
print(owner_id)
print(generation)
' "$owner_json" "$run_id")
if (( ${#owner_values[@]} != 2 )); then
  echo "Не удалось подтвердить owner Data Cycle" >&2
  exit 1
fi
owner_id="${owner_values[0]}"
generation="${owner_values[1]}"

invocation_before="$(/usr/bin/systemctl show --property=InvocationID --value "$unit")"
if [[ "$invocation_before" != "$owner_id" ]]; then
  echo "InvocationID systemd не совпадает с владельцем Data Cycle" >&2
  exit 1
fi
/usr/bin/systemctl stop "$unit" || true
unit_state="$(/usr/bin/systemctl show --property=ActiveState --value "$unit")"
unit_invocation="$(/usr/bin/systemctl show --property=InvocationID --value "$unit")"
unit_main_pid="$(/usr/bin/systemctl show --property=MainPID --value "$unit")"
if [[ "$unit_state" != "inactive" && "$unit_state" != "failed" ]] \
  || [[ "$unit_invocation" != "$owner_id" ]] \
  || [[ "$unit_main_pid" != "0" ]]; then
  echo "Systemd executor не подтверждён как остановленный" >&2
  exit 1
fi

inventory_file="$(mktemp)"
trap 'rm -f -- "$inventory_file"' EXIT
container_ids="$(/usr/bin/docker ps -aq \
  --filter "label=com.sfp.data-cycle.run-id=$run_id")"
if [[ -n "$container_ids" ]]; then
  while IFS= read -r container_id; do
    [[ "$container_id" =~ ^[0-9a-f]{12,64}$ ]] || exit 1
    details="$(/usr/bin/docker inspect --format \
      '{{.State.Running}}{{"\t"}}{{index .Config.Labels "com.sfp.data-cycle.run-id"}}{{"\t"}}{{index .Config.Labels "com.sfp.data-cycle.owner-generation"}}{{"\t"}}{{index .Config.Labels "com.sfp.data-cycle.owner-id"}}' \
      "$container_id")"
    IFS=$'\t' read -r is_running label_run label_generation label_owner <<<"$details"
    if [[ "$label_run" != "$run_id" || "$label_generation" != "$generation" \
      || "$label_owner" != "$owner_id" ]]; then
      echo "Run container не подтверждает executor identity" >&2
      exit 1
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' \
      "$container_id" "$label_run" "$label_generation" "$label_owner" "$is_running" \
      >>"$inventory_file"
    if [[ "$is_running" == "true" ]]; then
      /usr/bin/docker stop --time 10 "$container_id" >/dev/null
    fi
  done <<<"$container_ids"
fi

remaining_ids="$(/usr/bin/docker ps -q \
  --filter "label=com.sfp.data-cycle.run-id=$run_id")"
if [[ -n "$remaining_ids" ]]; then
  echo "В executor остались работающие one-off containers" >&2
  exit 1
fi
container_ids_after="$(/usr/bin/docker ps -aq \
  --filter "label=com.sfp.data-cycle.run-id=$run_id")"
if ! python3 - "$container_ids" "$container_ids_after" <<'PY'
import sys
before = set(filter(None, sys.argv[1].splitlines()))
after = set(filter(None, sys.argv[2].splitlines()))
raise SystemExit(0 if after <= before else 1)
PY
then
  echo "После остановки обнаружен неизвестный run container" >&2
  exit 1
fi

evidence="$(python3 - "$run_id" "$owner_id" "$generation" "$unit_state" \
  "$unit_invocation" "$unit_main_pid" "$inventory_file" <<'PY'
from datetime import UTC, datetime
import json
import sys

run_id, owner_id, generation, unit_state, invocation_id, main_pid, inventory_path = sys.argv[1:]
with open(inventory_path, encoding="utf-8") as inventory_file:
    rows = [line.rstrip("\n").split("\t") for line in inventory_file if line.strip()]
if any(len(row) != 5 for row in rows):
    raise SystemExit(2)
evidence = {
    "run_id": run_id,
    "owner_id": owner_id,
    "owner_generation": int(generation),
    "systemd_active_state": unit_state,
    "systemd_invocation_id": invocation_id,
    "systemd_main_pid": int(main_pid),
    "discovered_container_ids": [row[0] for row in rows],
    "stopped_container_ids": [row[0] for row in rows],
    "remaining_container_ids": [],
    "container_run_ids": [row[1] for row in rows],
    "container_generations": [int(row[2]) for row in rows],
    "container_owner_ids": [row[3] for row in rows],
    "inventory_complete": True,
    "verified_at": datetime.now(UTC).isoformat(),
}
print(json.dumps(evidence, separators=(",", ":")))
PY
)"

# The helper commits recovery only; its own container is outside the stopped owner labels.
export SF_DATA_CYCLE_RUN_ID=untracked
export SF_DATA_CYCLE_GENERATION="$generation"
export SF_DATA_CYCLE_OWNER_ID="$owner_id"
"${compose[@]}" --profile worker run --rm --no-deps worker \
  /app/.venv/bin/python -m sports_forecast.orchestration.data_cycle_cli \
  recover --run-id "$run_id" --evidence "$evidence"
