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

## R3. ✅ ~~Унифицировать datetime API (utcnow → timezone-aware)~~

> **Выполнено: 2026-03-07**

**Решение:** Все `datetime.utcnow()` заменены на `datetime.now(tz=timezone.utc)`.
Inline импорты в `predictions.py` перенесены в начало файла.
Также исправлен `datetime.now()` → `datetime.now(tz=timezone.utc)` в fallback-ветке.

**Изменённые файлы:**
- `sports_forecast/service/db/repository.py` — `utcnow()` → `now(tz=timezone.utc)`
- `sports_forecast/service/routers/health.py` — `utcnow()` → `now(tz=timezone.utc)`
- `sports_forecast/service/routers/predictions.py` — inline imports → top-level,
  `datetime.now()` → `datetime.now(tz=timezone.utc)`

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

## R6. ✅ ~~Проверить и почистить stacking config~~

> **Выполнено: 2026-03-07**

**Решение:**
- `params: {}` — подтверждено: не мешает, добавлен поясняющий комментарий
- Написаны 7 тестов для StackingEnsemble (create, fit, predict_proba, save/load, ошибки)
- **Обнаружен и исправлен баг** в `StackingEnsemble.load()`: glob на верхнем уровне
  находил директорию вместо файла модели. Исправлено — теперь load ищет файлы
  внутри поддиректорий и фильтрует preprocessor/calibration артефакты.

**Изменённые файлы:**
- `conf/algorithm/stacking.yaml` — расширенный комментарий к `params: {}`
- `sports_forecast/training/ensembles/stacking.py` — исправлен `load()` (баг-фикс)
- `tests/test_training.py` — добавлены `TestStackingEnsemble` (7 тестов)

---

## R7. ✅ ~~Удалить устаревший `tournament/all.yaml`~~

> **Выполнено: 2026-03-07**

**Решение:** `conf/tournament/all.yaml` удалён. Grep подтвердил отсутствие
ссылок на этот конфиг в коде, Makefile, DVC, Airflow DAGs.
`features_build.py` использует Hydra `--multirun` с перечислением конкретных
турниров — `all.yaml` не участвовал.

**Изменённые файлы:**
- `conf/tournament/all.yaml` — удалён

---

## R8. ✅ ~~Исправить `fillna(0)` для int-колонок в `_apply_dtype_conversion`~~

> **Выполнено: 2026-03-08**

**Проблема:** `_apply_dtype_conversion` использовал `fillna(0).astype("int64")`
для числовых int-колонок (включая `home_sets`, `away_sets`, `home_points`,
`away_points`). Для upcoming-матчей это превращало `NaN`-счёт в `0-0`, что
является валидным результатом и искажает downstream-логику.

**Решение:** Заменено на nullable `Int64` (`pd.Int64Dtype()`), который корректно
хранит `<NA>` вместо заполнения нулями.

**Изменённые файлы:**
- `sports_forecast/data/clean.py` — `fillna(0).astype("int64")` → `.astype("Int64")`

---

## R9. 🟡 Ревизия fillna-стратегий в feature pipeline

**Проблема:** Несколько мест используют `fillna(0)` или `fillna(max_rank)` без
документирования причин. Это может искажать данные: ноль — осмысленное значение,
а замена пропуска на ноль подразумевает «нулевой показатель», а не «нет данных».

**Список мест:**

### R9.1. ✅ ~~`ewm_generator.py` — `fillna(0.0)` в EWM-цепочке~~

> **Выполнено: 2026-03-10**

**Было:**
```python
x.shift(shift).ffill().fillna(0.0).ewm(span=..., ignore_na=True).mean()
```

**Стало:**
```python
x.shift(shift).ewm(span=..., min_periods=..., ignore_na=True).mean()
```

**Решение:** Убраны `ffill()` и `fillna(0.0)`. `ignore_na=True` корректно
обрабатывает оба типа NaN:
- **Cold-start** (< min_periods матчей) → EWM = NaN (модель видит «нет данных»)
- **Upcoming-матчи** (metric = NaN из-за отсутствия счёта) → EWM carry-forward
  от последнего known результата

Дополнительно добавлена **warmup-фича** `pl_ewm_warmup` / `opp_ewm_warmup`:
- Formula: `min(n_observed / threshold, 1.0)` ∈ [0, 1]
- threshold=10 (конфигурируемо)
- Показывает модели уровень достоверности EWM-оценки

**Изменённые файлы:**
- `sports_forecast/features/generators/ewm_generator.py` — рефакторинг
  `_calculate_ewm()`, добавлен `_generate_warmup_features()`
- `conf/features/generators/rolling/standard.yaml` — добавлен `warmup` блок
- `conf/features/generators/rolling/minimal.yaml` — добавлен `warmup` блок
- `tests/test_feature_generators.py` — 7 новых тестов (cold-start NaN,
  upcoming NaN carry-forward, no-fillna-zero, warmup values, warmup with NaN)

### R9.2. ✅ ~~`mutual_info_ranker.py` — `X.fillna(0)` перед MI scoring~~

> **Выполнено: 2026-03-11**

**Было:**
```python
X_filled = X.fillna(0)
```

**Стало:**
```python
X_filled = X.fillna(X.median()).fillna(0.0)  # median + fallback for all-NaN
```

**Решение:** `fillna(0)` → `fillna(X.median())`. Медиана устойчива к выбросам
и не смешивает «нет данных» с «нулевой показатель». Fallback `fillna(0.0)` для
теоретически возможных полностью NaN-колонок. Добавлено логирование при >0% NaN.

**Изменённые файлы:**
- `sports_forecast/features/selection/mutual_info_ranker.py` — median imputation
- `tests/test_feature_selection.py` — 3 новых теста (NaN median, all-NaN column,
  no-fillna-zero degradation)

### R9.3. ✅ ~~`selector.py` — агрегация рангов/скоров с fillna~~

> **Выполнено: 2026-03-11**

**Было:**
```python
merged[score_cols] = merged[score_cols].fillna(0.0)
```

**Стало:**
```python
for col in score_cols:
    merged[col] = merged[col].fillna(merged[col].min())
merged[score_cols] = merged[score_cols].fillna(0.0)  # fallback
```

**Решение:** `fillna(0.0)` → `fillna(per_column_min)`. Согласовано с подходом
для рангов (`fillna(max_rank)`): отсутствие в ранкере = худший наблюдаемый score
данного метода. Применено в двух местах: `_aggregate_rank_average()` и
`_build_aggregated_df()`.

**Изменённые файлы:**
- `sports_forecast/features/selection/selector.py` — per-method min score
- `tests/test_feature_selection.py` — 4 новых теста (missing feature min score,
  no NaN when full coverage, build_aggregated_df min score)

### R9.4. `logreg.py` — `SimpleImputer(strategy="mean")` для numeric

```python
numeric_pipeline = Pipeline([
    ("imputer", SimpleImputer(strategy="mean")),
    ("scaler", StandardScaler()),
])
```

- **Контекст:** Стандартный подход для LogReg. Mean-импутация корректна,
  но может искажать распределение при большой доле пропусков.
- **Риск:** Низкий. Это internal model preprocessing, не влияет на данные
  для других моделей (CatBoost/LGBM обрабатывают NaN нативно).
- [ ] При необходимости: добавить фичу-индикатор пропуска (`add_indicator=True`)

**Файлы:**
- `sports_forecast/features/generators/ewm_generator.py`
- `sports_forecast/features/selection/mutual_info_ranker.py`
- `sports_forecast/features/selection/selector.py`
- `sports_forecast/training/models/logreg.py`

---

## Приоритизация

| Задача | Критичность | Сложность | Рекомендуемый порядок |
|--------|-------------|-----------|----------------------|
| R1     | 🔴 High     | Medium    | 1-й ✅               |
| R3     | 🟢 Low      | Trivial   | 2-й ✅               |
| R7     | 🟢 Low      | Trivial   | 3-й ✅               |
| R6     | 🟢 Low      | Low       | 4-й ✅               |
| R8     | 🔴 High     | Trivial   | 5-й ✅               |
| R9     | 🟡 Medium   | Medium    | 6-й (R9.1-3 ✅, R9.4 ост.)|
| R2     | 🟡 Medium   | Medium    | 7-й (требует данных) |
| R5     | 🟡 Medium   | High      | 8-й (объёмный)       |
| R4     | 🟡 Medium   | High      | 9-й (зависит от R5) |
