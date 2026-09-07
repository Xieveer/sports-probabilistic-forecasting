# ─────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile for Sports Probabilistic Forecasting
#
# Stages:
#   base   — runtime dependencies + uv
#   api    — FastAPI read-only prediction server
#   worker — одноразовый batch prediction / materialize
# ─────────────────────────────────────────────────────────────────

# ── Base stage ──────────────────────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app

# CI и Operations выполняют smoke-gates через bare ``python``. Зависимости
# остаются в изолированном uv-venv, но должны быть видимы этому интерпретатору.
ENV PATH="/app/.venv/bin:$PATH" \
    HOME="/tmp" \
    XDG_CACHE_HOME="/tmp/.cache" \
    MPLCONFIGDIR="/tmp/matplotlib"

RUN groupadd --system --gid 10001 sf && \
    useradd --system --uid 10001 --gid sf --home-dir /app --shell /usr/sbin/nologin sf

# System deps
RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /uvx /bin/

# Copy dependency files first for caching
COPY pyproject.toml uv.lock ./

# Install third-party deps (cached layer); project sources are copied below.
RUN uv sync --frozen --no-dev --no-install-project

# Copy project code
COPY --chown=sf:sf sports_forecast/ ./sports_forecast/
COPY --chown=sf:sf conf/ ./conf/
COPY --chown=sf:sf migrations/ ./migrations/
COPY --chown=sf:sf alembic.ini ./
COPY --chown=sf:sf params.yaml ./
COPY --chown=sf:sf deploy/runtime-entrypoint.sh /app/runtime-entrypoint.sh
RUN chmod 0555 /app/runtime-entrypoint.sh

# Install the local package after its sources are available.
RUN uv sync --frozen --no-dev

# ── API stage (thin read-only server) ──────────────────────────
FROM base AS api

USER sf

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ready || exit 1

ENTRYPOINT ["/app/runtime-entrypoint.sh"]
CMD ["/app/.venv/bin/uvicorn", "sports_forecast.service.app:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# ── Telegram bot (aiogram) ────────────────────────────────────
FROM base AS telegram-bot

USER sf

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD /app/.venv/bin/python -m sports_forecast.bot.heartbeat --path /tmp/sf-bot-heartbeat.json --max-age-seconds 120

ENTRYPOINT ["/app/runtime-entrypoint.sh"]
CMD ["/app/.venv/bin/python", "-m", "sports_forecast.bot", "hydra/job_logging=disabled", \
     "hydra.output_subdir=null"]

# ── Worker stage (batch prediction / materialize) ──────────────
FROM base AS worker

USER sf

ENTRYPOINT ["/app/runtime-entrypoint.sh"]
CMD ["/app/.venv/bin/python", "-m", "sports_forecast.orchestration.canonical_full_refresh_cli", \
     "tournament=nhl", "market=winner_withOT", "market_spec=winner_withOT", \
     "algorithm=catboost_reg", "features=advanced", "hydra/job_logging=disabled", \
     "hydra.output_subdir=null"]

# ── Archive sync (отдельный Object Storage credential boundary) ──
FROM base AS archive-sync

RUN uv sync --frozen --no-dev --group archive-sync

USER sf

ENTRYPOINT ["/app/runtime-entrypoint.sh"]
CMD ["/app/.venv/bin/python", "-m", "sports_forecast.deploy.archive_sync_runtime"]
