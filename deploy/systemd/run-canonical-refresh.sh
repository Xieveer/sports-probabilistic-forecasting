#!/usr/bin/env bash
# Один scheduler run. Успешный сигнал сохраняется runner-ом в worker_executions.
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
/usr/bin/docker compose -f docker-compose.prod.yml --profile source-acquisition run --rm --no-deps source-acquirer \
  uv run python -m sports_forecast.orchestration.source_snapshot_cli \
  --tournament "${SF_TOURNAMENT}"

# The last successful run is stored in worker_executions by canonical_full_refresh_cli.
/usr/bin/docker compose -f docker-compose.prod.yml --profile worker run --rm --no-deps worker \
  uv run python -m sports_forecast.orchestration.canonical_full_refresh_cli \
  "tournament=${SF_TOURNAMENT}" "market=${SF_MARKET}" \
  "market_spec=${SF_MARKET_SPEC}" "algorithm=${SF_ALGORITHM}" "features=${SF_FEATURES}"

# Sync only already-verified immutable artifacts. A failed upload leaves staging
# and makes this scheduler run non-zero; it never replaces the last remote state.
: "${SF_OPERATIONAL_ARCHIVE_ROOT:?нужен SF_OPERATIONAL_ARCHIVE_ROOT}"
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
done < <(find "${SF_OPERATIONAL_ARCHIVE_ROOT}/operational-archive" -type f -name manifest.json -print0)
