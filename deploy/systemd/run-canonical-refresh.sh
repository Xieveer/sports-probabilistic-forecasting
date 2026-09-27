#!/usr/bin/env bash
# Один scheduler run с durable Data Cycle outcome.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/data-cycle-owner-guard.sh"

pipeline_id="${1:?нужен идентификатор pipeline}"
run_id="${2:?нужен заранее созданный run UUID}"
if (( $# != 2 )); then
  echo "Ожидаются аргументы: pipeline_id run_id" >&2
  exit 2
fi
case "$pipeline_id" in
  nhl) ;;
  *) echo "Недопустимый pipeline" >&2; exit 2 ;;
esac
if [[ ! "$run_id" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]]; then
  echo "Недопустимый run UUID" >&2
  exit 2
fi

data_odds_enabled=true
if [[ ${SF_DATA_ODDS_ENABLED+x} ]]; then
  data_odds_enabled="${SF_DATA_ODDS_ENABLED}"
fi
case "$data_odds_enabled" in
  true|false) ;;
  *)
    echo "SF_DATA_ODDS_ENABLED должен быть true или false" >&2
    exit 2
    ;;
esac

: "${SF_TOURNAMENT:?нужен SF_TOURNAMENT}"
: "${SF_MARKET:?нужен SF_MARKET}"
: "${SF_MARKET_SPEC:?нужен SF_MARKET_SPEC}"
: "${SF_ALGORITHM:?нужен SF_ALGORITHM}"
: "${SF_FEATURES:?нужен SF_FEATURES}"

if [[ "$SF_TOURNAMENT" != "$pipeline_id" ]]; then
  echo "Pipeline не соответствует фиксированному tournament profile" >&2
  exit 2
fi
owner_id="${INVOCATION_ID:?systemd должен передать owner InvocationID}"
if [[ ! "$owner_id" =~ ^[[:xdigit:]]{32}$ ]]; then
  echo "Некорректный systemd InvocationID" >&2
  exit 2
fi
export SF_WORKER_RUN_ID="${run_id}"
export SF_DATA_CYCLE_RUN_ID="${run_id}"
export SF_DATA_CYCLE_OWNER_ID="${owner_id,,}"
compose=(/usr/bin/docker compose -f docker-compose.prod.yml)
control() {
  "${compose[@]}" --profile worker run --rm --no-deps worker \
    /app/.venv/bin/python -m sports_forecast.orchestration.data_cycle_cli "$@"
}
run_with_heartbeat() {
  data_cycle_run_with_heartbeat "$@"
}
active_stage="calendar"
manifest_list=""
on_exit() {
  result=$?
  trap - EXIT
  if [[ -n "${manifest_list}" ]]; then
    rm -f -- "${manifest_list}" || true
  fi
  if (( result != 0 )); then
    if data_cycle_should_defer_terminal_failure; then
      echo "Data Cycle heartbeat ownership uncertain; host recovery must prove stage stop" >&2
      exit "${result}"
    fi
    if [[ "${active_stage}" == "archive_sync" ]]; then
      control fail --run-id "${SF_WORKER_RUN_ID}" --code archive_sync_failed || true
    elif [[ "${SF_TOURNAMENT}" == "nhl" ]]; then
      control fail --run-id "${SF_WORKER_RUN_ID}" --code executor_interrupted \
        --calendar-attempt --tournament "${SF_TOURNAMENT}" || true
    else
      control fail --run-id "${SF_WORKER_RUN_ID}" --code executor_interrupted || true
    fi
    exit "${result}"
  fi
  exit 0
}
trap on_exit EXIT
trap 'data_cycle_handle_signal 143' TERM
trap 'data_cycle_handle_signal 130' INT
data_cycle_mark_claim_attempted
generation="$(control claim --run-id "${SF_WORKER_RUN_ID}" --owner-id "${SF_DATA_CYCLE_OWNER_ID}")"
if [[ ! "${generation}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Data Cycle claim вернул некорректную generation" >&2
  exit 1
fi
export SF_DATA_CYCLE_GENERATION="${generation}"
control start-stage --run-id "${SF_WORKER_RUN_ID}" --stage "${active_stage}"

run_with_heartbeat /usr/bin/docker compose -f docker-compose.prod.yml --profile source-acquisition run --rm --no-deps source-acquirer \
  /app/.venv/bin/python -m sports_forecast.orchestration.source_snapshot_cli \
  --tournament "${SF_TOURNAMENT}" --odds-enabled "${data_odds_enabled}"

# WorkerExecution remains the lower-level materialization outcome.
run_with_heartbeat /usr/bin/docker compose -f docker-compose.prod.yml --profile worker run --rm --no-deps worker \
  /app/.venv/bin/python -m sports_forecast.orchestration.canonical_full_refresh_cli \
  "tournament=${SF_TOURNAMENT}" "market=${SF_MARKET}" \
  "market_spec=${SF_MARKET_SPEC}" "algorithm=${SF_ALGORITHM}" "features=${SF_FEATURES}" \
  "data_odds_enabled=${data_odds_enabled}" \
  "hydra/job_logging=stdout" "hydra.output_subdir=null"
active_stage="pipeline"

# Sync only already-verified immutable artifacts. A failed upload leaves staging
# and makes this scheduler run non-zero; it never replaces the last remote state.
: "${SF_OPERATIONAL_ARCHIVE_ROOT:?нужен SF_OPERATIONAL_ARCHIVE_ROOT}"
active_stage="archive_sync"
control start-stage --run-id "${SF_WORKER_RUN_ID}" --stage "${active_stage}"
manifest_list="$(mktemp)"
if ! bash deploy/systemd/list-canonical-archive-manifests.sh \
  "${SF_OPERATIONAL_ARCHIVE_ROOT}" >"${manifest_list}"; then
  exit 1
fi
artifact_count=0
while IFS= read -r -d '' manifest; do
  artifact="${manifest%/manifest.json}"
  relative="${artifact#"${SF_OPERATIONAL_ARCHIVE_ROOT}/"}"
  prefix="${SF_OPERATIONAL_ARCHIVE_PREFIX:-operational-archive}"
  if [[ "$relative" == operational-archive/nhl-source-state/v1/* ]]; then
    prefix="${SF_NHL_SOURCE_STATE_PREFIX:-operational-archive/nhl-source-state/v1}"
  fi
  container_artifact="/app/archive/${relative}"
  run_with_heartbeat /usr/bin/docker compose -f docker-compose.prod.yml --profile operational-sync run --rm --no-deps archive-sync \
    /app/.venv/bin/python -m sports_forecast.deploy.archive_sync_cli \
    sync --archive "${container_artifact}" --state-root /app/sync-state --prefix "${prefix}"
  artifact_count=$((artifact_count + 1))
done <"${manifest_list}"
rm -f -- "${manifest_list}"
manifest_list=""
control finish-stage --run-id "${SF_WORKER_RUN_ID}" --stage "${active_stage}" \
  --status success --counts "{\"artifacts\":${artifact_count}}"
control finish-run --run-id "${SF_WORKER_RUN_ID}" --status auto
trap - EXIT
