# ─────────────────────────────────────────────────────────────────
# Dockerfile для Airflow с ML-зависимостями проекта
# Базовый образ: Apache Airflow (slim)
# ─────────────────────────────────────────────────────────────────

FROM apache/airflow:2.10.4-python3.10

USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

USER airflow

# Устанавливаем uv для запуска проектных команд
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Копируем зависимости проекта
COPY pyproject.toml uv.lock /app/
WORKDIR /app
RUN uv sync --frozen --no-dev 2>/dev/null || true

# Копируем код проекта
COPY sports_forecast/ /app/sports_forecast/
COPY conf/ /app/conf/
COPY params.yaml /app/
