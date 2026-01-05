# 🚀 Feature Generation System - Быстрый старт

## 📋 Что реализовано

**Статус:** ✅ 9/12 задач завершено (75%)

### ✅ Готово:
1. Архитектура спроектирована
2. `column_utils.py` - управление категориями колонок
3. `long_format.py` - трансформации wide ↔ long
4. `BaseFeatureGenerator` - базовый класс
5. `FormFeatureGenerator` - форма игрока (FG/DP/Form)
6. `CountFeatureGenerator` - count фичей
7. `EWMFeatureGenerator` - скользящие средние
8. `FeaturePipeline` - оркестратор
9. `features_build.py` - интеграция

### Конфиги:
- `conf/features/basic.yaml` - 20+ фичей (быстро)
- `conf/features/advanced.yaml` - 1000+ фичей (production)

---

## 🎯 Как использовать

### 1. Генерация фичей

```bash
# Базовый набор (быстро, для тестирования)
uv run python -m sports_forecast.features.features_build features=basic

# Продвинутый набор (полный, для production)
uv run python -m sports_forecast.features.features_build features=advanced
```

**Результат:**
- `data/processed/{tournament}/train_wide.parquet` - для моделей тотала
- `data/processed/{tournament}/train_long.parquet` - для моделей победителя
- `data/processed/{tournament}/inference_wide.parquet`
- `data/processed/{tournament}/inference_long.parquet`

### 2. Обучение модели

```bash
# Модель победителя (использует long format)
uv run python -m sports_forecast.train tournament=uel_kz_1 model=is_home_win features=basic

# Модель тотала (использует wide format)
uv run python -m sports_forecast.train tournament=uel_kz_1 model=total_over_X features=basic
```

---

## 📊 Что генерируется

### Базовый набор (`basic.yaml`):

**Form features (12 фичей):**
- `f_pl_mins_prev_match`, `f_opp_mins_prev_match`
- `f_pl_is_dp`, `f_pl_is_fg`, `f_pl_is_form`
- `f_opp_is_dp`, `f_opp_is_fg`, `f_opp_is_form`
- `f_match_state`, `f_diff_mins_prev_match`

**EWM features (spans=[10, 20, 50]):**
- Global: `f_pl_global_ewm_10`, `f_opp_global_ewm_10`, `f_all_global_ewm_10_diff`
- H2H: `f_h2h_ewm_10_diff`
- × 3 spans = ~12 фичей

**Count features:**
- `f_pl_global_count`, `f_opp_global_count`
- `f_h2h_count`

**Итого:** ~25 фичей

### Продвинутый набор (`advanced.yaml`):

- **Spans:** [5, 10, 15, ..., 200] (40 значений)
- **Contexts:** 6 для каждого игрока + 4 H2H
- **Form + EWM + Count**

**Итого:** ~1200+ фичей 🚀

---

## 🔧 Архитектура

```
sports_forecast/features/
├── column_utils.py          # Утилиты (f_ префиксы, фильтрация)
├── long_format.py            # wide ↔ long трансформации
├── pipeline.py               # FeaturePipeline (оркестратор)
├── generators/
│   ├── base.py              # BaseFeatureGenerator
│   ├── form_generator.py    # FormFeatureGenerator
│   ├── count_generator.py   # CountFeatureGenerator
│   └── ewm_generator.py     # EWMFeatureGenerator
└── features_build.py        # Интеграция с DVC
```

---

## 📝 Конфигурация фичей

### Пример: `conf/features/basic.yaml`

```yaml
feature_prefix: "f_"
requires_long: true
create_metrics: ["diff", "total"]

generators:
  - type: "form"
    enabled: true
    fg_trigger_minutes: 480
    dp_trigger_minutes: 30
  
  - type: "ewm"
    enabled: true
    metric: "diff_ps"
    spans: [10, 20, 50]
    contexts:
      - name: "global"
        keys: ["pl"]
        players: ["pl", "opp"]
        compute_diff: true
  
  - type: "count"
    enabled: true
    shift: 1
    contexts:
      - name: "global"
        keys: ["pl"]
        players: ["pl", "opp"]
```

---

## ⚡ Примеры

### Создать свой набор фичей:

```yaml
# conf/features/my_features.yaml

feature_prefix: "f_"
requires_long: true

generators:
  - type: "ewm"
    enabled: true
    metric: "diff_ps"
    spans: [5, 10]  # Только 2 span для быстрого тестирования
    contexts:
      - name: "global"
        keys: ["pl"]
        players: ["pl"]  # Только для pl, без opp
```

Запуск:
```bash
uv run python -m sports_forecast.features.features_build features=my_features
```

### Отключить генератор:

```yaml
generators:
  - type: "ewm"
    enabled: false  # Отключаем EWM
```

---

## 🎓 Категории колонок

**META** (служебные):
- `id`, `datetime`, `tournament`, `status`
- `pl`, `opp`, `side`, `is_home` (long format)

**SOURCE** (исходные):
- `home_points`, `away_points`
- `pl_points`, `opp_points` (long format)
- `tour_num`, `weekday`, `tour_match_num`

**FEATURE** (генерируемые, префикс `f_`):
- `f_pl_global_ewm_10`
- `f_match_state`
- `f_h2h_count`

**TARGET** (создаются в train.py, префикс `target_`):
- `target_home_win`
- `target_total_over_4.5`

---

## 🔍 Дебаг

### Проверить сгенерированные фичи:

```python
import pandas as pd
from sports_forecast.features.column_utils import get_feature_columns

df = pd.read_parquet("data/processed/uel_kz_1/train_long.parquet")

# Все фичи
features = get_feature_columns(df)
print(f"Сгенерировано фичей: {len(features)}")
print(features[:10])  # Первые 10

# Проверка пропусков
print(df[features].isna().sum().sort_values(ascending=False).head())
```

### Посмотреть сводку pipeline:

```python
from omegaconf import OmegaConf
from sports_forecast.features.pipeline import FeaturePipeline

config = OmegaConf.load("conf/features/basic.yaml")
pipeline = FeaturePipeline(config)

print(pipeline)
print(pipeline.get_generator_summary())
```

---

## 📌 Следующие шаги

### TODO (осталось 2 задачи):

1. **Обновить `train.py`:**
   - Автоматически определять формат по типу модели
   - Загружать `train_wide.parquet` или `train_long.parquet`

2. **Протестировать на uel_kz_1:**
   - Запустить генерацию фичей
   - Обучить модель
   - Проверить метрики

### Запуск полного пайплайна:

```bash
# 1. Генерация фичей
uv run python -m sports_forecast.features.features_build features=basic

# 2. Обучение
uv run python -m sports_forecast.train tournament=uel_kz_1 model=is_home_win

# 3. Предсказания
uv run python -m sports_forecast.predict tournament=uel_kz_1 model=is_home_win
```

---

## 💡 Полезные команды

```bash
# Посмотреть структуру проекта
make tree DEPTH=3

# Запустить DVC пайплайн
make dvc-repro

# Запустить MLflow UI
make mlflow-ui

# Pre-commit проверки
make pre-commit
```

---

**Дата:** 2026-01-05  
**Статус:** 75% готово (9/12 задач)  
**Следующий шаг:** Обновление train.py

