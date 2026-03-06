# Документация проекта

## Актуальные документы

Все актуальные документы находятся в `docs/instructor/`:

| Документ | Описание |
|----------|----------|
| [CURRENT_TRAINING_STATUS.md](instructor/CURRENT_TRAINING_STATUS.md) | Текущий статус обучения, метрики, инфраструктура |
| [HOW_TO_ADD_NEW_TOURNAMENT.md](instructor/HOW_TO_ADD_NEW_TOURNAMENT.md) | Пошаговое руководство по добавлению турнира |
| [HOW_TO_ADD_NEW_MARKET.md](instructor/HOW_TO_ADD_NEW_MARKET.md) | Пошаговое руководство по добавлению маркета |
| [service_orchestration_architecture.md](instructor/service_orchestration_architecture.md) | Архитектура сервиса (FastAPI, Airflow, мониторинг) |

## Быстрый старт

```bash
# Data pipeline
make dvc-repro

# Обучение
uv run python -m sports_forecast.train \
    tournament=uel_kz_1 market=winner market_spec=winner \
    algorithm=catboost features=advanced

# MLflow UI
make mlflow-ui
# → http://127.0.0.1:5000

# API
make api-dev
# → http://127.0.0.1:8000/docs
```

**Последнее обновление:** 2026-03-06
