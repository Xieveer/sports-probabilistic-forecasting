#!/usr/bin/env bash
# Один scheduler run с durable Data Cycle outcome.
set -euo pipefail

profile="${1:?нужен идентификатор tournament profile}"
if [[ ! "$profile" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  echo "Недопустимый идентификатор tournament profile" >&2
  exit 2
fi

: "${SF_TOURNAMENT:?нужен SF_TOURNAMENT}"
: "${SF_MARKET:?нужен SF_MARKET}"
: "${SF_MARKET_SPEC:?нужен SF_MARKET_SPEC}"
: "${SF_ALGORITHM:?нужен SF_ALGORITHM}"
: "${SF_FEATURES:?нужен SF_FEATURES}"

export SF_WORKER_RUN_ID="${profile}-$(date -u +%Y%m%dT%H%M%SZ)-$(uuidgen)"
compose=(/usr/bin/docker compose -f docker-compose.prod.yml)
control() {
  "${compose[@]}" --profile worker run --rm --no-deps worker \
    /app/.venv/bin/python -m sports_forecast.orchestration.data_cycle_cli "$@"
}
control create --run-id "${SF_WORKER_RUN_ID}" --tournament "${SF_TOURNAMENT}" \
  --reason "${SF_DATA_CYCLE_REASON:-scheduled}"
active_stage="calendar"
manifest_list=""
on_exit() {
  result=$?
  trap - EXIT
  if [[ -n "${manifest_list}" ]]; then
    rm -f -- "${manifest_list}" || true
  fi
  if (( result != 0 )); then
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
control start-stage --run-id "${SF_WORKER_RUN_ID}" --stage "${active_stage}"

/usr/bin/docker compose -f docker-compose.prod.yml --profile source-acquisition run --rm --no-deps source-acquirer \
  /app/.venv/bin/python -m sports_forecast.orchestration.source_snapshot_cli \
  --tournament "${SF_TOURNAMENT}"

# WorkerExecution remains the lower-level materialization outcome.
/usr/bin/docker compose -f docker-compose.prod.yml --profile worker run --rm --no-deps worker \
  /app/.venv/bin/python -m sports_forecast.orchestration.canonical_full_refresh_cli \
  "tournament=${SF_TOURNAMENT}" "market=${SF_MARKET}" \
  "market_spec=${SF_MARKET_SPEC}" "algorithm=${SF_ALGORITHM}" "features=${SF_FEATURES}"
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
  /usr/bin/docker compose -f docker-compose.prod.yml --profile operational-sync run --rm --no-deps archive-sync \
    sync --archive "${container_artifact}" --state-root /app/sync-state --prefix "${prefix}"
  artifact_count=$((artifact_count + 1))
done <"${manifest_list}"
rm -f -- "${manifest_list}"
manifest_list=""
control finish-stage --run-id "${SF_WORKER_RUN_ID}" --stage "${active_stage}" \
  --status success --counts "{\"artifacts\":${artifact_count}}"
control finish-run --run-id "${SF_WORKER_RUN_ID}" --status partial_success --summary '{}'
trap - EXIT
