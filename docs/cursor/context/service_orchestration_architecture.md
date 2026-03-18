# Service & Orchestration Architecture (FastAPI + Airflow)

## Цель

ML-сервис прогнозирования с низкой latency API и вынесенными в фоновые процессы тяжёлыми вычислениями.

**Ключевой принцип**: Онлайн-сервис не выполняет тяжёлые вычисления. Все предикты вычисляются batch pipeline и сохраняются в витрине предсказаний.

## Архитектура

**Компоненты**: FastAPI (read-only API), Airflow (4 DAG), MLflow (tracking + registry), DVC (версионирование), PostgreSQL/SQLite (витрины), Prometheus + Grafana (мониторинг).

## Стратегия inference: Precomputed Predictions

**Проблема on-demand**: высокая latency, нагрузка на feature generation, риск падения SLA.

**Решение**: batch prediction → predictions in DB → API reads. API только читает, вычисления асинхронно в фоне.

## Online API (FastAPI)

**Endpoints**: `GET /predict/{match_id}`, `/predict/upcoming/{tournament}`, `/predict/stale`, `/metrics`.

**Ответ**: `match_id`, `predictions`, `model` (version/algorithm/featureset), `prediction_ts`, `status` (ok/stale/error). In-memory LRU кеш (TTL 5 минут).

## Prediction Materialization

Batch-процесс (`materialize.py`): `active matches → features → prod model → inference → DB`.

**Хранилище**: таблица `predictions` (SQLAlchemy): `match_id`, `tournament`, `market`, `market_spec`, `model_version`, `algorithm`, `featureset`, `predictions_json`, `prediction_ts`, `status`.

## Orchestration (Airflow)

**4 DAG**:

1. **`data_refresh`** (при получение новых данных в source): `source → ingest → clean → features`
2. **`training_sweep`** (ручной): `Hydra multirun → MLflow → model promotion` (выбор лучшего run → копирование в `models/`)
3. **`prediction_materialize`** (после data_refresh): batch inference → DB
4. **`monitoring`**: data freshness, feature drift (PSI/KS), prediction distribution

Все задачи через CLI (BashOperator), ML-логика вне Airflow.

## Model Registry & Promotion

**MLflow Model Registry**: версионирование, артефакты, метрики, stages (Staging/Production/Archived). `ModelPromoter` выбирает лучшую модель по метрике (`test_logloss`) и копирует артефакты в `models/{tournament}/{market_spec}/{algorithm}_{features}/`.

## Monitoring

**Service** (Prometheus): request latency, error rate, throughput. **ML** (модуль `monitoring/`): data drift (PSI/KS), performance (AUC/LogLoss/ECE/ROI), A/B testing (shadow vs prod).

## Принципы

- **Разделение**: API → чтение, pipeline → вычисления
- **Воспроизводимость**: DVC + MLflow + versioned configs
- **Изоляция**: обучение не влияет на API
- **Масштабируемость**: компоненты масштабируются отдельно

## Технологический стек

| Компонент | Инструмент |
|-----------|------------|
| API | FastAPI |
| Validation | Pandera |
| Orchestration | Airflow |
| Experiments | MLflow |
| Datasets | DVC |
| Monitoring | Prometheus + Grafana |
| Drift | PSI/KS (собственный модуль) |
