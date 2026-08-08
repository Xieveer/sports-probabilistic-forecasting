![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![DVC](https://img.shields.io/badge/DVC-3.0+-orange.svg)
![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

# Sports Probabilistic Forecasting

MLOps-система промышленного уровня для вероятностного прогнозирования спортивных событий.
Калибровка вероятностей влияет на итоговую доходность от value-ставок в беттинге.

Проектируется как мультиспортивная платформа, а не как сервис одного турнира:
типовые соревнования с поддерживаемым источником и стандартными фичами должны
подключаться ML-инженером конфигурацией. Границы `sport`, `tournament`,
`model_pool` и `market/spec` зафиксированы в
[ADR-003](docs/architecture/adr/ADR-003-configured-multisport-portfolio.md).
Первый шаг уже реализован — проверяемый каталог
[`conf/portfolio/default.yaml`](conf/portfolio/default.yaml); он пока не заменяет
статические DVC/Airflow списки. Их подключение запланировано отдельными задачами
EPIC-003.

---

## Архитектура

```
┌─────────────────────────────────────────────────────────┐
│              DATA PIPELINE (DVC)                        │
│  source → raw → interim → processed                    │
│  Pandera validation на каждом слое                      │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│           TRAINING PIPELINE (Hydra + MLflow)            │
│  Config → Features → TSCV → Calibration → MLflow       │
│  Feature Selection · Optuna · Stacking                  │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│         INFERENCE PIPELINE (Batch + FastAPI)            │
│  materialize → Prediction Store → FastAPI API           │
│  Prometheus + Grafana · A/B Testing                     │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│           ORCHESTRATION (Airflow)                       │
│  DAG: Data Refresh · Training · Materialization ·       │
│       Monitoring · Model Promotion                      │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Установка зависимостей

Требуются Python 3.12 и [uv](https://docs.astral.sh/uv/) (менеджер окружения и зависимостей по
`pyproject.toml`). Команда `make install` выполняет `uv sync`.

```bash
make install
```

### 2. Запуск data pipeline (DVC)

```bash
make dvc-repro
```

Выполняет последовательно:
- **Ingest:** CSV/JSON → Parquet, разделение подтурниров, извлечение odds
- **Clean:** типизация, маппинг колонок, валидация (Pandera)
- **Features:** генерация признаков (EWM, Count, Form, Time)

### 3. Обучение модели

```bash
# Одиночный эксперимент
make train TOURNAMENT=uel_kz_1 MARKET=winner SPEC=winner ALG=catboost FEAT=basic

# Sweep моделей (CatBoost, LightGBM, LogReg)
make train-sweep TOURNAMENT=uel_kz_1

# Sweep с расширенными фичами
make train-sweep-full TOURNAMENT=uel_kz_1
```

### 4. MLflow UI

```bash
make mlflow-ui
# http://127.0.0.1:5000
```

### 5. FastAPI сервис (dev)

```bash
make api-dev
# http://127.0.0.1:8000/docs
```

### 6. Docker (полный стек)

```bash
make docker-build
make docker-up
# API:        http://localhost:8000
# MLflow:     http://localhost:5000
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3000 (admin/admin)
```

---

## Технологический стек

| Компонент | Инструмент |
|-----------|-----------|
| ML Framework | CatBoost, LightGBM, scikit-learn |
| Конфигурация | Hydra |
| Эксперименты | MLflow (tracking + Model Registry) |
| Data Pipeline | DVC |
| Оркестрация | Apache Airflow |
| API | FastAPI + Uvicorn |
| Валидация данных | Pandera |
| Database | PostgreSQL / SQLite |
| Мониторинг | Prometheus + Grafana |
| Контейнеризация | Docker + Docker Compose |
| Окружение и зависимости | uv (`pyproject.toml`) |
| Оптимизация | Optuna |
| Качество кода | ruff, pre-commit, pytest |

---

## Структура проекта

```
SportsProbabilisticForecasting/
├── conf/                              # Hydra конфиги
│   ├── config.yaml                    # Root config
│   ├── tournament/                    # Турниры (7 шт.)
│   ├── sport/                         # Спорты (cyberhockey, table_tennis)
│   ├── source/                        # Sources (uel, lp_*)
│   ├── market/                        # Market families (winner, total)
│   ├── market_spec/                   # Спецификации (winner, total_over, ...)
│   ├── algorithm/                     # Алгоритмы (catboost, lgbm, logreg, ...)
│   ├── features/                      # Наборы фичей (basic, advanced)
│   │   └── generators/                # Генераторы (rolling, form, time)
│   ├── feature_selection/             # Feature selection (default, aggressive)
│   ├── hyper/                         # Оптимизация (none, optuna, grid_small)
│   ├── bookmaker/                     # Букмекеры (fonbet, the_odds_api)
│   ├── betting.yaml                   # Betting simulator
│   ├── calibration.yaml               # Калибровка
│   ├── split.yaml                     # Train/test split
│   ├── metrics.yaml                   # Метрики
│   └── mlflow/                        # MLflow tracking
│
├── sports_forecast/                   # Основной пакет
│   ├── data/                          # Data pipeline
│   │   ├── ingest.py                  # source → raw
│   │   └── clean.py                   # raw → interim
│   ├── features/                      # Feature engineering
│   │   ├── features_build.py          # Orchestrator
│   │   ├── pipeline.py                # FeaturePipeline
│   │   ├── generators/                # EWM, Count, Form, Time
│   │   └── selection/                 # Feature selection (rankers + selector)
│   ├── training/                      # ML training
│   │   ├── trainer.py                 # ExperimentRunner
│   │   ├── calibration.py             # Isotonic/Sigmoid calibration
│   │   ├── models/                    # CatBoost, LGBM, LogReg, Dummy
│   │   ├── ensembles/                 # Stacking
│   │   └── optimization/              # TSCV, Optuna
│   ├── betting/                       # Betting simulation
│   │   ├── simulator.py               # BettingSimulator + BettingResult
│   │   └── odds.py                    # Odds extraction
│   ├── service/                       # FastAPI service
│   │   ├── app.py                     # FastAPI app + Prometheus
│   │   ├── routers/                   # /health, /predict
│   │   ├── db/                        # SQLAlchemy models + repository
│   │   └── schemas.py                 # Pydantic models
│   ├── monitoring/                    # Monitoring
│   │   ├── metrics.py                 # Prometheus gauges
│   │   ├── drift.py                   # PSI + KS drift detection
│   │   ├── performance.py             # ML performance tracking
│   │   └── ab_testing.py              # A/B model comparison
│   ├── orchestration/                 # Refresh/cron, post-refresh digest (Airflow hooks)
│   ├── validation/                    # Data validation (Pandera)
│   │   ├── schemas.py                 # Raw/Interim/Processed schemas
│   │   └── gates.py                   # Quality gates
│   ├── deploy/                        # Model promotion
│   ├── utils/                         # Targets, metrics, logging
│   ├── train.py                       # Training entry point
│   ├── predict.py                     # Inference
│   └── materialize.py                 # Batch prediction → DB
│
├── airflow/                           # Airflow DAGs
│   ├── dags/                          # 5 DAGs (data, train, materialize, monitor, NHL refresh)
│   ├── Dockerfile                     # Airflow worker image
│   └── docker-compose.airflow.yml     # Airflow services
│
├── monitoring/                        # Prometheus + Grafana configs
│   ├── prometheus/                    # prometheus.yml, alert_rules.yml
│   └── grafana/                       # Dashboards, datasources
│
├── data/                              # Данные (DVC-tracked)
│   ├── source/                        # Исходные CSV/JSON
│   ├── raw/                           # Parquet
│   ├── interim/                       # Очищенные
│   └── processed/                     # С фичами
│
├── models/                            # Обученные модели
├── tests/                             # ~700 pytest-тестов
├── docs/                              # Документация
│
├── dvc.yaml                           # DVC pipeline
├── params.yaml                        # DVC параметры
├── docker-compose.yml                 # Docker stack
├── Dockerfile                         # FastAPI image
├── Makefile                           # Все команды
├── pyproject.toml                     # Зависимости
└── .pre-commit-config.yaml            # Pre-commit hooks
```

---

## Data Pipeline

### Слои данных

| Слой | Путь | Описание |
|------|------|----------|
| source | `data/source/` | Исходные CSV/JSON от провайдеров |
| raw | `data/raw/` | Parquet, разделённые по подтурнирам |
| interim | `data/interim/` | Очищенные, типизированные, валидированные |
| processed | `data/processed/` | С фичами, готовые для обучения |

### Турниры

| Турнир | Спорт | Регион |
|--------|-------|--------|
| uel_kz_1, uel_kz_2 | Cyberhockey | Kazakhstan |
| uel_cz | Cyberhockey | Czech Republic |
| lp_ru | Table Tennis | Russia |
| lp_eu, lp_eu_a18 | Table Tennis | Europe |
| lp_by | Table Tennis | Belarus |

---

## Training Pipeline

### Алгоритмы

- **CatBoost** — gradient boosting (Yandex)
- **LightGBM** — gradient boosting (Microsoft)
- **Logistic Regression** — линейная модель
- **Stacking Ensemble** — мета-модель поверх base моделей
- **Dummy** — baseline (частоты классов)

### Наборы фичей

- **basic** (~50 фичей) — для быстрого тестирования
- **advanced** (~1000+ фичей) — для исследования сигналов

### Генераторы фичей

- **EWM** — экспоненциально взвешенные скользящие средние
- **Count** — счётчики матчей (global, h2h, по турниру)
- **Form** — First Game / Double Play индикаторы
- **Time** — день недели, час матча

### Процесс обучения

1. TSCV (Time Series Cross-Validation) на train данных
2. Shadow модель — обучена на последнем TSCV fold
3. Калибровка (Isotonic/Sigmoid) если ECE > порог
4. Production модель — обучена на всём датасете
5. Feature Selection — ранжирование и отбор фичей
6. Betting Simulation — ROI, threshold sweep, equity curve

### Метрики (MLflow)

**ML:** LogLoss, Brier, AUC, Accuracy, ECE, MCE
**Betting:** ROI, Profit, Sharpe, Max Drawdown, EV Realization, Hit Rate
**Артефакты:** equity_curve.csv, threshold_sweep.csv, per_bet_df.parquet, feature_ranking.csv

---

## Inference & Service

### Batch Prediction (Materialization)

```bash
make materialize TOURNAMENT=uel_kz_1
```

Загружает trained модель → инференс на upcoming матчах → сохраняет в PostgreSQL/SQLite.

### FastAPI Endpoints

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/health` | GET | Health check |
| `/predict/{match_id}` | GET | Предсказание для матча |
| `/predict/match/{match_id}/all` | GET | Все предсказания для матча |
| `/predict/upcoming/{tournament}` | GET | Upcoming матчи турнира |
| `/metrics` | GET | Prometheus метрики |

### Monitoring

- **Prometheus:** AUC, LogLoss, ECE, ROI, drift score, request latency
- **Grafana:** dashboards с автоматическим provisioning
- **Alerts:** ModelAUCDegraded, ModelLogLossHigh, DataDriftSignificant
- **A/B Testing:** сравнение prod vs shadow моделей

---

## Orchestration (Airflow)

| DAG | Описание | Расписание |
|-----|----------|------------|
| dag_data_refresh | Ingest → Clean → Features | Ежедневно |
| dag_training | Training sweep + promotion | Еженедельно |
| dag_materialize | Batch prediction | Каждые 2 часа |
| dag_monitoring | Drift detection + retraining | Ежедневно |
| notification_nhl_heavy_refresh | NHL-профиль: source/odds → ingest → clean → features → materialize → quality gate → initial Telegram fan-out | 10:00 Europe/Moscow (из `conf/notification/nhl.yaml`) |
| notification_nhl_odds_poll | NHL-профиль: один batch live Pinnacle → сравнение state → Telegram delta fan-out | Каждые 15 минут (из `conf/notification/nhl.yaml`) |

---

## Makefile команды

```bash
# Окружение
make install          # Установка зависимостей
make init             # + pre-commit hooks

# Качество кода
make lint             # ruff check
make format           # ruff format
make pre-commit       # Все хуки
make test             # pytest (~700 тестов)
make test-cov         # С coverage

# Data pipeline
make dvc-repro        # Полный pipeline
make features-basic   # Фичи (basic)
make features-advanced # Фичи (advanced)
make validate-data    # Pandera валидация

# Training
make train            # Одиночный эксперимент
make train-sweep      # Sweep моделей
make train-sweep-full # Sweep: все модели × все фичи
make promote          # Выбор лучшей модели

# Service
make api-dev          # FastAPI (dev, SQLite)
make materialize      # Batch prediction
make mlflow-ui        # MLflow UI

# Docker
make docker-build     # Собрать образы
make docker-up        # Запустить все сервисы
make docker-down      # Остановить

# Airflow
make airflow-init     # Инициализация
make airflow-up       # Запустить
make airflow-down     # Остановить
```

---

## AI-агенты и skills

Репозиторий использует переносимый AI-слой, совместимый с Codex и другими агентными
инструментами:

- `AGENTS.md` — обязательные проектные правила;
- `agents/` и `.codex/agents/` — роли и именованные профили Codex;
- `skills/` — повторяемые процессы разработки;
- `references/` — общие критерии и чек-листы;
- `evals/` — поведенческие сценарии для проверки skills;
- `.codex-plugin/` и `.agents/plugins/` — нативный plugin manifest.

Карта выбора ролей и процессов находится в
[`docs/development/ai-agents-and-skills.md`](docs/development/ai-agents-and-skills.md).
Структура проверяется командой `make ai-validate`.

## Документация

### Пользовательская (Sphinx)

Сборка из `docs/source/`: `make docs`, локальный просмотр — `make docs-serve` (см. `make help`).

### Дополнительная документация (`docs/cursor/`)

Материалы для разработки и сопровождения (архитектура, домен, расширение системы):

| Назначение | Путь |
|------------|------|
| Бизнес-контекст и функциональность | [project_info.md](docs/cursor/context/project_info.md) |
| Структура репозитория и entry points | [repo-index.md](docs/cursor/context/repo-index.md) |
| Сервис, оркестрация, данные, API | [service_orchestration_architecture.md](docs/cursor/context/service_orchestration_architecture.md) |
| Контекст фичей | [context_feature.md](docs/cursor/context/context_feature.md) |
| Композиция feature pipeline | [feature_pipeline_composition.md](docs/cursor/context/feature_pipeline_composition.md) |
| Как добавить турнир | [HOW_TO_ADD_NEW_TOURNAMENT.md](docs/cursor/context/HOW_TO_ADD_NEW_TOURNAMENT.md) |
| Как добавить рынок | [HOW_TO_ADD_NEW_MARKET.md](docs/cursor/context/HOW_TO_ADD_NEW_MARKET.md) |
| Колонки и контракты источников | [docs/cursor/source_data/](docs/cursor/source_data/) |

### Единый CLI

Точка входа [main.py](main.py): подкоманды `train`, `predict`, `promote` (тонкая обёртка над модулями `sports_forecast.*` — подробнее в [repo-index.md](docs/cursor/context/repo-index.md)).

---

## Лицензия

MIT License — см. [LICENSE](LICENSE).
