# Data Pipeline Architecture

## 📊 Обзор

Пайплайн обработки данных разделен на **два независимых процесса**:

1. **Data Processing** (DVC) — воспроизводимая обработка данных
2. **Model Training** (MLflow) — гибкое обучение моделей

---

## 🔄 Data Processing Pipeline (DVC)

### Запуск

```bash
# Полный прогон всех стадий
dvc repro

# Или отдельные стадии
dvc repro ingest
dvc repro clean
dvc repro features
```

### Стадии

#### 1️⃣ Ingest: `source → raw`

**Что делает:**
- Читает CSV из `data/source/`
- Разделяет на подтурниры (если задано в `conf/source/*.yaml`)
- Извлекает букмекерские коэффициенты
- Сохраняет в `data/raw/{tournament}/`:
  - `matches.parquet` — основные данные
  - `odds.parquet` — коэффициенты (опционально)

**Конфигурация:**
- `conf/source/*.yaml` — правила split и odds
- `conf/bookmaker/*.yaml` — маппинги коэффициентов

**Команда:**
```bash
uv run python -m sports_forecast.data.ingest
```

---

#### 2️⃣ Clean: `raw → interim`

**Что делает:**
- Очистка и валидация данных
- Типизация колонок
- Генерация производных колонок (`derived_columns`)
- Сохраняет в `data/interim/{tournament}/matches_interim.parquet`

**Конфигурация:**
- `conf/tournament/*.yaml` (секция `data_clean`)

**Команда:**
```bash
uv run python -m sports_forecast.data.clean
```

---

#### 3️⃣ Features: `interim → processed`

**Что делает:**
- Генерация фичей для обучения
- Преобразование в long/wide форматы
- Split на train/inference
- Сохраняет в `data/processed/{tournament}/`:
  - `train_long.parquet` / `train_wide.parquet`
  - `inference_long.parquet` / `inference_wide.parquet`

**Конфигурация:**
- `conf/features/*.yaml`

**Команда:**
```bash
uv run python -m sports_forecast.features.features_build tournament=all
```

---

## 🎯 Model Training (Отдельный процесс)

### Почему отдельно от DVC?

**Причины:**
1. **Гибкость экспериментов** — можно запускать разные модели без перепрогона данных
2. **Скорость итераций** — не нужно ждать `dvc repro` для каждого эксперимента
3. **MLflow интеграция** — логирование экспериментов, сравнение моделей
4. **Разделение ответственности** — данные (DVC) vs модели (MLflow + S3)

### Запуск обучения

```bash
# Базовый запуск
uv run python -m sports_forecast.train \
  tournament=uel_kz_1 \
  market=total \
  market_spec=total_over \
  market_spec.line=6.5 \
  recipe=total_baseline

# С конкретными параметрами
uv run python -m sports_forecast.train \
  tournament=uel_kz_1 \
  market=total \
  market_spec=total_over \
  market_spec.line=6.5 \
  features=advanced \
  algorithm=catboost \
  hyper=optuna
```

### Сохранение моделей

**Локально (MLflow):**
```bash
# Модели автоматически логируются в MLflow
# Просмотр: mlflow ui
```

**В S3 (DVC):**
```bash
# После обучения
dvc add models/
git add models.dvc .gitignore
git commit -m "models: добавлены обученные модели"

# Отправка в S3
dvc push

# Скачивание с S3
dvc pull
```

---

## 📂 Структура данных

```
data/
├── source/          # Исходные CSV (не в git)
│   ├── uel/
│   ├── lp_eu/
│   ├── lp_by/
│   └── lp_ru/
│
├── raw/             # После ingest (DVC tracked)
│   ├── uel_kz_1/
│   │   ├── matches.parquet
│   │   └── odds.parquet
│   ├── uel_kz_2/
│   └── ...
│
├── interim/         # После clean (DVC tracked)
│   ├── uel_kz_1/
│   │   └── matches_interim.parquet
│   └── ...
│
└── processed/       # После features (DVC tracked)
    ├── uel_kz_1/
    │   ├── train_long.parquet
    │   ├── train_wide.parquet
    │   ├── inference_long.parquet
    │   └── inference_wide.parquet
    └── ...

models/              # Обученные модели (DVC tracked, MLflow logged)
└── {experiment_id}/
    ├── shadow_model.pkl
    └── prod_model.pkl
```

---

## 🔧 Конфигурация по слоям

### Ingest Layer
- **`conf/source/*.yaml`** — правила обработки источников
  - `split_strategy` — разделение на подтурниры
  - `odds` — извлечение коэффициентов

### Clean Layer
- **`conf/tournament/*.yaml`** (секция `data_clean`)
  - `column_mapping` — переименование колонок
  - `dtype_mapping` — типизация
  - `derived_columns` — генерация доп. колонок

### Features Layer
- **`conf/features/*.yaml`** — генерация фичей
  - `player_id_attr` — идентификатор игрока
  - `ewm_spans` — окна для EWM фичей

### Training Layer
- **`conf/tournament/*.yaml`** — метаданные турнира
- **`conf/market/*.yaml`** — определение рынков
- **`conf/market_spec/*.yaml`** — спецификация задач
- **`conf/algorithm/*.yaml`** — модели
- **`conf/recipe/*.yaml`** — наборы экспериментов

---

## 🚀 Типичные сценарии

### 1. Полный прогон с нуля

```bash
# 1. Обработка данных
dvc repro

# 2. Обучение моделей
uv run python -m sports_forecast.train \
  tournament=uel_kz_1 \
  market=total \
  market_spec=total_over \
  market_spec.line=6.5 \
  recipe=total_baseline

# 3. Сохранение в S3
dvc add models/
dvc push
```

### 2. Обновление данных

```bash
# Новые CSV в data/source/
dvc repro ingest
dvc repro clean
dvc repro features

# Переобучение моделей
uv run python -m sports_forecast.train <params>
```

### 3. Эксперименты с моделями

```bash
# Данные уже готовы, только обучение
uv run python -m sports_forecast.train \
  tournament=uel_kz_1 \
  market=total \
  market_spec=total_over \
  market_spec.line=6.5 \
  algorithm=catboost

uv run python -m sports_forecast.train \
  tournament=uel_kz_1 \
  market=total \
  market_spec=total_over \
  market_spec.line=6.5 \
  algorithm=lgbm

# Сравнение в MLflow UI
mlflow ui
```

---

## 📊 Версионирование

### Данные (DVC)
- `data/raw/`, `data/interim/`, `data/processed/` — tracked by DVC
- Хранятся в S3 (Yandex Cloud)
- Версионируются через git commits

### Модели (DVC + MLflow)
- **MLflow** — эксперименты, метрики, сравнение
- **DVC** — хранение артефактов в S3
- **Git** — версионирование `.dvc` файлов

### Конфигурации (Git)
- Все `conf/*.yaml` — в git
- Изменения конфигов = новые версии пайплайна

---

## ⚠️ Важные замечания

1. **DVC pipeline НЕ включает train** — обучение запускается отдельно
2. **Модели сохраняются дважды** — MLflow (метаданные) + DVC (артефакты)
3. **`data/source/` не в DVC** — слишком большие исходники, хранятся отдельно
4. **Конфиги source ≠ tournament** — разные слои, разные конфиги
5. **Odds только в ingest** — обрабатываются один раз, кладутся в `data/raw/`

---

## 🔍 Отладка

### Проверка стадий DVC

```bash
# Статус пайплайна
dvc status

# Граф зависимостей
dvc dag

# Принудительный перезапуск
dvc repro --force
```

### Логи

```bash
# Логи ingest
uv run python -m sports_forecast.data.ingest

# Логи clean
uv run python -m sports_forecast.data.clean

# Логи features
uv run python -m sports_forecast.features.features_build tournament=all
```

### MLflow UI

```bash
# Запуск UI
mlflow ui

# Открыть в браузере: http://localhost:5000
```

---

## 📚 См. также

- [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) — общая архитектура проекта
- [ARCHITECTURE_PRINCIPLES.md](ARCHITECTURE_PRINCIPLES.md) — принципы конфигурации
- [dvc.yaml](../dvc.yaml) — определение DVC pipeline
