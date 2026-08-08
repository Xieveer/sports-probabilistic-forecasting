# Индекс проекта — Sports Probabilistic Forecasting

Краткий навигационный индекс структуры MLOps-проекта для вероятностного прогнозирования спортивных событий.

---

## Структура директорий

### Конфигурация (`conf/`)
- `tournament/` — конфиги турниров (**8 файлов**, по одному slug на файл: ``uel_*``, ``lp_*``, ``nhl``; см. правило один YAML на турнир в `HOW_TO_ADD_NEW_TOURNAMENT.md`)
- `sport/` — спорты (cyberhockey, table_tennis)
- `source/` — источники данных (uel, lp_eu, lp_ru_by)
- `market/` — семейства рынков (winner, total)
- `market_spec/` — спецификации (winner, winner_home, total_over, total_under)
- `portfolio/` — версионируемый каталог связей `sport` → `tournament` →
  `model_pool` → `market/spec` → deployment profile; на текущем этапе валидирует
  контракт, но ещё не является runtime-источником DVC/Airflow (ADR-003)
- `algorithm/` — алгоритмы (catboost, lgbm, logreg, stacking, dummy)
- `features/` — наборы фичей (basic, advanced) + generators
- `feature_selection/` — стратегии отбора фичей
- `hyper/` — оптимизация (none, optuna, grid_small)
- `bookmaker/` — мапинги к букмекерским данным (`fonbet`, `the_odds_api` для The Odds API)
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
- `airflow/dags/` — DAG оркестрации: например ``data_refresh``, ``nhl_morning_refresh`` (утренний турнир + digest), ``training_sweep``, ``prediction_materialize``, ``model_monitoring`` (фактический набор см. каталог ``airflow/dags/``)
- `monitoring/` — Prometheus + Grafana конфиги
- `models/` — обученные модели (по турнирам)
- `tests/` — unit-тесты (358+)
- `docs/` — документация (Sphinx + cursor/context), включая сводный архитектурный документ `docs/cursor/context/service_orchestration_architecture.md`

### Рефакторинг и ревью (`docs/cursor/refactor/`)
- **Бэклог и приоритеты:** `backlog/*.md`, сводка `todo-refactor.md`, выполненные задачи в `done_task/`.
- **Журнал техдолга после ревью:** `backlog/reviewer-tech-debt.md` — накопительный список ограничений, компромиссов и возможных улучшений, зафиксированных Reviewer после успешной приёмки (не путать с Rework). Порядок работы: скилл `.cursor/skills/worker-reviewer-loop/SKILL.md`, роль `.cursor/agents/reviewer.md`.

---

## Entry Points

- `main.py` — унифицированный CLI (train, predict, promote)
- `sports_forecast/train.py` — обучение (Hydra)
- `sports_forecast/predict.py` — инференс
- `sports_forecast/materialize.py` — batch prediction → DB
- `sports_forecast/data/ingest.py` — ingest pipeline
- `sports_forecast/data/clean.py` — clean pipeline
- `sports_forecast/features/features_build.py` — генерация фичей
