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
# The last successful run is stored in worker_executions by canonical_full_refresh_cli.
exec /usr/bin/docker compose -f docker-compose.prod.yml --profile worker run --rm --no-deps worker \
  uv run python -m sports_forecast.orchestration.canonical_full_refresh_cli \
  "tournament=${SF_TOURNAMENT}" "market=${SF_MARKET}" \
  "market_spec=${SF_MARKET_SPEC}" "algorithm=${SF_ALGORITHM}" "features=${SF_FEATURES}"
