# TODO Refactor — Sports Probabilistic Forecasting

> Задачи рефакторинга по результатам полного аудита проекта.
> Создано: 2026-03-07

---

## R1. ✅ ~~Исправить именование участников в конфигах и long format~~

> **Выполнено: 2026-03-07**

**Решение:** Стандартизировано единое именование участников:
- **Wide format:** `home_team` / `away_team` (для всех спортов, маппинг через `column_mapping`)
- **Long format:** `pl` / `opp` (напрямую из `home_team`/`away_team`, без промежуточного `pl_team`)
- **`player_id_attr`** — полностью удалён (не нужен: имена всегда стандартизированы)

**Изменённые файлы:**
- `conf/sport/cyberhockey.yaml` — добавлен маппинг `home_short_name_en → home_team`
- `conf/sport/table_tennis.yaml` — изменён маппинг `_home_name → home_team`
- `conf/tournament/*.yaml` (7 файлов) — `select_columns` обновлены
- `sports_forecast/features/long_format.py` — `wide_to_long()` упрощена,
  `player_id_attr` удалён, `home_team` → `pl` напрямую
- `sports_forecast/features/pipeline.py` — убрана загрузка `player_id_attr`
- `sports_forecast/features/features_build.py` — убрано логирование `player_id_attr`
- `conf/features/basic.yaml`, `conf/features/advanced.yaml` — убрана интерполяция
- `conf/features/_common.yaml` — `result_cols` обновлены
- `conf/features/generators/rolling/standard.yaml` — `h2h_side` исправлен
  (EWM: `pl_name`/`opp_name` → убрано, Count: `pl_team`/`opp_team` → убрано)
- `sports_forecast/features/column_utils.py` — `META_COLUMNS` обновлены
- `tests/test_long_format.py` — все тесты обновлены
- `tests/test_feature_generators.py` — убрана ссылка на `player_id_attr`
- `tests/test_validation.py` — колонки обновлены
- Документация (`CURRENT_TRAINING_STATUS.md`, `HOW_TO_ADD_NEW_TOURNAMENT.md`,
  `architecture.rst`)

> ⚠️ **Требуется:** перезапустить `dvc repro` для перегенерации interim/processed данных

---

## R2. 🟡 Ревизия контекстных колонок для table tennis

**Проблема:** `conf/features/_common.yaml` содержит `long_format_context_columns:
[tour_num, tour_match_num]`, но table tennis турниры не имеют этих колонок в
`select_columns`. Контексты `tour_num`, `match_num` пропускаются для TT
(soft-fail), но это может означать потерю полезных фичей.

**Что сделать:**

- [ ] **R2.1** Изучить содержимое файлов `data/interim/lp_*` — какие колонки
  реально присутствуют у table tennis
- [ ] **R2.2** Опросить пользователя: какие колонки table tennis считать
  контекстными (если есть аналоги `tour_num` / `tour_match_num`)
- [ ] **R2.3** Определить, нужны ли дополнительные генераторы фичей для table
  tennis (например, по сетам, по формату турнира)
- [ ] **R2.4** При необходимости: переопределить `long_format_context_columns`
  для table tennis (через sport-конфиг или features-конфиг)
- [ ] **R2.5** Обновить документацию: какие контексты поддерживаются для каждого
  спорта

**Файлы:**
- `conf/features/_common.yaml`
- `conf/sport/table_tennis.yaml`
- `conf/tournament/lp_*.yaml`
- `data/interim/lp_*/` (инспекция)

---

## R3. 🟢 Унифицировать datetime API (utcnow → timezone-aware)

**Проблема:** В `repository.py` и `health.py` используется `datetime.utcnow()`
(deprecated с Python 3.12). В остальном коде уже используется
`datetime.now(tz=timezone.utc)`. Нужна консистентность.

**Что сделать:**

- [ ] **R3.1** Заменить `datetime.utcnow()` → `datetime.now(tz=timezone.utc)` в:
  - `sports_forecast/service/db/repository.py`
  - `sports_forecast/service/routers/health.py`
- [ ] **R3.2** Grep по всему проекту на оставшиеся `utcnow()` — заменить все
- [ ] **R3.3** Убрать inline `from datetime import datetime` в
  `routers/predictions.py` (перенести в imports файла)

**Файлы:**
- `sports_forecast/service/db/repository.py`
- `sports_forecast/service/routers/health.py`
- `sports_forecast/service/routers/predictions.py`

---

## R4. 🟡 Реализовать рабочий monitoring DAG

**Проблема:** В `dag_monitoring.py` используется `BranchPythonOperator`,
который проверяет XCom key `quality_ok` от `check_model_quality`. Но эта
задача — `BashOperator` вызывающая placeholder-функцию `check_model_quality()`
из `gates.py`, которая всегда возвращает `True` и **не пишет XCom**.
Branching-логика никогда не сработает.

**Что сделать:**

- [ ] **R4.1** Изучить, какие модули мониторинга уже реализованы
  (`monitoring/performance.py`, `monitoring/drift.py`) и какие можно
  интегрировать в DAG
- [ ] **R4.2** Реализовать полноценную `check_model_quality()` (или заменить на
  `PythonOperator` с вызовом `evaluate_on_new_data`)
- [ ] **R4.3** Определить источник «фактических результатов» для сравнения с
  предсказаниями (resolved matches)
- [ ] **R4.4** Исправить `_decide_retrain` — использовать XCom корректно или
  переделать на `PythonOperator` с push/pull
- [ ] **R4.5** Добавить интеграцию drift detection (`detect_drift`) в DAG
- [ ] **R4.6** Протестировать DAG в изоляции (Airflow unit test или mock)

**Файлы:**
- `airflow/dags/dag_monitoring.py`
- `sports_forecast/validation/gates.py`
- `sports_forecast/monitoring/performance.py`
- `sports_forecast/monitoring/drift.py`

---

## R5. 🟡 Тесты: покрытие service layer + 90%+ coverage target

**Проблема:** Нет тестов для `sports_forecast/service/` (FastAPI routers, DB
repository, engine, schemas) и `materialize.py`. Текущее покрытие неизвестно
(вероятно < 70% по всему проекту из-за непокрытого service layer).

**Что сделать:**

- [ ] **R5.1** Добавить unit-тесты для `PredictionRepository` (CRUD: create,
  read, update, upsert, bulk_upsert, mark_stale, delete_old, get_stale)
- [ ] **R5.2** Добавить unit-тесты для DB engine (`get_session`, `init_db`,
  `reset_engine`)
- [ ] **R5.3** Добавить unit-тесты для Pydantic schemas (`PredictionResponse`,
  `HealthResponse`, `StaleInfo`)
- [ ] **R5.4** Добавить тесты для `materialize.py`
  (`_aggregate_long_predictions`, `materialize_predictions`)
- [ ] **R5.5** Добавить тесты для FastAPI endpoints (TestClient:
  `/health`, `/predict/{match_id}`, `/predict/upcoming`, `/predict/cached`,
  `/predict/cache/clear`, `/predict/stale`)
- [ ] **R5.6** Измерить текущее покрытие (`make test-cov`), довести до 90%+
- [ ] **R5.7** Рассмотреть интеграционные / e2e тесты:
  - E2E: full pipeline ingest → clean → features → train → materialize → API
  - Integration: DB + repository + FastAPI

**Файлы:**
- `tests/test_service_repository.py` (новый)
- `tests/test_service_engine.py` (новый)
- `tests/test_service_schemas.py` (новый)
- `tests/test_materialize.py` (новый)
- `tests/test_service_api.py` (новый)

---

## R6. 🟢 Проверить и почистить stacking config

**Проблема:** В `conf/algorithm/stacking.yaml` есть `params: {}` после
`base_models` и `meta_model`. Это потенциально создаёт путаницу.

**Что сделать:**

- [ ] **R6.1** Протестировать полный цикл stacking: создание через
  `ModelFactory`, обучение, predict_proba, сохранение/загрузка
- [ ] **R6.2** Проверить что `params: {}` не мешает
  (ModelFactory.create_model использует `base_models` и `meta_model` напрямую,
  не через `params`) — по аудиту: не мешает, но добавить комментарий
- [ ] **R6.3** Уточнить комментарий в `stacking.yaml`:
  `params: {}  # не используется для stacking (base_models и meta_model выше)`

**Файлы:**
- `conf/algorithm/stacking.yaml`
- `sports_forecast/training/model_factory.py`

---

## R7. 🟢 Удалить устаревший `tournament/all.yaml`

**Проблема:** `conf/tournament/all.yaml` не используется нигде в коде, Makefile,
DVC, Airflow DAGs. Содержит TODO о рефакторинге и хардкод дефолтных значений
для cyberhockey (`player_id_attr: "short_name_en"`), что некорректно для table
tennis.

**Проверено:** `grep` по всему проекту не находит ссылок на `tournament=all` или
`load_tournament_config("all")`. Конфиг мёртвый.

**Что сделать:**

- [ ] **R7.1** Удалить `conf/tournament/all.yaml`
- [ ] **R7.2** Проверить что ничего не сломалось (`make test`, `make pre-commit`)
- [ ] **R7.3** Если `features_build.py` использовал `all.yaml` ранее — убедиться
  что текущая логика (Hydra `--multirun` с перечислением турниров) работает
  корректно

**Файлы:**
- `conf/tournament/all.yaml` (удалить)
- `sports_forecast/features/features_build.py` (проверить)

---

## Приоритизация

| Задача | Критичность | Сложность | Рекомендуемый порядок |
|--------|-------------|-----------|----------------------|
| R1     | 🔴 High     | Medium    | 1-й                  |
| R3     | 🟢 Low      | Trivial   | 2-й (быстро)         |
| R7     | 🟢 Low      | Trivial   | 3-й (быстро)         |
| R6     | 🟢 Low      | Low       | 4-й (быстро)         |
| R2     | 🟡 Medium   | Medium    | 5-й (требует данных)  |
| R5     | 🟡 Medium   | High      | 6-й (объёмный)       |
| R4     | 🟡 Medium   | High      | 7-й (зависит от R5)  |
