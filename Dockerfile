# ─────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile for Sports Probabilistic Forecasting
#
# Stages:
#   base   — runtime dependencies + uv
#   api    — FastAPI read-only prediction server
#   worker — batch prediction / materialize / training
# ─────────────────────────────────────────────────────────────────

# ── Base stage ──────────────────────────────────────────────────
FROM python:3.10-slim AS base

WORKDIR /app

# System deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files first for caching
COPY pyproject.toml uv.lock ./

# Install Python deps (cached layer)
RUN uv sync --frozen --no-dev

# Copy project code
COPY sports_forecast/ ./sports_forecast/
COPY conf/ ./conf/
COPY params.yaml ./

# ── API stage (thin read-only server) ──────────────────────────
FROM base AS api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uv", "run", "uvicorn", "sports_forecast.service.app:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# ── Worker stage (batch prediction / training) ─────────────────
FROM base AS worker

# Копируем данные и модели (при необходимости монтируются как volume)
COPY data/ ./data/
COPY models/ ./models/

CMD ["uv", "run", "python", "-m", "sports_forecast.materialize"]
