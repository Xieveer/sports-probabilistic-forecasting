# 🏗️ Архитектура системы Sports Probabilistic Forecasting

**Версия:** 2.0
**Дата:** 10 января 2026
**Статус:** Production Ready (после исправления утечки данных)

---

## 📋 Оглавление

1. [Общая архитектура](#общая-архитектура)
2. [Модули и их функции](#модули-и-их-функции)
3. [Конфигурационная система](#конфигурационная-система)
4. [MLflow интеграция](#mlflow-интеграция)
5. [Процесс обучения](#процесс-обучения)
6. [Утечки данных и исправления](#утечки-данных-и-исправления)
7. [Дальнейшие планы](#дальнейшие-планы)

---

## 🎯 Общая архитектура

### Принципы проекта

**MLOps-подход:**
- Воспроизводимость (DVC + Git)
- Конфигурируемость (Hydra)
- Модульность (чистая архитектура)
- Отслеживаемость (MLflow)
- Тестируемость (pytest + pre-commit)

### Слои системы

```
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
```

---

## 📦 Модули и их функции

### 1. `sports_forecast/data/`

**Назначение:** Обработка данных через DVC pipeline

#### `ingest.py`
- **Функция:** Конвертация CSV → Parquet
- **Вход:** `data/source/*.csv`
- **Выход:** `data/raw/*.parquet`
- **Атрибуты:** Сохраняет типы данных, метаданные

#### `clean.py`
- **Функция:** Очистка и валидация данных
- **Вход:** `data/raw/*.parquet`
- **Выход:** `data/interim/*.parquet`
- **Что делает:**
  - Типизация колонок (numeric, string, datetime)
  - Фильтрация по статусу (`finished`, `upcoming`)
  - Маппинг колонок (из конфига турнира)
  - Удаление дубликатов и NaN

### 2. `sports_forecast/features/`

**Назначение:** Генерация признаков для моделей

#### `features_build.py`
- **Функция:** Orchestrator для генерации фичей
- **Взаимодействует:** `long_format.py`, `ewm_features.py`, `count_features.py`
- **Выход:**
  - `train_long.parquet` (player vs opponent format)
  - `train_wide.parquet` (home vs away format)

#### `long_format.py`
- **Функция:** Трансформация wide → long format
- **Метод `wide_to_long()`:**
  - Параметр `player_id_attr` (из конфига, например `short_name_en`)
  - Создаёт 2 строки на матч: `(player=home, opponent=away)` + `(player=away, opponent=home)`
  - **Важно:** НЕ использует синтетические ID!

#### `ewm_features.py`
- **Функция:** Exponentially Weighted Moving features
- **Методы:**
  - `add_ewm_features()`: Скользящие средние по форме игрока
  - Группировка: по игроку, турниру, дню недели, и т.д.
- **Параметры:** `spans = [5, 10, 20]` (из конфига)

#### `count_features.py`
- **Функция:** Счётчики появлений и форм
- **Методы:**
  - `add_count_features()`: Количество матчей, форма (DP/FG/FORM)

### 3. `sports_forecast/training/`

**Назначение:** Обучение моделей и MLflow tracking

#### `trainer.py` (ранее `trainer_v2.py`)

**Класс `ExperimentRunner`:**

**Атрибуты:**
- `config`: DictConfig (parent config от Hydra)
- `project_root`: Path
- `parent_run_id`: str (MLflow parent run ID)

**Методы:**

##### `run_all_experiments() -> dict[str, bool]`
- **Назначение:** Запуск всех экспериментов из recipe
- **Логика:**
  1. Берёт `recipe.algorithms`, `recipe.featuresets`, `recipe.seeds`
  2. Для каждой комбинации запускает `_run_single_experiment()`
  3. Возвращает `{experiment_name: success}`
- **MLflow:** Создаёт nested runs для каждого эксперимента

##### `_run_single_experiment(algorithm, featureset, seed) -> bool`
- **Назначение:** Обучение одной модели
- **Шаги:**
  1. Загрузка данных (`_load_data()`)
  2. Вычисление таргета (`_compute_target()`)
  3. Сортировка по времени (`datetime`)
  4. Выбор фичей (`_select_features()`)
  5. Train/Test split (90/10)
  6. Обучение модели (`_train_model()`)
  7. Сохранение артефактов
  8. MLflow logging

##### `_select_features(df, cfg) -> (features, feature_names)`
- **Назначение:** Фильтрация колонок для обучения
- **Исключает:**
  ```python
  exclude_cols = [
      # Служебные
      "id", "match_id", "datetime", "tournament", "status", "match_state",
      # РЕЗУЛЬТАТЫ МАТЧЕЙ (утечка таргета!)
      "pl_points", "opp_points", "pl", "opp", "diff_ps", "total_ps",
      "home_points", "away_points", "total", "diff",
      # Имена команд/игроков
      "pl_short_name_en", "opp_short_name_en", "home_name", "away_name",
  ]
  ```
- **Возвращает:** Только числовые колонки, начинающиеся с `f_`

##### `_train_model(model, train_features, train_target, test_features, test_target, cfg)`
- **Назначение:** Обучение с TSCV + Shadow/Prod models
- **Шаги:**
  1. **Shadow модель:**
     - Обучение с TSCV на `train_features` + `train_target`
     - Валидация метрик (LogLoss, AUC, Brier, ECE)
     - Сохранение: `{model_name}_shadow.pkl`
  2. **Production модель:**
     - Обучение на `train_features` + `test_features` (весь датасет!)
     - Метрики копируются от Shadow (Prod не валидируется!)
     - Сохранение: `{model_name}_prod.pkl`
  3. **Анализ стабильности:**
     - `CV(LogLoss) = std / mean`
     - `stability_level`: high (<5%), medium (5-10%), low (>10%)
     - `prod_confidence`: high/medium/low
- **MLflow tags:**
  - `shadow: validated=true`
  - `prod: validated=false`

##### `_create_model(algorithm_cfg) -> Model`
- **Назначение:** Фабрика моделей
- **Поддерживает:**
  - `DummyModel` (baseline)
  - `LogRegModel` (Logistic Regression)
  - `CatBoostModel` (CatBoost)
  - `LGBMModel` (LightGBM)
  - `StackingEnsemble` (мета-модель)
- **Логика:** Использует `_target_` из конфига или name matching

##### `_create_stacking_ensemble(algorithm_cfg) -> StackingEnsemble`
- **Назначение:** Создание Stacking Ensemble
- **Логика:**
  1. Берёт `recipe.ensemble_config.stacking.base_models`
  2. Создаёт базовые модели напрямую (без Hydra compose!)
  3. Создаёт мета-модель (LogReg)
  4. Возвращает `StackingEnsemble(base_models, meta_model)`

### 4. `sports_forecast/training/models/`

**Назначение:** Реализация моделей

#### `base.py`

**Класс `BaseSingleModel`:**
- **Атрибуты:**
  - `name`: str
  - `params`: dict
  - `model_`: sklearn/catboost/lgbm модель
  - `calibrated_model_`: CalibratedClassifierCV (опционально)
  - `classes_`: np.ndarray
- **Методы:**
  - `fit(features, target)`: Обучение
  - `predict_proba(features)`: Предсказание вероятностей
  - `save(path)`: Сохранение модели
  - `load(path)`: Загрузка модели

#### `catboost.py`, `lgbm.py`, `logreg.py`, `dummy.py`
- **Наследуют:** `BaseSingleModel`
- **Переопределяют:** `_fit_implementation()`, `_preprocess_data()`

### 5. `sports_forecast/training/ensembles/`

#### `stacking.py`

**Класс `StackingEnsemble`:**
- **Атрибуты:**
  - `base_models`: list[BaseSingleModel]
  - `meta_model`: BaseSingleModel
  - `n_splits`: int (для OOF predictions)
- **Методы:**
  - `fit(features, target)`:
    1. Обучает базовые модели с TSCV
    2. Генерирует OOF predictions
    3. Обучает мета-модель на OOF
  - `predict_proba(features)`:
    1. Получает predictions от базовых моделей
    2. Передаёт в мета-модель

### 6. `sports_forecast/training/optimization/`

#### `tscv.py`

**Класс `TimeSeriesCrossValidator`:**
- **Назначение:** Time Series Cross-Validation
- **Параметры:**
  - `n_splits`: 4 (default)
  - `gap`: 0 (без gap между train/val)
- **Метод `split()`:**
  ```
  Fold 1: [====train====][val]
  Fold 2: [========train========][val]
  Fold 3: [=============train=============][val]
  Fold 4: [==================train==================][val]
  ```
- **Метод `cross_validate(model, features, target) -> dict`:**
  - Возвращает: `mean_logloss`, `std_logloss`, `mean_auc`, и т.д.

#### `optuna_optimizer.py`
- **Статус:** Пока не используется
- **План:** Гиперпараметр оптимизация через Optuna

### 7. `sports_forecast/utils/`

#### `targets.py`

**Функции:**

##### `compute_target_from_market_spec(df, market_spec, tournament_cfg, line)`
- **Назначение:** Вычисление таргета на основе конфига
- **Архитектура v2.0:**
  - Использует `market_spec.target_source_key`
  - Берёт правило из `tournament_cfg.target_sources`
- **Пример:**
  ```python
  target_source = tournament.target_sources["player_win"]
  # player_win:
  #   format: long
  #   player_column: pl_points
  #   opponent_column: opp_points
  #   comparison: greater

  target = (df[pl_points] > df[opp_points]).astype(int)
  ```

##### `get_target_name(market_spec, line) -> str`
- **Назначение:** Формирование имени таргета
- **Примеры:**
  - `target_is_win` (winner)
  - `target_total_over_6_5` (total over 6.5)

#### `log_config.py`
- **Функция:** Централизованное логирование
- **Использует:** Python `logging` module
- **Формат:** `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`

### 8. `sports_forecast/config/`

#### `validation.py`

**Функции:**

##### `validate_parent_config(cfg, project_root)`
- **Назначение:** Валидация parent конфига перед обучением
- **Проверяет:**
  - Tournament задан и имеет пути к данным
  - Market и MarketSpec заданы корректно
  - Для total: `line` обязательна
  - `data_format` задан явно
  - Recipe задан

##### `validate_experiment_config(cfg)`
- **Назначение:** Валидация конфига эксперимента
- **Проверяет:**
  - Algorithm задан и имеет `_target_`
  - Features заданы

---

## ⚙️ Конфигурационная система

### Архитектура Hydra Configs

```
conf/
├── config.yaml              # Root config
├── tournament/
│   └── uel_kz_1.yaml        # Tournament: пути, target_sources
├── market/
│   ├── winner.yaml          # Market family definition
│   └── total.yaml
├── market_spec/
│   ├── winner.yaml          # Long format
│   ├── winner_home.yaml     # Wide format
│   ├── total_over.yaml      # Parametrized by line
│   └── total_under.yaml
├── algorithm/
│   ├── dummy.yaml
│   ├── logreg.yaml
│   ├── catboost.yaml
│   ├── lgbm.yaml
│   └── stacking.yaml        # Universal ensemble
├── features/
│   ├── basic.yaml           # Basic features
│   └── advanced.yaml        # EWM features
├── recipe/
│   ├── winner_baseline.yaml
│   ├── winner_with_ensemble.yaml
│   ├── total_baseline.yaml
│   └── total_with_ensemble.yaml
├── hyper/
│   └── none.yaml            # No optimization (baseline)
├── split.yaml               # Train/test split params
├── calibration.yaml         # Calibration params (disabled)
├── metrics.yaml             # Metrics config
└── mlflow/
    └── mlflow.yaml          # MLflow tracking URI
```

### Принципы разделения

**Запрещено:**
- `algorithm` содержит `target_config`
- `market_spec` содержит `params` модели
- `tournament` содержит гиперпараметры
- Смешивание бизнес-логики разных слоёв

**Обязательно:**
- Явное указание `data_format` (long/wide)
- Явное указание `line` для total/handicap
- `target_source_key` вместо inline формул

### Ключевые конфиги

#### `conf/tournament/uel_kz_1.yaml`

```yaml
name: uel_kz_1
sport: cyberhockey
region: kazakhstan

data:
  processed_dir: data/processed/uel_kz_1
  formats:
    long: train_long.parquet
    wide: train_wide.parquet

allowed_market_specs:
  winner:
    specs: [winner_home, winner]
  total:
    lines: [3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5]
    specs: [total_over, total_under]

target_sources:
  player_win:
    format: long
    player_column: pl_points
    opponent_column: opp_points
    comparison: greater

  total_sum:
    format: wide
    home_column: home_points
    away_column: away_points
    comparison: total_over
```

#### `conf/recipe/winner_with_ensemble.yaml`

```yaml
name: winner_with_ensemble

algorithms: [dummy, logreg, catboost, lgbm, stacking]
featuresets: [basic]
seeds: [42]
hyper: none

ensemble_config:
  stacking:
    base_models: [logreg, catboost, lgbm]
```

---

## 📊 MLflow интеграция

### Иерархическая структура

```
Experiment: sports_prob_forecasting_winner
├── Parent Run: uel_kz_1__winner__player
│   ├── Tags: tournament, market_family, recipe, architecture=v2.0
│   ├── Metrics: experiments_total=5, experiments_successful=4, success_rate=0.8
│   ├── Artifacts: parent_config.yaml, data_summary.txt
│   │
│   ├── Nested Run: dum__bas__s42 (Dummy + basic)
│   │   ├── Tags: algorithm=dummy, featureset=basic, seed=42
│   │   ├── Metrics: shadow_logloss=0.6820, shadow_auc=0.5000, prod_confidence=high
│   │   ├── Artifacts: dummy_basic_shadow.pkl, dummy_basic_prod.pkl
│   │
│   ├── Nested Run: lr__bas__s42 (LogReg + basic)
│   │   ├── Metrics: shadow_logloss=0.6779, shadow_auc=0.5597
│   │   └── ...
│   │
│   ├── Nested Run: cb__bas__s42 (CatBoost + basic)
│   │   ├── Metrics: shadow_logloss=0.7110, shadow_auc=0.5290
│   │   └── ...
│   │
│   └── Nested Run: lgbm__bas__s42 (LGBM + basic)
       ├── Metrics: shadow_logloss=0.7549, shadow_auc=0.5400
       └── ...
```

### Что логируется

#### Parent Run
- **Parameters:** tournament, market, market_spec, recipe
- **Metrics:**
  - `experiments_total`: количество экспериментов
  - `experiments_successful`: успешных
  - `success_rate`: процент успеха
- **Tags:**
  - `tournament`, `market_family`, `market_spec`, `recipe`
  - `architecture=v2.0`
  - `side` (для winner/total)
  - `line` (для total)
  - `data_format` (long/wide)
- **Artifacts:**
  - `parent_config.yaml`: полный конфиг
  - `data_summary.txt`: shape, target distribution

#### Nested Run (модель)
- **Parameters:**
  - Гиперпараметры модели (из `algorithm.params`)
  - `seed`, `featureset`
- **Metrics:**
  - **Shadow model (validated):**
    - `shadow_logloss`, `shadow_auc`, `shadow_accuracy`, `shadow_brier`, `shadow_ece`
  - **Prod model (unvalidated):**
    - `prod_logloss`, `prod_auc`, `prod_accuracy`, `prod_brier`, `prod_ece`
  - **TSCV stats:**
    - `cv_logloss_mean`, `cv_logloss_std`, `cv_logloss_cv`
  - **Stability:**
    - `stability_level`: high/medium/low
    - `prod_confidence`: high/medium/low
- **Tags:**
  - `algorithm`, `featureset`, `seed`
  - `validated`: `shadow=true`, `prod=false`
  - `parent_run_id`
- **Artifacts:**
  - `{model_name}_shadow.pkl`: Shadow модель
  - `{model_name}_prod.pkl`: Production модель
  - `feature_importance.json` (для tree-based)
  - `experiment_config.yaml`: конфиг эксперимента

### Что НЕ логируется в MLflow

**Не логируем:**
- Промежуточные данные (features, predictions)
- Логи обучения (они в `logs/`)
- Сырые данные (они в DVC)
- Калибровочные модели (пока отключены)

**Зачем:**
- MLflow для метрик и артефактов моделей
- DVC для данных и воспроизводимости
- Git для кода и конфигов

---

## 🔄 Процесс обучения

### CLI команда

```bash
uv run python -m sports_forecast.train \
    tournament=uel_kz_1 \
    market=winner \
    market_spec=winner \
    recipe=winner_with_ensemble
```

### Шаги выполнения

1. **Hydra compose config**
   - Загружает и объединяет конфиги
   - Валидирует через `validate_parent_config()`

2. **MLflow Parent Run**
   - Создаёт parent run: `uel_kz_1__winner__player`
   - Логирует теги, parent_config.yaml

3. **ExperimentRunner.run_all_experiments()**
   - Перебирает `recipe.algorithms × recipe.featuresets × recipe.seeds`
   - Для каждой комбинации:

4. **_run_single_experiment()**
   - Создаёт nested run
   - Загружает данные (`train_long.parquet` или `train_wide.parquet`)
   - Вычисляет таргет (`compute_target_from_market_spec()`)
   - Сортирует по времени (`datetime`)
   - Фильтрует фичи (`_select_features()`)
   - Делит на train/test (90/10, time-based)

5. **_train_model()**
   - **Shadow model:**
     - TSCV (4 фолда) на `train_features`
     - Валидация метрик
     - Сохранение: `{name}_shadow.pkl`
   - **Prod model:**
     - Обучение на `train_features` + `test_features`
     - Копирование метрик от Shadow
     - Сохранение: `{name}_prod.pkl`
   - **Анализ стабильности:**
     - CV(LogLoss), stability_level, prod_confidence

6. **MLflow logging**
   - Метрики: shadow_*, prod_*, cv_*
   - Теги: algorithm, validated
   - Артефакты: модели, feature_importance

7. **Завершение**
   - Закрытие nested run
   - Логирование success/failure
   - Возврат к Parent Run

8. **Parent Run summary**
   - Подсчёт `experiments_successful`
   - Логирование `success_rate`
   - Закрытие Parent Run

---

## ⚠️ Утечки данных и исправления

### Проблема: Утечка таргета в фичах

**Обнаружено:** 10 января 2026

**Симптомы:**
```python
CatBoost: LogLoss = 0.0155, AUC = 1.0000  # Идеально!
LGBM:     LogLoss = 0.0000, AUC = 1.0000  # Идеально!
```

**Причина:**
В фичи попадали колонки с результатами матчей:
- `pl_points`, `opp_points` (результаты игроков)
- `diff_ps`, `total_ps` (разница и сумма)
- `home_points`, `away_points` (wide format)

**Исправление:**
```python
# trainer.py / _select_features()
result_cols = [
    # Long format
    "pl_points", "opp_points", "pl", "opp", "diff_ps", "total_ps",
    # Wide format
    "home_points", "away_points", "home_score", "away_score", "total", "diff",
    # Имена (могут leak через categorical encoding)
    "pl_short_name_en", "opp_short_name_en", "home_name", "away_name",
]
exclude_cols.extend(result_cols)
```

**Результат после исправления:**
```python
LogReg:   LogLoss = 0.6883 ± 0.0108, AUC = 0.5800  ✅
CatBoost: LogLoss = 0.7110 ± 0.0231, AUC = 0.5290  ✅
LGBM:     LogLoss = 0.7549 ± 0.0152, AUC = 0.5400  ✅
```

### Проблема: GlobalHydra в Stacking

**Ошибка:**
```
ValueError: GlobalHydra is already initialized
```

**Причина:**
Попытка вызвать `Hydra compose()` внутри уже запущенной Hydra сессии при создании базовых моделей для Stacking.

**Исправление:**
Создание базовых моделей напрямую с захардкоженными параметрами (без Hydra compose).

### Проблема: CatBoost random_seed

**Ошибка:**
```
CatBoostError: only one of the parameters random_seed, random_state should be initialized
```

**Исправление:**
Используем `random_seed` вместо `random_state` для CatBoost.

---

## 📈 Дальнейшие планы

### Ближайшие задачи (уже в архитектуре)

1. **Оптимизация гиперпараметров (Optuna)**
   - Модуль: `sports_forecast/training/optimization/optuna_optimizer.py`
   - Конфиг: `conf/hyper/optuna.yaml`
   - Интеграция: `ExperimentRunner._run_single_experiment()`

2. **Калибровка моделей**
   - Модуль: `sports_forecast/training/calibration.py`
   - Методы: Isotonic, Sigmoid
   - Статус: Отключена (пока оценка качества базовых моделей)

3. **Stacking Ensemble**
   - Статус: Реализован, но требует тестирования
   - План: Полный прогон с winner_with_ensemble / total_with_ensemble

4. **Advanced features**
   - EWM фичи работают
   - План: Оценка улучшения метрик relative to basic

### Среднесрочные задачи (требуют доработки)

1. **FastAPI Inference Endpoint**
   - Модуль: `sports_forecast/predict.py` (уже есть)
   - План: REST API для async predictions
   - Роутинг: `/predict/winner`, `/predict/total`

2. **A/B тестирование моделей**
   - Split traffic между Shadow/Prod
   - Логирование реальных результатов
   - Автоматическое переключение на лучшую модель

3. **Feature Store**
   - Централизованное хранилище фичей
   - Offline: для training
   - Online: для inference

4. **Мониторинг деградации**
   - Отслеживание prod_logloss на новых данных
   - Алерты при падении AUC/LogLoss
   - Автоматический ретрейн при drift

### Долгосрочные задачи (будущие фичи)

1. **Airflow оркестрация**
   - DAG: ingest → clean → features → train → deploy
   - Расписание: ежедневно / по событию
   - Мониторинг: Airflow UI

2. **Онлайн-обновление данных**
   - Инкрементальный ingest (добавление новых матчей)
   - Streaming features (real-time EWM)
   - Инкрементальный ретрейн

3. **Ансамбли моделей**
   - Weighted averaging
   - Blending (разные алгоритмы)
   - Multi-level stacking

4. **Временные ряды (RNN/LSTM)**
   - Sequence models для формы команды
   - Attention mechanism для важных матчей
   - Encoder-Decoder для прогнозов

5. **Reinforcement Learning**
   - RL для стратегии ставок (Kelly criterion)
   - Multi-armed bandit для A/B testing
   - Contextual bandits для маркетов

---

## 🔧 Техническая документация

### Запуск проекта

**Инициализация:**
```bash
make init        # Установка зависимостей + pre-commit
make dvc-repro   # Воспроизведение данных
```

**Обучение:**
```bash
make train       # Быстрый тест (dummy модель)

# Полный прогон
bash run_full_training.sh  # Winner + Total 6.5
```

**MLflow:**
```bash
make mlflow-ui   # Запуск UI на http://127.0.0.1:5000
make mlflow-stop # Остановка UI
```

### Структура проекта

```
SportsProbabilisticForecasting/
├── conf/                          # Hydra configs
│   ├── tournament/                # Турниры + target_sources
│   ├── market/                    # Market families
│   ├── market_spec/               # Конкретные спецификации
│   ├── algorithm/                 # Модели
│   ├── features/                  # Фичи
│   ├── recipe/                    # Планы экспериментов
│   └── config.yaml                # Root config
│
├── data/
│   ├── source/                    # CSV (не в git)
│   ├── raw/                       # Parquet (DVC)
│   ├── interim/                   # Cleaned (DVC)
│   └── processed/                 # Features (DVC)
│       ├── uel_kz_1/
│       │   ├── train_long.parquet
│       │   └── train_wide.parquet
│
├── sports_forecast/
│   ├── data/                      # DVC pipeline
│   │   ├── ingest.py
│   │   └── clean.py
│   ├── features/                  # Feature generation
│   │   ├── features_build.py
│   │   ├── long_format.py
│   │   ├── ewm_features.py
│   │   └── count_features.py
│   ├── training/                  # ML training
│   │   ├── trainer.py             # ExperimentRunner
│   │   ├── models/                # Model implementations
│   │   │   ├── base.py
│   │   │   ├── catboost.py
│   │   │   ├── lgbm.py
│   │   │   └── logreg.py
│   │   ├── ensembles/
│   │   │   └── stacking.py
│   │   └── optimization/
│   │       ├── tscv.py
│   │       └── optuna_optimizer.py
│   ├── utils/
│   │   ├── targets.py             # Target computation
│   │   └── log_config.py
│   ├── config/
│   │   └── validation.py
│   ├── train.py                   # Entry point
│   └── predict.py                 # Inference
│
├── models/                        # Saved models (DVC)
│   └── uel_kz_1/
│       └── winner/
│           ├── logreg_basic_shadow.pkl
│           └── logreg_basic_prod.pkl
│
├── mlruns/                        # MLflow tracking (не в git)
├── docs/                          # Documentation
├── tests/                         # Tests
├── dvc.yaml                       # DVC pipeline
├── Makefile                       # Shortcuts
├── pyproject.toml                 # Dependencies
└── .pre-commit-config.yaml        # Pre-commit hooks
```

---

## 📚 Полезные ссылки

- **MLflow UI:** http://127.0.0.1:5000
- **DVC:** `make dvc-repro`
- **Pre-commit:** `make pre-commit`
- **Документация:** `docs/`

---

**Версия документа:** 2.0
**Последнее обновление:** 10 января 2026
**Статус:** Production Ready
