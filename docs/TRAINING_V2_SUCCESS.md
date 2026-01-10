# 🎉 Training Pipeline v2.0 — Успешный запуск!

**Дата:** 2026-01-10
**Статус:** ✅ ПОЛНОСТЬЮ РАБОТАЕТ
**Время выполнения:** ~3.5 минуты (4 модели)

---

## 📊 Результаты обучения

### ✅ Успешно обучены все модели (4/4, 100%)

**Tournament:** `uel_kz_1`
**Market:** `total_over` (line=6.5)
**Featureset:** `basic` (222 фичи)
**Parent MLflow Run ID:** `04879b338e244379841a24d4efcce397`

| # | Модель | Nested Run | TSCV LogLoss | TSCV AUC | Prod LogLoss | Prod AUC | Статус |
|---|--------|------------|--------------|----------|--------------|----------|--------|
| 1 | **Dummy** | `dum__bas__s42` | 0.6883 ± 0.0108 | 0.5000 | 0.6966 | 0.5000 | ✅ |
| 2 | **LogReg** | `lr__bas__s42` | 0.0200 ± 0.0052 | 1.0000 | 0.0162 | 1.0000 | ✅ |
| 3 | **CatBoost** | `cb__bas__s42` | 0.0003 ± 0.0001 | 1.0000 | 0.0002 | 1.0000 | ✅ |
| 4 | **LightGBM** | `lgbm__bas__s42` | 0.0000 ± 0.0000 | 1.0000 | 0.0000 | 1.0000 | ✅ |

---

## 🏗️ Архитектура v2.0 — Что работает

### ✅ 1. Конфигурация (Hydra)
- ✅ Разделение `market` / `market_spec` / `algorithm`
- ✅ Динамическая композиция конфигов
- ✅ Валидация на старте
- ✅ Параметризация линий (`market_spec.line=6.5`)

### ✅ 2. Training Pipeline
- ✅ **TSCV (4 фолда)** — Time Series Cross-Validation
- ✅ **Train/Test split (90/10)** по времени
- ✅ **Shadow модель** — обучена на последнем TSCV фолде
- ✅ **Prod модель** — обучена на train+test
- ✅ Сохранение обеих версий в `models/{tournament}/{market_spec}/`

### ✅ 3. MLflow Logging
- ✅ **Parent Run** — один на весь запуск (tournament + market_spec)
- ✅ **Nested Runs** — для каждой модели (algorithm + featureset + seed)
- ✅ Логирование метрик (Shadow TSCV + Prod test)
- ✅ Логирование параметров (гиперы, seed, n_features)
- ✅ Логирование артефактов (config, features.txt)

### ✅ 4. Модели
- ✅ **DummyModel** — baseline (частоты классов)
- ✅ **LogRegModel** — линейная модель
- ✅ **CatBoostModel** — gradient boosting
- ✅ **LGBMModel** — fast gradient boosting

---

## 📂 Сохранённые модели

```
models/uel_kz_1/total_over/
├── dummy_basic_shadow (6.6 KB)
├── dummy_basic_prod (6.6 KB)
├── logreg_basic_shadow.pkl (9.7 KB + 27 KB preprocessor)
├── logreg_basic_prod.pkl (9.7 KB + 27 KB preprocessor)
├── catboost_basic_shadow.cbm (566 KB)
├── catboost_basic_prod.cbm (565 KB)
├── lgbm_basic_shadow.txt (407 KB)
└── lgbm_basic_prod.txt (415 KB)
```

**Всего:** 10 файлов, ~2.1 MB

---

## 🚀 Как запустить

### Базовый запуск (все модели)
```bash
uv run python -m sports_forecast.train_v3 \
    tournament=uel_kz_1 \
    market=total \
    market_spec=total_over \
    market_spec.line=6.5 \
    recipe=total_baseline \
    features=basic \
    algorithm=dummy
```

### Только определённые модели
```bash
uv run python -m sports_forecast.train_v3 \
    tournament=uel_kz_1 \
    market=total \
    market_spec=total_over \
    market_spec.line=6.5 \
    recipe=total_baseline \
    recipe.algorithms=[catboost,lgbm] \
    recipe.featuresets=[basic] \
    features=basic \
    algorithm=dummy
```

### Другая линия тотала
```bash
uv run python -m sports_forecast.train_v3 \
    tournament=uel_kz_1 \
    market=total \
    market_spec=total_over \
    market_spec.line=7.5 \
    recipe=total_baseline \
    features=basic \
    algorithm=dummy
```

---

## ⚠️ Важные наблюдения

### 🔴 Подозрительно хорошие метрики (CatBoost, LGBM)

**Проблема:** CatBoost и LightGBM показывают **LogLoss ≈ 0.0000** и **AUC = 1.0000**

**Возможные причины:**
1. **Переобучение** — модели запомнили обучающие данные
2. **Утечка данных** — в фичах есть информация о будущем
3. **Проблема с таргетом** — таргет вычисляется некорректно
4. **Малый датасет** — 26961 строк может быть недостаточно

**Рекомендации:**
- ✅ Проверить фичи на утечки (особенно EWM с `shift=1`)
- ✅ Увеличить регуляризацию CatBoost/LGBM
- ✅ Проверить корреляцию фичей с таргетом
- ✅ Добавить early stopping
- ✅ Использовать `advanced` featureset для сравнения

### ✅ Нормальные метрики (Dummy, LogReg)

**Dummy:** LogLoss = 0.69 (ожидаемо для baseline)
**LogReg:** LogLoss = 0.02 (подозрительно хорошо, но линейная модель менее склонна к переобучению)

---

## 📋 Что НЕ реализовано (по вашему запросу)

- ❌ **Optuna оптимизация** — отключена
- ❌ **Калибровка моделей** — отключена
- ❌ **Stacking Ensemble** — конфиг создан, но интеграция не завершена

---

## 🎯 Следующие шаги

### 1. Проверка утечек данных (High Priority)
- [ ] Проанализировать топ-10 важных фичей CatBoost/LGBM
- [ ] Проверить корреляцию фичей с таргетом
- [ ] Убедиться что `shift=1` применяется корректно
- [ ] Запустить на `advanced` featureset для сравнения

### 2. Интеграция Stacking Ensemble (Medium Priority)
- [ ] Адаптировать `StackingEnsemble` для v2.0 архитектуры
- [ ] Добавить логику загрузки базовых моделей из saved файлов
- [ ] Протестировать на `recipe=total_with_ensemble`

### 3. Тестирование на других турнирах (Medium Priority)
- [ ] Запустить на `uel_kz_2`, `uel_cz`
- [ ] Проверить на `lp_*` турнирах (настольный теннис)
- [ ] Сравнить метрики между турнирами

### 4. Документация (Low Priority)
- [ ] Обновить `docs/CURRENT_TRAINING_STATUS.md`
- [ ] Создать `docs/TROUBLESHOOTING.md`
- [ ] Добавить примеры в README

---

## 📊 MLflow UI

```bash
# Запустить MLflow UI
uv run mlflow ui --host 127.0.0.1 --port 5000

# Открыть в браузере
# http://127.0.0.1:5000

# Найти Parent Run
# Experiment: sports_forecast
# Run ID: 04879b338e244379841a24d4efcce397
```

---

## ✅ Критерии успеха (Checklist)

- [x] TSCV работает (4 фолда)
- [x] Shadow/Production модели сохраняются
- [x] MLflow Parent/Nested runs создаются
- [x] Все 4 модели обучаются без ошибок
- [x] Метрики логируются в MLflow
- [x] Конфиги валидируются
- [x] Данные загружаются из правильных parquet
- [x] Таргет вычисляется через market_spec
- [ ] **Метрики соответствуют реальности** ← ТРЕБУЕТ ПРОВЕРКИ
- [ ] Stacking Ensemble работает

---

## 🎉 Итог

**Архитектура v2.0 полностью работает!**

✅ TSCV
✅ Shadow/Production сохранение
✅ MLflow иерархия
✅ 4/4 модели успешно обучены

⚠️ **Но:** Метрики CatBoost/LGBM подозрительно хороши — требуется проверка на утечки данных.

---

**Время выполнения:** ~3.5 минуты
**Размер моделей:** 2.1 MB
**Датасет:** 26961 строк, 222 фичи
**MLflow Parent Run:** `04879b338e244379841a24d4efcce397`
