# Архитектура системы обучения моделей

> **Статус:** ✅ УТВЕРЖДЕНО - Готово к реализации (2025-01-05)

## 📋 Требования

1. **Time Series Cross-Validation (TSCV)** - 4 фолда
2. **Optuna** для подбора гиперпараметров (НЕ фичей)
3. **Множество типов моделей:**
   - Dummy (baseline)
   - CatBoost
   - LogisticRegression
   - LightGBM
   - RNN (PyTorch Lightning) - планируется
4. **Ансамбли моделей** (voting, stacking, weighted)
5. **Калибровка** (опционально, если ECE > threshold)
6. **Две версии модели:**
   - `_shadow` - обучена на train через TSCV
   - prod - дообучена на train+test
7. **Мониторинг метрик** для обеих версий в MLflow
8. **Масштабируемость** - легко добавлять новые модели

---

## ✅ ФИНАЛЬНЫЕ РЕШЕНИЯ (утверждены):

### 1. Train/Test Split ✅
**РЕШЕНИЕ:** Вариант A - каждый турнир/подтурнир независимо, **test_size = 0.10** (10%)

**Обоснование:**
- ✅ Каждый (под)турнир имеет свою специфику
- ✅ Временная структура сохраняется
- ✅ Модели учатся на турнир-специфичных паттернах
- ✅ 10% теста достаточно для оценки качества на свежих данных

**Реализация:**
```python
# Для каждого турнира отдельно
split_idx = int(len(df) * 0.90)  # 90% train, 10% test
X_train = X[:split_idx]
X_test = X[split_idx:]
```

---

### 2. TSCV - механика ✅
**РЕШЕНИЕ:** Вариант A - по времени внутри турнира (вплоть до подтурнира)

**Обоснование:**
- ✅ TSCV работает на уровне подтурнира (uel_kz_1, uel_kz_2, uel_cz)
- ✅ Фолды: fold1(0-25%), fold2(0-50%), fold3(0-75%), fold4(0-100%)
- ✅ Каждый фолд учитывает временную последовательность

**Реализация:**
```python
from sklearn.model_selection import TimeSeriesSplit

tscv = TimeSeriesSplit(n_splits=4)
for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X_train)):
    # Обучение на fold
    ...
```

---

### 3. Ансамбли ✅
**РЕШЕНИЕ:** Вариант B - **Stacking** (мета-модель обучается на предсказаниях)

**Обоснование:**
- ✅ Stacking более мощный, чем простое усреднение
- ✅ Мета-модель (LogReg) научится оптимальной комбинации базовых моделей
- ✅ Подходит для продакшена

**Реализация:**
```python
# Базовые модели: CatBoost, LightGBM, LogReg
# Мета-модель: LogisticRegression (калиброванная по умолчанию)

# Стэкинг через out-of-fold предсказания на TSCV
```

---

### 4. Калибровка ✅
**РЕШЕНИЕ:** Вариант B - **Только если ECE > 0.1**

**Обоснование:**
- ✅ CatBoost/LightGBM обычно хорошо калиброваны
- ✅ LogReg калиброван по определению
- ✅ Проверяем ECE → калибруем при необходимости (Isotonic/Platt)

**Реализация:**
```python
ece = compute_expected_calibration_error(y_val, y_proba)
if ece > 0.1:
    calibrator = CalibratedClassifierCV(model, method='isotonic', cv='prefit')
    calibrator.fit(X_cal, y_cal)
    model = calibrator
```

---

### 5. Конфигурация моделей (YAML) ✅
**РЕШЕНИЕ:** Вариант C - **Иерархия** `single/` + `ensemble/`

**Структура:**
```
conf/model/
  single/
    dummy.yaml           # DummyClassifier baseline
    catboost.yaml        # CatBoost parameters
    lgbm.yaml            # LightGBM parameters
    logreg.yaml          # LogisticRegression parameters
  ensemble/
    stacking_win.yaml    # Stacking для is_win
    stacking_total.yaml  # Stacking для total
  is_win.yaml            # Ссылается на single/catboost.yaml (по умолчанию)
  is_home_win.yaml
  total_over.yaml
  total_under.yaml
```

**Пример `conf/model/ensemble/stacking_win.yaml`:**
```yaml
name: stacking_win
description: "Stacking ensemble для предсказания победы"
type: ensemble
ensemble_method: stacking

base_models:
  - single/catboost
  - single/lgbm
  - single/logreg

meta_model:
  type: logreg
  params:
    C: 1.0
    class_weight: balanced

target_config:
  source_key: is_win
  name: target_is_win
```

---

### 6. Shadow vs Prod ✅
**РЕШЕНИЕ:** Вариант C - **Только усреднённые метрики** по всем фолдам

**Обоснование:**
- ✅ Сохраняем средние метрики (mean) и стандартное отклонение (std)
- ✅ Shadow модель = последний фолд TSCV (обучена на максимуме данных)
- ✅ Prod модель = дообучена на train+test

**MLflow метрики:**
```python
# Shadow модель (TSCV)
mlflow.log_metric("shadow_logloss_mean", np.mean(fold_losses))
mlflow.log_metric("shadow_logloss_std", np.std(fold_losses))
mlflow.log_metric("shadow_auc_mean", np.mean(fold_aucs))
mlflow.log_metric("shadow_ece_mean", np.mean(fold_eces))

# Prod модель (test перед дообучением)
mlflow.log_metric("prod_test_logloss", test_logloss)
mlflow.log_metric("prod_test_auc", test_auc)
mlflow.log_metric("prod_test_ece", test_ece)
```

**Сохранение моделей:**
```
models/uel_kz_1/
  is_win_shadow.cbm      # Обучена на train через TSCV (последний фолд)
  is_win.cbm             # Дообучена на train+test (продакшн)
```

---

### 7. MLflow - структура ✅
**РЕШЕНИЕ:** Вариант C - **Parent/Child runs** для ансамблей

**Структура:**
```
Experiment: sports_forecast

Parent Run: uel_kz_1_stacking_win_2025-01-05
├─ Child Run: uel_kz_1_is_win_catboost_shadow
├─ Child Run: uel_kz_1_is_win_catboost_prod
├─ Child Run: uel_kz_1_is_win_lgbm_shadow
├─ Child Run: uel_kz_1_is_win_lgbm_prod
├─ Child Run: uel_kz_1_is_win_logreg_shadow
├─ Child Run: uel_kz_1_is_win_logreg_prod
├─ Child Run: uel_kz_1_stacking_meta_shadow
└─ Child Run: uel_kz_1_stacking_meta_prod
```

**Реализация:**
```python
with mlflow.start_run(run_name=f"{tournament}_stacking_{target}") as parent_run:
    mlflow.set_tag("run_type", "ensemble")
    mlflow.set_tag("ensemble_method", "stacking")

    # Обучаем базовые модели
    for model_name in base_models:
        with mlflow.start_run(run_name=f"{tournament}_{model_name}_shadow", nested=True):
            # Shadow модель
            ...
        with mlflow.start_run(run_name=f"{tournament}_{model_name}_prod", nested=True):
            # Prod модель
            ...

    # Обучаем мета-модель
    with mlflow.start_run(run_name=f"{tournament}_stacking_meta", nested=True):
        ...
```

---

### 8. Optuna - стратегия ✅
**РЕШЕНИЕ:** **Гиперпараметры тюним для Shadow модели** на TSCV

**Обоснование:**
- ✅ Optuna оптимизирует гиперпараметры на TSCV (4 фолда)
- ✅ Objective = mean(log_loss) по всем фолдам
- ✅ Prod модель использует те же гиперпараметры (просто дообучается)
- ✅ Отдельные гиперпараметры для каждого (под)турнира

**Реализация:**
```python
def objective(trial):
    params = {
        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
        'depth': trial.suggest_int('depth', 4, 12),
        'l2_leaf_reg': trial.suggest_int('l2_leaf_reg', 1, 10),
        'iterations': trial.suggest_int('iterations', 100, 1000),
    }

    # TSCV на train
    fold_losses = []
    for train_idx, val_idx in tscv.split(X_train):
        model.fit(X_train[train_idx], y_train[train_idx], **params)
        proba = model.predict_proba(X_train[val_idx])
        fold_losses.append(log_loss(y_train[val_idx], proba))

    return np.mean(fold_losses)

# Для каждого турнира отдельное study
study = optuna.create_study(
    study_name=f"{tournament}_{model_name}",
    storage=f"sqlite:///optuna/{tournament}.db",
    direction="minimize"
)
study.optimize(objective, n_trials=30)
```

---

## 🏗️ Предлагаемая архитектура классов

```
sports_forecast/training/
  __init__.py

  # Базовые классы
  base.py
    - BaseModel (abstract)
    - BaseSingleModel
    - BaseEnsembleModel

  # Конкретные модели
  models/
    __init__.py
    dummy.py       → DummyModel(BaseSingleModel)
    catboost.py    → CatBoostModel(BaseSingleModel)
    lgbm.py        → LGBMModel(BaseSingleModel)
    logreg.py      → LogRegModel(BaseSingleModel)

  # Ансамбли
  ensembles/
    __init__.py
    voting.py      → VotingEnsemble(BaseEnsembleModel)
    weighted.py    → WeightedEnsemble(BaseEnsembleModel)
    stacking.py    → StackingEnsemble(BaseEnsembleModel)

  # Оптимизация
  optimization/
    __init__.py
    optuna_optimizer.py  → OptunaOptimizer
    tscv.py              → TimeSeriesCrossValidator

  # Калибровка
  calibration.py  → ModelCalibrator

  # Основной трейнер
  trainer.py      → ModelTrainer (оркестратор)
```

---

## 🎯 Использование (концепт)

```python
# Одиночная модель
trainer = ModelTrainer(cfg)
trainer.train_single(
    model_type="catboost",
    tournament="uel_kz_1",
    target="is_win",
    use_optuna=True,
    save_shadow=True,
)

# Ансамбль
trainer.train_ensemble(
    ensemble_type="voting",
    models=["catboost", "lgbm", "logreg"],
    tournament="uel_kz_1",
    target="is_win",
)

# Все турниры
trainer.train_all_tournaments(
    model_type="catboost",
    target="is_win",
)
```

---

## 📊 Метрики для отслеживания

### Shadow модель (TSCV):
- `shadow_logloss_mean`, `_std`
- `shadow_auc_mean`, `_std`
- `shadow_accuracy_mean`, `_std`
- `shadow_brier_mean`, `_std`
- `shadow_ece_mean`, `_std`
- `shadow_fold_{i}_logloss` (для каждого фолда)

### Prod модель:
- `prod_test_logloss` (на удерживаемом тесте ДО дообучения)
- `prod_test_auc`
- `prod_test_accuracy`
- `prod_test_brier`
- `prod_test_ece`
- `prod_calibrated` (bool - была ли применена калибровка)

### Optuna (если использовалась):
- `optuna_n_trials`
- `optuna_best_value`
- `optuna_best_params` (JSON string)

---

## ⏭️ Следующие шаги:

1. ✅ Обсудить открытые вопросы (1-8)
2. ⬜ Утвердить финальную архитектуру
3. ⬜ Реализовать базовые классы
4. ⬜ Реализовать CatBoost + Dummy
5. ⬜ Добавить TSCV + Optuna
6. ⬜ Добавить Shadow/Prod сохранение
7. ⬜ Реализовать LightGBM + LogReg
8. ⬜ Реализовать Voting Ensemble
9. ⬜ Интеграция с текущим train.py
10. ⬜ Тесты

---

**Автор:** AI Assistant + User
**Дата:** 2025-01-05
**Статус:** ✅ УТВЕРЖДЕНО - Готово к реализации
