#!/usr/bin/env bash
# NHL: полный data refresh (source → … → materialize) с flock — см. cron_refresh CLI.
# Установите SF_PROJECT_DIR на корень клона на сервере.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export SF_PROJECT_DIR="${SF_PROJECT_DIR:-$ROOT}"
cd "$SF_PROJECT_DIR"
exec uv run python -m sports_forecast.orchestration.cron_refresh --tournaments "${SF_REFRESH_TOURNAMENTS:-nhl}" "$@"
