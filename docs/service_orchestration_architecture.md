
# Service & Orchestration Architecture (FastAPI + Airflow)

## Цель

Собрать архитектуру ML-сервиса прогнозирования, где:

- онлайн-API отвечает **быстро и стабильно** (низкая latency);
- вычислительно тяжёлые операции вынесены в **фоновые процессы**;
- релиз новых моделей проходит через **quality gates**;
- система имеет **наблюдаемость** (monitoring, drift detection, alerts);
- воспроизводимость экспериментов обеспечивается через **DVC + MLflow**.

Ключевой принцип системы:

> Онлайн-сервис не выполняет тяжёлые вычисления.
> Все предикты вычисляются **фоновыми задачами** и сохраняются в витрине предсказаний.

---

# 1. High-level архитектура

Система состоит из нескольких независимых компонентов:

Airflow orchestrates background pipelines:
- Data Refresh
- Training
- Validation
- Prediction Materialization
- Monitoring

Основные сервисы:

| сервис | назначение |
|------|------|
FastAPI | онлайн выдача предиктов |
Airflow | оркестрация pipeline |
MLflow | tracking экспериментов и registry |
DVC | управление версиями датасетов |
PostgreSQL | хранение витрин данных |
Prometheus | сбор метрик |
Grafana | визуализация мониторинга |

---

# 2. Стратегия inference

В системе используется **precomputed predictions strategy**.

### Почему

On-demand inference имеет ряд проблем:

- высокая latency
- нагрузка на feature generation
- риск падения SLA при пиковом трафике

Поэтому применяется следующий подход:

batch prediction pipeline
→ predictions stored in database
→ API reads predictions

Таким образом:

- API выполняет **только чтение данных**
- вычисления происходят **асинхронно в фоне**

---

# 3. Online API (FastAPI)

## Endpoint

GET /predict/{match_id}

### Поведение

1. API получает `match_id`.
2. Выполняется поиск записи в таблице `predictions`.
3. Возвращается **последний актуальный предикт**.

### Ответ (пример)

```json
{
  "match_id": "abc123",
  "market": "winner",
  "predictions": {
    "home_win": 0.53,
    "away_win": 0.47
  },
  "model": {
    "version": "winner_cb_v42",
    "trained_at": "2026-01-14T03:00:00Z",
    "featureset": "advanced"
  },
  "prediction_ts": "2026-01-14T12:10:00Z",
  "snapshot_ts": "2026-01-14T12:09:30Z",
  "status": "ok"
}
```

### Возможные статусы

| статус | значение |
|------|------|
ok | актуальный предикт |
stale | предикт устарел |
not_ready | предикт ещё не рассчитан |
error | ошибка генерации |

---

# 4. Prediction materialization

Предикты рассчитываются **в фоновом batch-процессе**.

Pipeline:

matches list
→ feature generation
→ model inference
→ write predictions to DB

Batch-подход позволяет:

- оптимизировать вычисления
- снизить нагрузку на сервис
- упростить масштабирование

---

# 5. Хранилище предиктов

Основная таблица:

`predictions`

### структура

| поле | описание |
|----|----|
match_id | идентификатор матча |
market | тип рынка |
model_version | версия модели |
featureset_hash | версия feature pipeline |
prediction_ts | время расчёта |
snapshot_ts | состояние матча |
predictions_json | вероятности |
status | состояние предикта |

### индексы

index(match_id)
index(prediction_ts)

---

# 6. Feature generation

Feature generation используется в двух местах:

- train pipeline
- inference pipeline

Чтобы избежать **train-serving skew**:

- используется **единый модуль feature generation**
- код генерации фичей полностью переиспользуется

---

# 7. Data validation

Перед использованием данных выполняется **валидация**.

Используется библиотека:

Pandera

Примеры проверок:

- schema validation
- диапазоны значений
- отсутствие NaN
- уникальность ключей

Pipeline:

raw data → clean → features → validation → store

---

# 8. Orchestration (Airflow)

Используются несколько независимых DAG.

### DAG A — Data Refresh

source → ingest → clean → features

Обновляет данные.

---

### DAG B — Training Sweep

dataset → hydra multirun → MLflow logging → model artifacts

Запускает обучение моделей.

---

### DAG C — Validation & Promotion

Проверяет кандидатов моделей.

Quality gates:

- метрика лучше baseline
- стабильность по фолдам
- проверка калибровки
- sanity checks

Если проверки пройдены:

model promoted to production

---

### DAG D — Monitoring

Проверяет:

- data freshness
- feature drift
- prediction distribution

Инструменты:

Evidently
whylogs

---

### DAG E — Prediction Materialization

Pipeline генерации предиктов.

active matches
→ build features
→ load production model
→ batch inference
→ write predictions

---

# 9. Model registry

Для управления версиями моделей используется:

MLflow Model Registry

В registry хранится:

- version
- artifacts
- metrics
- stage

Stages:

Staging
Production
Archived

---

# 10. Monitoring

## Service monitoring

Используются:

Prometheus + Grafana

Метрики:

- request latency
- error rate
- throughput

---

## ML monitoring

Отслеживаются:

- data drift
- prediction distribution
- feature stability

Инструменты:

Evidently
whylogs

---

# 11. Observability

Для трассировки используется:

OpenTelemetry

Позволяет анализировать:

request → feature loading → inference → response

---

# 12. Фоновые задачи

В системе **не используется Celery как обязательный компонент**.

Причина:

- Airflow выполняет orchestration задач
- batch-процессы покрывают основные вычисления

Celery может быть добавлен позже для:

- on-demand задач
- event-driven обновлений

---

# 13. Принципы архитектуры

### разделение вычислений

API → только чтение
pipeline → вычисления

### воспроизводимость

обеспечивается через:

- DVC
- MLflow
- versioned configs

### изоляция сервисов

обучение моделей не влияет на API.

### масштабируемость

каждый компонент масштабируется отдельно:

- inference
- training
- pipelines

---

# 14. Технологический стек

| компонент | инструмент |
|------|------|
API | FastAPI |
validation | Pandera |
orchestration | Airflow |
experiments | MLflow |
datasets | DVC |
monitoring | Prometheus |
dashboards | Grafana |
drift | Evidently |
logging | whylogs |

---

# Итог

Система строится вокруг следующих ключевых идей:

- batch prediction pipeline
- тонкий inference API
- строгий ML lifecycle
- изолированные вычислительные процессы

Такая архитектура обеспечивает:

- низкую latency API
- воспроизводимость ML экспериментов
- управляемый релиз моделей
- масштабируемость системы.
