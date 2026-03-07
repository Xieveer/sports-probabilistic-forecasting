
Архитектура системы
===================

Слои системы
------------

.. code-block:: text

    ┌─────────────────────────────────────────┐
    │         DATA PIPELINE (DVC)             │
    │  source → raw → interim → processed     │
    └─────────────────────────────────────────┘
                        ↓
    ┌─────────────────────────────────────────┐
    │      TRAINING PIPELINE (Hydra)          │
    │  Config → Features → Models → MLflow    │
    └─────────────────────────────────────────┘
                        ↓
    ┌─────────────────────────────────────────┐
    │    INFERENCE PIPELINE (FastAPI)         │
    │  upcoming → features → predict → API    │
    └─────────────────────────────────────────┘

Конфигурация (Hydra)
--------------------

.. code-block:: text

    conf/
    ├── config.yaml              # Корневой конфиг
    ├── tournament/              # Турниры + target_sources
    ├── sport/                   # Настройки спорта (column_mapping, form)
    ├── source/                  # Правила ingest + split
    ├── market/                  # Семейства маркетов (winner, total)
    ├── market_spec/             # Конкретные спецификации
    ├── algorithm/               # ML-алгоритмы
    ├── features/                # Наборы фичей (basic, advanced)
    ├── bookmaker/               # Маппинги коэффициентов (fonbet)
    ├── feature_selection/       # Настройки отбора фичей
    ├── betting.yaml             # Беттинг-симулятор
    ├── calibration.yaml         # Калибровка моделей
    ├── split.yaml               # Train/test split
    ├── metrics.yaml             # Метрики оценки
    ├── database.yaml            # Настройки БД
    └── mlflow/mlflow.yaml       # MLflow tracking

Принципы разделения
~~~~~~~~~~~~~~~~~~~~

Каждая группа конфигов отвечает **только за своё**:

* ``tournament`` — данные, пути, маппинги
* ``market`` / ``market_spec`` — задача прогнозирования
* ``algorithm`` — ML-алгоритм
* ``features`` — генерация фичей

Комбинации собираются через **Hydra overrides**, а не через отдельные конфиги.

Обучение
--------

Процесс обучения одного эксперимента:

1. Загрузка ``train_long.parquet`` / ``train_wide.parquet``
2. Вычисление таргета через ``FormulaTargetBuilder``
3. Train/Test split (90/10, time-based)
4. **Shadow модель** — TSCV (4 фолда) на train → **validated**
5. Evaluation на holdout test set (ML + betting метрики)
6. Калибровка (IsotonicRegression, если ECE > порог)
7. **Prod модель** — обучение на train + test
8. Логирование в MLflow + Model Registry

Сервис (FastAPI)
-----------------

Онлайн-API **не выполняет тяжёлых вычислений**.
Все предикты вычисляются batch-процессом (``materialize.py``)
и сохраняются в витрине предсказаний (PostgreSQL/SQLite).

API эндпоинты:

* ``GET /health`` — проверка доступности
* ``GET /predict/{match_id}`` — предикт для матча
* ``GET /predict/upcoming/{tournament}`` — предикты предстоящих матчей
* ``POST /predict/on-demand`` — предикт по запросу (с кешированием)
* ``GET /metrics`` — Prometheus метрики

Мониторинг
-----------

* **Prometheus** — сбор метрик (latency, error rate, drift, performance)
* **Grafana** — дашборды и визуализация
* **Schema Drift** — отслеживание изменений в данных
* **A/B testing** — сравнение shadow и prod моделей
