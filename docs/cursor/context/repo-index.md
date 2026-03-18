# Индекс проекта — Sports Probabilistic Forecasting

Краткий навигационный индекс структуры MLOps-проекта для вероятностного прогнозирования спортивных событий.

---

## Структура директорий

### Конфигурация (`conf/`)
- `tournament/` — конфиги турниров (7 шт.: uel_*, lp_*)
- `sport/` — спорты (cyberhockey, table_tennis)
- `source/` — источники данных (uel, lp_eu, lp_ru_by)
- `market/` — семейства рынков (winner, total)
- `market_spec/` — спецификации (winner, winner_home, total_over, total_under)
- `algorithm/` — алгоритмы (catboost, lgbm, logreg, stacking, dummy)
- `features/` — наборы фичей (basic, advanced) + generators
- `feature_selection/` — стратегии отбора фичей
- `hyper/` — оптимизация (none, optuna, grid_small)
- `bookmaker/` — мапинги к букмекерским данным
- `betting.yaml`, `calibration.yaml`, `split.yaml`, `metrics.yaml`, `mlflow/`

### Код (`sports_forecast/`)
- `data/` — ingest (source→raw), clean (raw→interim)
- `features/` — генерация фичей (EWM, Count, Form, Time) + selection
- `training/` — обучение (trainer, calibration, models, ensembles, optimization)
- `betting/` — симулятор ставок (simulator, odds)
- `service/` — FastAPI (app, routers, db, schemas)
- `monitoring/` — метрики, drift, performance, A/B testing
- `validation/` — Pandera схемы и quality gates
- `deploy/` — промоушн моделей (promoter)
- `utils/` — targets, metrics, logging
- `train.py`, `predict.py`, `materialize.py` — entry points

### Данные (`data/`)
- `source/` — исходные CSV/JSON
- `raw/` — Parquet после ingest
- `interim/` — очищенные данные
- `processed/` — данные с фичами

### Инфраструктура
- `airflow/dags/` — 4 DAG (data_refresh, training, materialize, monitoring)
- `monitoring/` — Prometheus + Grafana конфиги
- `models/` — обученные модели (по турнирам)
- `tests/` — unit-тесты (358+)
- `docs/` — документация (Sphinx + cursor/context)

---

## Entry Points

- `main.py` — унифицированный CLI (train, predict, promote)
- `sports_forecast/train.py` — обучение (Hydra)
- `sports_forecast/predict.py` — инференс
- `sports_forecast/materialize.py` — batch prediction → DB
- `sports_forecast/data/ingest.py` — ingest pipeline
- `sports_forecast/data/clean.py` — clean pipeline
- `sports_forecast/features/features_build.py` — генерация фичей
