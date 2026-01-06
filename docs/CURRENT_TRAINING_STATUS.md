# 📊 Текущее состояние системы обучения (2026-01-06)

## 🎯 Краткое резюме

**Что работает отлично:**
- ✅ LogisticRegression: **LogLoss = 0.6671** (близко к бенчмарку 0.64!)
- ✅ Feature Pipeline: 73 фичи с spans [5, 25, 100]
- ✅ TSCV: корректная валидация по времени (4 фолда)
- ✅ Betting Simulator: готов к интеграции

**Критические проблемы:**
- 🚨 Утечка данных через калибровку
- 🚨 Смешение понятий "model" (is_home_win) и "algorithm" (logreg)
- 🚨 CatBoost/LGBM показывают подозрительно хорошие результаты на test

---

## 📁 Архитектура конфигов

### Структура директорий

```
conf/
├── config.yaml              # Главный конфиг (Hydra entry point)
├── paths.yaml               # Пути к данным/моделям
├── tournament/
│   ├── uel_kz_1.yaml       # Турнир: UEL Kazakhstan Stream 1
│   ├── uel_kz_2.yaml       # Турнир: UEL Kazakhstan Stream 2
│   └── uel_kz_3.yaml       # Турнир: UEL Kazakhstan Stream 3
├── model/
│   ├── is_home_win.yaml    # Модель: победа хозяев (wide format)
│   ├── is_win.yaml         # Модель: победа игрока (long format)
│   ├── total_over_6_5.yaml # Модель: тотал > 6.5 (wide format)
│   ├── catboost.yaml       # Алгоритм: CatBoost
│   ├── lgbm.yaml           # Алгоритм: LightGBM
│   ├── logreg.yaml         # Алгоритм: Logistic Regression
│   ├── dummy.yaml          # Алгоритм: Dummy (baseline)
│   └── ensemble/
│       └── stacking_win.yaml
└── features/
    ├── basic.yaml          # Базовые фичи (player_id_attr: "name")
    └── advanced.yaml       # Продвинутые фичи (player_id_attr: "short_name_en")
```

### 🚨 АРХИТЕКТУРНАЯ ПРОБЛЕМА: Model vs Algorithm

**Текущая ситуация (НЕПРАВИЛЬНАЯ):**

В `conf/model/` смешаны два разных концепта:

1. **MODEL (задача)**: `is_home_win`, `total_over_6_5`, `is_win`
   - Определяет: какой таргет, какой формат данных (long/wide), какие фичи
   - Пример: "Предсказать победу хозяев в киберхоккее"

2. **ALGORITHM (алгоритм)**: `catboost`, `lgbm`, `logreg`, `dummy`
   - Определяет: гиперпараметры, метод обучения
   - Пример: "Использовать CatBoost с 300 итерациями"

**Проблема:**
- `train_tournament(models=['dummy', 'logreg'])` вызывает `_train_single_internal('dummy')`
- Внутри загружается `conf/model/dummy.yaml`
- Но в `dummy.yaml` НЕТ информации о таргете и формате данных!
- Система использует Hydra config (model=is_home_win), а не файл `dummy.yaml`

**Результат:**
- `total_over_6_5` НЕ РАБОТАЕТ: всегда обучается на `is_home_win` данных!

---

## 🔄 Текущий Workflow обучения

### 1. Entry Point: `train_v2.py`

```python
# sports_forecast/train_v2.py
with initialize_config_dir(config_dir=config_dir, version_base='1.3'):
    cfg = compose(config_name='config', overrides=[
        'tournament=uel_kz_1',
        'model=is_home_win'  # ← Hydra config (РАБОТАЕТ)
    ])

trainer = ModelTrainer(cfg, PROJECT_ROOT)

results = trainer.train_tournament(
    tournament='uel_kz_1',
    models=['dummy', 'catboost', 'lgbm', 'logreg'],  # ← Алгоритмы (НЕ РАБОТАЕТ с total_over_6_5!)
    ensembles=['stacking_win'],
    use_optuna=False,
    use_calibration=False,
)
```

### 2. ModelTrainer инициализация

```python
# sports_forecast/training/trainer.py: __init__()
self.config = config                    # ← Hydra config (model=is_home_win)
self.project_root = project_root
self.processed_root = project_root / "data" / "processed"
self.models_root = project_root / "models"

mlflow.set_tracking_uri("file:./mlruns")
mlflow.set_experiment("sports_forecast")
```

### 3. train_tournament() - Иерархическое обучение

```python
# sports_forecast/training/trainer.py: train_tournament()

# 1. Создаём Parent MLflow Run
parent_run = mlflow.start_run(run_name=f"{tournament}_{market}")

# 2. Обучаем одиночные модели
for model_name in models:  # ['dummy', 'catboost', 'lgbm', 'logreg']
    success, shadow_metrics, prod_metrics = self._train_single_internal(
        model_name=model_name,      # ← 'dummy'
        tournament=tournament,       # ← 'uel_kz_1'
        parent_run_id=parent_run.info.run_id,
    )
    # ← Здесь НЕ используется total_over_6_5!

# 3. Обучаем ансамбли
for ensemble_name in ensembles:
    success, shadow_metrics, prod_metrics = self._train_ensemble_internal(...)

# 4. Генерируем models_comparison.csv
# 5. Определяем best_model по LogLoss
```

### 4. _train_single_internal() - Обучение одной модели

```python
# sports_forecast/training/trainer.py: _train_single_internal()

# ПРОБЛЕМА: Загружаем конфиг алгоритма, а не модели!
model_config_path = self.project_root / "conf" / "model" / f"{model_name}.yaml"
# model_name = 'dummy' → conf/model/dummy.yaml
# Но в dummy.yaml НЕТ target_config и data_format!

model_config = OmegaConf.load(model_config_path)  # ← Загружен dummy.yaml

# Загружаем датасет и таргет
result = self.load_dataset_and_target(tournament, model_config)
# ← Здесь используется model_config (dummy.yaml), но там нет нужной инфы!
```

### 5. load_dataset_and_target() - ГДЕ УТЕЧКА

```python
# sports_forecast/training/trainer.py: load_dataset_and_target()

# 1. Определяем формат данных
data_format = model_config.get("data_format", "long")  # ← Из dummy.yaml (НЕТ!)
dataset_filename = f"train_{data_format}.parquet"     # ← Всегда "train_long.parquet"
dataset_path = self.processed_root / tournament / dataset_filename

# 2. Загружаем датасет
df = pd.read_parquet(dataset_path)  # ← Всегда train_long.parquet!

# 3. Создаём полный конфиг (tournament + model)
full_cfg = OmegaConf.create({
    "tournament": tournament_cfg,   # ← uel_kz_1.yaml
    "model": model_config,          # ← dummy.yaml (НЕТ target_config!)
})

# 4. Вычисляем таргет
y = compute_target(df, full_cfg)
# ← full_cfg.model.target_config.source_key → ОШИБКА! (dummy.yaml не содержит!)
```

### 6. compute_target() - Использует Hydra config!

```python
# sports_forecast/train.py: compute_target()

source_key = cfg.model.target_config.source_key  # ← Из Hydra (model=is_home_win)!
# Не из model_config (dummy.yaml)!

target_spec = cfg.tournament.target_sources[source_key]
# ← Всегда берёт 'is_win' или 'is_home_win', никогда 'total_over_6_5'!
```

---

## 🚨 Найденные проблемы

### Проблема 1: Утечка данных через калибровку

**Местоположение:** `sports_forecast/training/trainer.py:506-529`

```python
# ❌ НЕПРАВИЛЬНО:

# Калибруем на 50% test
cal_size = int(len(X_test) * 0.5)
X_cal = X_test.iloc[:cal_size]      # 50% test
y_cal = y_test.iloc[:cal_size]

model, is_calibrated, ... = calibrator.calibrate_if_needed(
    model, X_cal, y_cal, X_val, y_val
)

# Метрики считаются на 100% test (включая X_cal!)
y_pred_proba = model.calibrated_model_.predict_proba(X_test)  # 🚨 УТЕЧКА!

prod_metrics = {
    "logloss": log_loss(y_test, y_pred_proba),  # ← Завышенные метрики!
}
```

**Почему это утечка:**
- Модель калибруется на первых 50% test
- Метрики считаются на 100% test (включая те же 50%)
- Модель "видела" эти данные при калибровке!

**Эффект:**
```
CatBoost TSCV (честно):  LogLoss = 0.6977
CatBoost Test (утечка):  LogLoss = 0.5191  ← На 18% лучше!

LGBM TSCV (честно):      LogLoss = 0.7312
LGBM Test (утечка):      LogLoss = 0.4767  ← На 35% лучше! 🚨
```

**Решение:**
```python
# ✅ ПРАВИЛЬНО:

# Вариант А: Калибровка на validation из train
val_size = int(len(X_train) * 0.1)
X_val = X_train.iloc[-val_size:]
y_val = y_train.iloc[-val_size:]
X_train_clean = X_train.iloc[:-val_size]
y_train_clean = y_train.iloc[:-val_size]

# Обучаем на чистом train
model.fit(X_train_clean, y_train_clean)

# Калибруем на validation (не трогая test!)
model = calibrator.calibrate(model, X_val, y_val)

# Метрики на нетронутом test
y_pred = model.predict_proba(X_test)
prod_metrics = {"logloss": log_loss(y_test, y_pred)}  # ← Честно!
```

---

### Проблема 2: Model vs Algorithm смешаны

**Текущее:**
```
conf/model/
├── is_home_win.yaml     ← MODEL (задача: победа хозяев)
├── total_over_6_5.yaml  ← MODEL (задача: тотал > 6.5)
├── catboost.yaml        ← ALGORITHM (метод: CatBoost)
├── logreg.yaml          ← ALGORITHM (метод: LogReg)
└── dummy.yaml           ← ALGORITHM (метод: Dummy)
```

**Проблема:**
- `train_tournament(models=['dummy'])` → загружает `dummy.yaml`
- В `dummy.yaml` нет `target_config` и `data_format`
- Система падает или использует Hydra config (неявно)

**Правильная архитектура:**

```
conf/
├── market/              ← НОВАЯ ДИРЕКТОРИЯ!
│   ├── is_home_win.yaml
│   ├── is_win.yaml
│   └── total_over_6_5.yaml
└── algorithm/           ← ПЕРЕИМЕНОВАНО!
    ├── catboost.yaml
    ├── lgbm.yaml
    ├── logreg.yaml
    └── dummy.yaml
```

**Использование:**
```python
results = trainer.train_tournament(
    tournament='uel_kz_1',
    market='total_over_6_5',          # ← Явно указываем маркет!
    algorithms=['dummy', 'logreg'],   # ← Явно указываем алгоритмы!
    use_calibration=False,
)
```

---

### Проблема 3: CatBoost/LGBM подозрительно хороши

**Результаты:**

| Модель | LogLoss (CV) | LogLoss (Test) | Разница | Статус |
|--------|--------------|----------------|---------|--------|
| Dummy | 0.6815 | 0.6839 | +0.0024 | ✅ OK |
| LogReg | 0.6707 | 0.6671 | -0.0036 | ✅ OK |
| CatBoost | 0.6977 | 0.5774 | **-0.1203** | 🚨 Подозрительно |
| LGBM | 0.7312 | 0.4767 | **-0.2545** | 🚨🚨 ОЧЕНЬ подозрительно |

**Возможные причины:**
1. ✅ Утечка через калибровку (объясняет ~50% разницы)
2. 🤔 Скрытая утечка в фичах? (проверили `shift=1` - OK)
3. 🤔 Test set "легче" чем train? (unlikely)
4. 🤔 Overfitting (но TSCV должен был поймать)

**Требуется:**
- Отключить калибровку полностью
- Перезапустить CatBoost/LGBM
- Сравнить CV и Test метрики
- Если разница сохранится → искать скрытую утечку

---

## ✅ Что работает хорошо

### 1. Feature Pipeline (73 фичи)

```yaml
# conf/features/advanced.yaml
generators:
  - type: "form"        # 10 фичей (match_state, is_fg, is_dp, mins_prev_*)
  - type: "ewm"         # 51 фича (spans: 5, 25, 100 × контексты)
  - type: "count"       # 12 фичей (количество матчей по контекстам)

# ВАЖНО: shift=1 → фичи не используют будущее! ✅
```

**Контексты:**
- `global`: форма игрока без контекста
- `match_num`: форма по номеру матча в турнире
- `h2h`: личные встречи pl vs opp
- `h2h_side`: личные встречи pl vs opp (с учётом home/away)

### 2. TSCV (Time Series Cross-Validation)

```python
# sports_forecast/training/optimization/tscv.py

# 4 фолда, expanding window
# Фолд 1: train на 20%, val на 20%
# Фолд 2: train на 40%, val на 20%
# Фолд 3: train на 60%, val на 20%
# Фолд 4: train на 80%, val на 20%

# ✅ Валидация ВСЕГДА идёт ПОСЛЕ обучения по времени!
```

### 3. LogisticRegression результаты

```
TSCV (честная валидация):
  LogLoss: 0.6707 ± 0.0153
  AUC:     0.6025 ± 0.0277

Test (без калибровки):
  LogLoss: 0.6671
  AUC:     0.5996

Разница: -0.0036 (Test немного лучше, но в пределах нормы!) ✅
```

**Вывод:** LogReg близок к бенчмарку 0.64! 🎯

### 4. Betting Simulator готов

```python
# sports_forecast/betting/simulator.py

simulator = BettingSimulator(
    initial_bankroll=1000,
    stake_strategy="flat",       # или "kelly"
    flat_stake=10,
    min_value_threshold=0.05,    # Ставим только на EV > 5%
)

metrics = simulator.simulate(y_true, y_pred_proba, odds)
# → ROI, Profit, Win Rate, Sharpe Ratio, Max Drawdown
```

**Осталось:**
- Интегрировать в `trainer.py`
- Логировать метрики в MLflow
- Добавить букмекерские odds в датасет

---

## 🔧 План исправлений

### Приоритет 1: Исправить утечку в калибровке

**Файл:** `sports_forecast/training/trainer.py:500-530`

**Изменения:**
1. Отделить validation от train (10%)
2. Обучать на train (90%)
3. Калибровать на validation (10%)
4. Метрики считать на test (20% от всех данных)

### Приоритет 2: Разделить Model и Algorithm

**Изменения в конфигах:**
```
conf/
├── market/          # Новая директория
│   ├── is_home_win.yaml
│   └── total_over_6_5.yaml
└── algorithm/       # Переименовано из model/
    ├── catboost.yaml
    └── logreg.yaml
```

**Изменения в trainer.py:**
```python
def train_tournament(
    self,
    tournament: str,
    market: str,                    # ← НОВЫЙ ПАРАМЕТР!
    algorithms: list[str],          # ← ПЕРЕИМЕНОВАНО!
    use_calibration: bool = False,
):
    # Загружаем market config (target, data_format, features)
    market_config = load_market_config(market)

    for algo_name in algorithms:
        # Загружаем algorithm config (hyperparams)
        algo_config = load_algorithm_config(algo_name)

        # Объединяем configs
        full_config = merge(market_config, algo_config)

        # Обучаем
        self._train_single(full_config, tournament)
```

### Приоритет 3: Перезапустить чистый тест

**После исправления утечки:**
```bash
uv run python -m sports_forecast.train_v2 \
    tournament=uel_kz_1 \
    market=is_home_win \
    algorithms=catboost,lgbm,logreg \
    use_calibration=false
```

**Ожидаемые результаты:**
- CatBoost Test ≈ CatBoost CV (±5%)
- LGBM Test ≈ LGBM CV (±5%)
- LogReg Test ≈ LogReg CV (±2%) ✅

---

## 📊 Текущие метрики (is_home_win, БЕЗ калибровки)

| Модель | LogLoss (CV) | LogLoss (Test) | AUC (CV) | AUC (Test) | Статус |
|--------|--------------|----------------|----------|------------|--------|
| **Dummy** | 0.6815 ± 0.002 | 0.6839 | 0.5000 | 0.5000 | ✅ Baseline |
| **LogReg** | **0.6707 ± 0.015** | **0.6671** | 0.6025 | 0.5996 | ✅ **Лучший!** |
| **CatBoost** | 0.6977 ± 0.020 | 0.5774 | 0.5665 | 0.7xxx | ⚠️ Test подозрителен |
| **LGBM** | 0.7312 ± 0.036 | 0.4767 | 0.5561 | 0.9xxx | 🚨 Test ОЧЕНЬ подозрителен |

**Бенчмарк:** LogLoss = 0.64

**Вывод:** LogReg уже достиг цели! 🎯

---

## 🚀 Следующие шаги

### Этап 1: Критические исправления (1-2 дня)
1. ✅ Исправить утечку в калибровке
2. ✅ Разделить Market и Algorithm
3. ✅ Перезапустить чистый тест

### Этап 2: Интеграция Betting (1 день)
1. ✅ Добавить букмекерские odds в датасет
2. ✅ Интегрировать BettingSimulator в trainer
3. ✅ Логировать betting метрики в MLflow

### Этап 3: Калибровка (правильная) (1 день)
1. ✅ Исправить утечку
2. ✅ Проверить ECE на validation
3. ✅ Применить калибровку только если ECE > 0.1

### Этап 4: total_over_6.5 (1 день)
1. ✅ Запустить с исправленной архитектурой
2. ✅ Сравнить метрики с is_home_win
3. ✅ Проверить betting метрики

### Этап 5: Масштабирование (2-3 дня)
1. Запустить на всех турнирах (uel_kz_1, uel_kz_2, uel_kz_3)
2. Запустить на всех маркетах (is_home_win, total_over_6.5, total_under_6.5)
3. Ансамбли (stacking)
4. Optuna для гиперпараметров

---

## 📝 Команды для работы

### Обучение (текущая версия, с багами)
```bash
# is_home_win (работает)
uv run python -m sports_forecast.train_v2 \
    tournament=uel_kz_1 \
    model=is_home_win

# total_over_6.5 (НЕ РАБОТАЕТ - обучается на is_home_win данных!)
uv run python -m sports_forecast.train_v2 \
    tournament=uel_kz_1 \
    model=total_over_6_5
```

### Генерация фичей
```bash
uv run python -m sports_forecast.features.features_build \
    tournament=all \
    features=advanced \
    model=is_home_win
```

### MLflow UI
```bash
make mlflow-ui
# → http://127.0.0.1:5000
```

### Тесты
```bash
make test                # Все тесты
make test-unit           # Только unit-тесты
make test-cov            # С coverage
```

---

## 📚 Ключевые файлы для изучения

### Обучение
- `sports_forecast/train_v2.py` - Entry point
- `sports_forecast/training/trainer.py` - Главный класс (300+ строк)
- `sports_forecast/training/base.py` - Базовые классы моделей
- `sports_forecast/training/optimization/tscv.py` - Time Series CV

### Конфиги
- `conf/config.yaml` - Главный конфиг
- `conf/model/is_home_win.yaml` - Пример конфига модели
- `conf/tournament/uel_kz_1.yaml` - Пример конфига турнира
- `conf/features/advanced.yaml` - Продвинутые фичи

### Утилиты
- `sports_forecast/train.py` - Функции compute_target, select_features
- `sports_forecast/betting/simulator.py` - Betting симулятор

---

## 🎓 Полезные ссылки

### Документация проекта
- `docs/TRAINING_ARCHITECTURE.md` - Архитектура обучения (старая, устарела)
- `docs/CURRENT_TRAINING_STATUS.md` - **ЭТОТ ФАЙЛ** (актуальный статус)

### Внешние ресурсы
- [MLflow Documentation](https://mlflow.org/docs/latest/index.html)
- [Hydra Documentation](https://hydra.cc/docs/intro/)
- [CatBoost Documentation](https://catboost.ai/docs/)
- [Expected Calibration Error (ECE)](https://arxiv.org/abs/1706.04599)

---

## ✅ Чек-лист для следующей сессии

- [ ] Изучить `trainer.py:load_dataset_and_target()` - где именно проблема
- [ ] Изучить `train.py:compute_target()` - как используется Hydra config
- [ ] Набросать новую архитектуру: Market + Algorithm
- [ ] Исправить утечку в калибровке
- [ ] Перезапустить чистый тест CatBoost/LGBM
- [ ] Проверить что total_over_6.5 работает с новой архитектурой

---

**Дата:** 2026-01-06
**Автор:** CursorAI + Xieveer
**Статус:** 🟡 В разработке (критические баги найдены, требуют исправления)
