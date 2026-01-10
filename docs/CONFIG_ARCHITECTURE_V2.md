# 🏗️ Архитектура конфигов v2.0 (Hydra + MLflow)

## 📋 Главная цель

Создать масштабируемую, валидируемую систему конфигов для ML training где:

- ✅ **Единый источник правды:** только Hydra compose, никаких `OmegaConf.load()` в коде
- ✅ **Разделение ответственности:** Market ≠ Algorithm ≠ Features
- ✅ **Масштабируемость:** добавление турниров/линий/алгоритмов без копипасты
- ✅ **Parent/Nested MLflow runs:** один parent run на (tournament, market_spec), много nested runs (algorithms)

---

## 🎯 Термины и нейминг (обязательно)

### Основные понятия

| Термин | Определение | Пример |
|--------|-------------|--------|
| **Tournament** | Источник данных + правила обработки + реестр доступных market specs | `uel_kz_1`, `lp_by` |
| **Market family** | Тип задачи БЕЗ конкретных параметров | `winner`, `total`, `handicap` |
| **MarketSpec** | Конкретная постановка задачи с параметрами | `total/over/6.5/prematch` |
| **Algorithm** | ML-алгоритм с гиперпараметрами | `catboost`, `logreg`, `lgbm` |
| **Featureset** | Набор/генерация фичей | `basic`, `advanced`, `totals_wide` |
| **Recipe** | Связка featureset + algorithms + hyper стратегия | `total_baseline`, `winner_strong` |
| **Experiment** | Одна конкретная комбинация: algorithm + featureset + hyper + seed | `cb__adv__optuna__s42` |

### ⛔ ЗАПРЕЩЕНО

- ❌ Использовать слово `model` для обозначения и market, и algorithm одновременно
- ❌ Список алгоритмов называть `models` (правильно: `algorithms`)
- ❌ Хардкодить `data_format="long"` как дефолт (только явные значения!)
- ❌ `OmegaConf.load()` внутри тренировочного кода
- ❌ Создавать `total_over_6_5.yaml`, `total_over_7_5.yaml` для каждой линии

---

## 📁 Новая структура conf/

```
conf/
├── config.yaml                    # Root config с defaults

├── tournament/                    # Источники данных + реестр market specs
│   ├── uel_kz_1.yaml             # UEL Kazakhstan Stream 1
│   ├── uel_kz_2.yaml
│   ├── lp_by.yaml                # Live Premiere Belarus
│   └── ...

├── market/                        # ⭐ НОВАЯ: Семейства рынков (без линий)
│   ├── winner.yaml               # Победитель (1x2 или H2H)
│   ├── total.yaml                # Тотал (общий)
│   └── handicap.yaml             # Фора

├── market_spec/                   # ⭐ НОВАЯ: Конкретные спецификации
│   ├── winner_home.yaml          # Победа хозяев
│   ├── winner_h2h.yaml           # Head-to-head
│   ├── total_over.yaml           # Тотал больше (параметр: line)
│   ├── total_under.yaml          # Тотал меньше (параметр: line)
│   └── handicap_home.yaml

├── algorithm/                     # ⭐ ПЕРЕИМЕНОВАНО: Алгоритмы (без market)
│   ├── dummy.yaml                # Baseline
│   ├── logreg.yaml
│   ├── catboost.yaml
│   ├── lgbm.yaml
│   └── ensemble/
│       └── stacking.yaml

├── features/                      # Фичи (без изменений)
│   ├── basic.yaml
│   ├── advanced.yaml
│   ├── totals_wide.yaml          # Специфичные для тоталов
│   └── winner_long.yaml

├── recipe/                        # ⭐ НОВАЯ: Планы экспериментов
│   ├── winner_baseline.yaml     # Дефолтный набор для winner
│   ├── total_baseline.yaml      # Дефолтный набор для total
│   └── total_strong.yaml        # Продвинутый набор для total

├── hyper/                         # ⭐ НОВАЯ: Стратегии подбора гиперов
│   ├── none.yaml                 # Без оптимизации
│   ├── grid_small.yaml           # Grid search (малый)
│   └── optuna.yaml               # Optuna optimization

├── split.yaml                     # Train/test split стратегия
├── calibration.yaml               # Настройки калибровки
├── metrics.yaml                   # Метрики для оценки
├── mlflow.yaml                    # MLflow конфигурация
└── paths.yaml                     # Пути к данным/моделям
```

---

## 🔑 Принципы разбиения (нет пересечений)

### cfg.tournament.*

**Ответственность:**
- Пути к parquet файлам (long/wide)
- Маппинги колонок, фильтры
- **Реестр допустимых market specs** (allowed_market_specs)

**Пример:**
```yaml
# conf/tournament/uel_kz_1.yaml
name: uel_kz_1
sport: cyberhockey
region: kazakhstan

# Пути к данным
data:
  processed_dir: data/processed/uel_kz_1
  formats:
    long: train_long.parquet
    wide: train_wide.parquet

# Реестр допустимых market specs
allowed_market_specs:
  winner:
    - winner_home
    - winner_h2h
  total:
    lines: [3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5]  # Киберхоккей
    specs:
      - total_over
      - total_under
```

**НЕ СОДЕРЖИТ:**
- ❌ Гиперпараметры алгоритмов
- ❌ Детали генерации фичей
- ❌ Target config (это в market_spec!)

---

### cfg.market.*

**Ответственность:**
- Определение семейства рынка (winner/total/handicap)
- Общая логика таргета (БЕЗ конкретной линии)

**Пример:**
```yaml
# conf/market/total.yaml
family: total
description: "Total goals/points market family"

# Общая логика (параметризуется в market_spec)
target_logic:
  type: comparison
  operands:
    - home_points
    - away_points
  operator: sum  # total = home + away
  compare_with: line  # Берётся из market_spec!
```

**НЕ СОДЕРЖИТ:**
- ❌ Конкретную линию (6.5, 7.5) - это в market_spec!
- ❌ side (over/under) - это в market_spec!
- ❌ Гиперпараметры алгоритмов

---

### cfg.market_spec.*

**Ответственность:**
- Конкретные параметры: side, line, scope, period
- Правило формирования таргета относительно линии
- Требуемый формат данных (long/wide)
- Источник прематч-линии (если нужен)

**Пример:**
```yaml
# conf/market_spec/total_over.yaml
name: total_over
market_family: total
side: over
line: ???  # ОБЯЗАТЕЛЬНЫЙ ПАРАМЕТР! Задаётся через CLI

# Формат данных
data_format: wide  # long или wide (ОБЯЗАТЕЛЬНО!)

# Правило таргета
target:
  source_columns:
    - home_points
    - away_points
  formula: "(home_points + away_points) > line"
  name: "target_total_over_{line}"  # Динамическое имя

# Источник прематч-линии (если нужно)
prematch_line:
  enabled: true
  source: "odds_feed"  # Колонка в данных
  timing: "close"      # close/open/pre_N_minutes
```

**НЕ СОДЕРЖИТ:**
- ❌ Гиперпараметры алгоритмов
- ❌ Детали генерации фичей

---

### cfg.algorithm.*

**Ответственность:**
- `_target_` (путь к классу модели)
- Гиперпараметры алгоритма
- Дефолтные значения для optuna

**Пример:**
```yaml
# conf/algorithm/catboost.yaml
name: catboost
_target_: sports_forecast.training.models.catboost.CatBoostModel

# Гиперпараметры
params:
  loss_function: Logloss
  eval_metric: Logloss
  iterations: 500
  learning_rate: 0.1
  depth: 6
  l2_leaf_reg: 3
  random_seed: 777
  verbose: false

# Optuna space (используется если hyper=optuna)
optuna_space:
  learning_rate:
    type: float
    low: 0.01
    high: 0.3
    log: true
  depth:
    type: int
    low: 4
    high: 12
```

**НЕ СОДЕРЖИТ:**
- ❌ target_config
- ❌ feature_selection
- ❌ data_format

---

### cfg.features.*

**Ответственность:**
- Генерация фичей (generators, spans, contexts)
- player_id_attr
- long_format_context_columns

**Пример:**
```yaml
# conf/features/advanced.yaml
name: advanced
description: "Advanced features with multiple spans"

player_id_attr: short_name_en

generators:
  - type: form
    enabled: true
    fg_trigger_minutes: 480
    
  - type: ewm
    enabled: true
    metric: diff_ps
    spans: [5, 25, 100]  # Короткое, среднее, длинное
    shift: 1
    contexts:
      - name: global
        keys: [pl]
```

**НЕ СОДЕРЖИТ:**
- ❌ Гиперпараметры алгоритмов
- ❌ Target config

---

### cfg.recipe.*

**Ответственность:**
- Какие featuresets пробуем
- Какие algorithms пробуем
- Какая hyper стратегия
- seeds/folds

**Пример:**
```yaml
# conf/recipe/total_baseline.yaml
name: total_baseline
description: "Baseline experiments for total markets"

# Что пробуем
featuresets:
  - basic
  - advanced

algorithms:
  - dummy      # Baseline
  - logreg
  - catboost
  - lgbm

# Стратегия гиперпараметров
hyper: none  # none/grid_small/optuna

# Seeds для воспроизводимости
seeds: [42, 777, 2024]

# TSCV folds
tscv_folds: 4
```

---

### cfg.hyper.*

**Ответственность:**
- Стратегия подбора гиперпараметров
- Параметры grid search / optuna

**Пример:**
```yaml
# conf/hyper/optuna.yaml
strategy: optuna
n_trials: 50
timeout: 3600  # 1 hour
direction: minimize
metric: logloss

# Optuna параметры
sampler:
  type: TPESampler
  n_startup_trials: 10
  multivariate: true

pruner:
  type: MedianPruner
  n_startup_trials: 5
  n_warmup_steps: 10
```

---

## 🎯 Как формируется таргет для прематч тоталов

### Шаг 1: MarketSpec определяет параметры

```yaml
# market_spec/total_over.yaml
side: over
line: ???  # Задаётся через CLI: market_spec.line=6.5

target:
  formula: "(home_points + away_points) > line"
  
prematch_line:
  enabled: true
  source: "odds_feed"
  timing: "close"
```

### Шаг 2: Tournament указывает источник данных

```yaml
# tournament/uel_kz_1.yaml
data:
  formats:
    wide: train_wide.parquet
    
  odds_feed:
    column: "fon_bet_odds_feed"
    format: "python_dict"
```

### Шаг 3: Код вычисляет таргет

```python
# sports_forecast/train.py: compute_target()

def compute_target(df: pd.DataFrame, market_spec: DictConfig) -> pd.Series:
    """
    Вычислить таргет на основе market_spec.
    
    Args:
        df: DataFrame с данными (home_points, away_points, ...)
        market_spec: cfg.market_spec (side, line, formula)
    
    Returns:
        Series с таргетом (0/1)
    """
    # Получаем параметры
    line = market_spec.line  # 6.5
    formula = market_spec.target.formula  # "(home_points + away_points) > line"
    
    # Вычисляем total
    total = df["home_points"] + df["away_points"]
    
    # Применяем formula
    if market_spec.side == "over":
        y = (total > line).astype(int)
    elif market_spec.side == "under":
        y = (total < line).astype(int)
    
    return y
```

**Ключевое:** Линия (6.5, 7.5) — это **ПАРАМЕТР**, а не отдельный файл!

---

## 🔍 Валидация конфигов

### На старте Parent Run

```python
def validate_parent_config(cfg: DictConfig) -> None:
    """Валидация перед запуском parent run."""
    
    # 1. Tournament задан
    assert cfg.tournament.name is not None, "tournament.name обязателен!"
    
    # 2. Market family задан
    assert cfg.market.family is not None, "market.family обязателен!"
    
    # 3. MarketSpec задан и валиден
    assert cfg.market_spec.name is not None, "market_spec.name обязателен!"
    
    # 4. Для total: line обязателен
    if cfg.market.family == "total":
        assert cfg.market_spec.line is not None, \
            "market_spec.line обязателен для total! Укажите: market_spec.line=6.5"
    
    # 5. data_format явно задан
    assert cfg.market_spec.data_format in ["long", "wide"], \
        f"market_spec.data_format должен быть 'long' или 'wide', получено: {cfg.market_spec.data_format}"
    
    # 6. Файл данных существует
    data_path = get_data_path(cfg.tournament, cfg.market_spec.data_format)
    assert data_path.exists(), f"Файл данных не найден: {data_path}"
    
    # 7. Line допустима для турнира
    if cfg.market.family == "total":
        allowed_lines = cfg.tournament.allowed_market_specs.total.lines
        assert cfg.market_spec.line in allowed_lines, \
            f"Line {cfg.market_spec.line} не допустима для {cfg.tournament.name}. " \
            f"Допустимые: {allowed_lines}"
```

### На старте каждого Nested Run

```python
def validate_experiment_config(cfg_experiment: DictConfig) -> None:
    """Валидация перед запуском experiment (nested run)."""
    
    # 1. Algorithm задан
    assert cfg_experiment.algorithm._target_ is not None, \
        "algorithm._target_ обязателен!"
    
    # 2. Featureset задан
    assert cfg_experiment.features.name is not None, \
        "features.name обязателен!"
    
    # 3. Hyper стратегия валидна
    assert cfg_experiment.hyper.strategy in ["none", "grid", "optuna"], \
        f"hyper.strategy должна быть 'none'/'grid'/'optuna', получено: {cfg_experiment.hyper.strategy}"
```

---

## 🚀 Workflow запуска

### 1. CLI команда

```bash
# Запуск parent run для total over 6.5 на uel_kz_1
uv run python -m sports_forecast.train_v2 \
    tournament=uel_kz_1 \
    market=total \
    market_spec=total_over \
    market_spec.line=6.5 \
    recipe=total_baseline
```

### 2. Parent Run инициализация

```python
# sports_forecast/train_v2.py

@hydra.main(version_base="1.3", config_path="conf", config_name="config")
def main(cfg: DictConfig) -> None:
    # 1. Валидация parent config
    validate_parent_config(cfg)
    
    # 2. Создаём parent MLflow run
    parent_run_name = f"{cfg.tournament.name}__{cfg.market.family}__{cfg.market_spec.side}_{cfg.market_spec.line}"
    
    with mlflow.start_run(run_name=parent_run_name) as parent_run:
        # Логируем parent tags
        mlflow.set_tags({
            "tournament": cfg.tournament.name,
            "market_family": cfg.market.family,
            "side": cfg.market_spec.side,
            "line": cfg.market_spec.line,
            "scope": "prematch",
        })
        
        # 3. Запускаем nested runs согласно recipe
        run_experiments(cfg, parent_run.info.run_id)
```

### 3. Nested Runs (согласно recipe)

```python
def run_experiments(cfg: DictConfig, parent_run_id: str) -> None:
    """Запуск nested runs согласно recipe."""
    
    recipe = cfg.recipe
    
    # Перебираем все комбинации
    for featureset_name in recipe.featuresets:
        for algorithm_name in recipe.algorithms:
            for seed in recipe.seeds:
                
                # Компонуем config для эксперимента через Hydra compose
                with initialize_config_dir(config_dir="conf", version_base="1.3"):
                    cfg_experiment = compose(
                        config_name="config",
                        overrides=[
                            f"tournament={cfg.tournament.name}",
                            f"market={cfg.market.family}",
                            f"market_spec={cfg.market_spec.name}",
                            f"market_spec.line={cfg.market_spec.line}",
                            f"algorithm={algorithm_name}",
                            f"features={featureset_name}",
                            f"hyper={recipe.hyper}",
                            f"seed={seed}",
                        ]
                    )
                
                # Валидация experiment config
                validate_experiment_config(cfg_experiment)
                
                # Запускаем nested run
                run_experiment(cfg_experiment, parent_run_id)
```

---

## 📊 MLflow: Теги и артефакты

### Parent Run

**Теги:**
```python
{
    "tournament": "uel_kz_1",
    "market_family": "total",
    "side": "over",
    "line": "6.5",
    "scope": "prematch",
    "recipe": "total_baseline",
}
```

**Артефакты:**
- `parent_config.yaml` - Полный конфиг parent run
- `models_comparison.csv` - Сравнение всех nested runs
- `feature_list.txt` - Список фичей (общий)

---

### Nested Run

**Имя:** `cb__adv__none__s42`
- `cb` = catboost
- `adv` = advanced features
- `none` = no hyper optimization
- `s42` = seed 42

**Теги:**
```python
{
    "algorithm": "catboost",
    "featureset": "advanced",
    "hyper": "none",
    "seed": "42",
    "split": "timeseries_v1",
}
```

**Артефакты:**
- `experiment_config.yaml` - Snapshot конфига
- `model_shadow.cbm` - Shadow модель (TSCV)
- `model_prod.cbm` - Production модель (train+test)
- `feature_importance.csv` - Важности фичей
- `calibration_curve.png` - Кривая калибровки

**Метрики:**
```python
{
    # Shadow (TSCV)
    "shadow_logloss_mean": 0.6707,
    "shadow_logloss_std": 0.0153,
    "shadow_auc_mean": 0.6025,
    
    # Production (test set)
    "prod_logloss": 0.6671,
    "prod_auc": 0.5996,
    "prod_accuracy": 0.5800,
    
    # Калибровка
    "ece_before": 0.1158,
    "ece_after": 0.0120,
}
```

---

## 🔄 План миграции (поэтапный)

### Этап 1: Создать новую структуру (не ломая старую)

1. ✅ Создать `conf/market/`
2. ✅ Создать `conf/market_spec/`
3. ✅ Создать `conf/algorithm/` (скопировать из `model/`)
4. ✅ Создать `conf/recipe/`
5. ✅ Создать `conf/hyper/`
6. ✅ Обновить `conf/tournament/*.yaml` (добавить `allowed_market_specs`)

### Этап 2: Обновить код

1. ✅ Создать `validate_parent_config()` и `validate_experiment_config()`
2. ✅ Обновить `compute_target()` для работы с `market_spec`
3. ✅ Обновить `select_features()` для работы с `features`
4. ✅ Обновить `ModelTrainer` для работы с новой архитектурой
5. ✅ Реализовать `run_experiments()` с Hydra compose

### Этап 3: Тестирование

1. ✅ Запустить с `recipe=total_baseline` на `uel_kz_1`
2. ✅ Проверить Parent/Nested runs в MLflow
3. ✅ Проверить валидацию (неправильные line, отсутствующий data_format)

### Этап 4: Миграция всех турниров

1. ✅ Обновить все `tournament/*.yaml` с новыми полями
2. ✅ Удалить старую директорию `conf/model/`
3. ✅ Обновить документацию

---

## ✅ Чек-лист готовности

- [ ] Структура `conf/` соответствует спецификации
- [ ] Все критичные поля имеют валидацию (НЕТ тихих дефолтов)
- [ ] `OmegaConf.load()` удалён из тренировочного кода
- [ ] Parent Run создаёт правильные теги
- [ ] Nested Runs имеют читаемые имена
- [ ] Конфиг каждого nested run сохраняется как артефакт
- [ ] `market_spec.line` — параметр (не файл!)
- [ ] Добавление нового турнира требует только 1 YAML файл
- [ ] Добавление новой линии требует только CLI override

---

**Дата:** 2026-01-07  
**Статус:** 🟢 В разработке (архитектура спроектирована)  
**Next:** Реализация новой структуры конфигов


