# 🚨 ОТЧЁТ О НАЙДЕННЫХ УТЕЧКАХ ДАННЫХ

## Дата анализа: 2026-01-10

---

## ❌ КРИТИЧНАЯ УТЕЧКА #1: Train+Test → Evaluate on Test

### Местоположение:
`sports_forecast/training/trainer_v2.py`, строки 337-343

### Описание проблемы:
```python
# 5. Обучение Prod модели (train + test)
full_features = pd.concat([train_features, test_features])
full_target = pd.concat([train_target, test_target])
model.fit(full_features, full_target)  # ← Модель видит test данные

# Вычисляем метрики prod на test
prod_metrics = self._evaluate_model(model, test_features, test_target)  # ← Оценка на тех же данных
```

### Почему это утечка:
1. Модель обучается на **train + test** данных (строка 340)
2. Затем модель оценивается на **test** данных (строка 343)
3. Модель уже видела test данные во время обучения
4. Метрики будут **искусственно завышены** (overfitting)

### Последствия:
- **LogLoss, Brier Score** → занижены (модель "знает" ответы)
- **ROC-AUC** → завышен (идеальное разделение классов)
- Реальное качество модели **неизвестно**
- В продакшене модель будет работать **хуже**, чем в валидации

---

## ⚠️  ПОТЕНЦИАЛЬНАЯ УТЕЧКА #2: Отсутствие явной сортировки по времени

### Местоположение:
`sports_forecast/training/trainer_v2.py`, строки 307-314

### Описание проблемы:
```python
# 2. Train/Test split (90/10)
test_size = cfg.get("split", {}).get("test_size", 0.1)
split_idx = int(len(features) * (1 - test_size))

train_features = features.iloc[:split_idx]  # ← Предполагается что данные отсортированы
test_features = features.iloc[split_idx:]
```

### Почему это может быть проблемой:
- Код **предполагает**, что данные уже отсортированы по времени
- Нет **явной проверки** или сортировки
- Если данные придут не отсортированными → модель будет "заглядывать в будущее"

### Рекомендация:
Добавить явную сортировку перед split:
```python
# Проверяем наличие timestamp колонки
if "match_datetime" not in df.columns and "date" not in df.columns:
    logger.warning("Нет колонки с датой! Split может быть некорректным.")

# Сортируем по времени
time_col = "match_datetime" if "match_datetime" in df.columns else "date"
df = df.sort_values(time_col).reset_index(drop=True)
```

---

## ✅ КОРРЕКТНЫЕ КОМПОНЕНТЫ

### 1. TSCV (Time Series Cross-Validation)
- Использует `sklearn.TimeSeriesSplit` ✅
- Expanding window (каждый фолд больше предыдущего) ✅
- Валидация всегда после train ✅

### 2. Формирование таргета
- Таргет вычисляется из `market_spec` ✅
- Используются только доступные на момент матча данные ✅

---

## 🛠️ РЕКОМЕНДАЦИИ ПО ИСПРАВЛЕНИЮ

### Исправление утечки #1: Два варианта

#### **Вариант A (рекомендуемый):**
```python
# Shadow модель: train через TSCV
shadow_metrics = self._train_with_tscv(model, train_features, train_target, cfg)
model.save(shadow_path, version="shadow")

# Prod модель: обучаем на train+test
full_features = pd.concat([train_features, test_features])
full_target = pd.concat([train_target, test_target])
model.fit(full_features, full_target)
model.save(prod_path, version="prod")

# Метрики prod = метрики shadow (т.к. test уже в train)
# НЕ оцениваем prod на test!
prod_metrics = shadow_metrics.copy()
prod_metrics["note"] = "prod trained on train+test, metrics from shadow"
```

#### **Вариант B (честная оценка):**
```python
# Shadow модель: train через TSCV
shadow_metrics = self._train_with_tscv(model, train_features, train_target, cfg)

# Prod модель: обучаем ТОЛЬКО на train
model.fit(train_features, train_target)
model.save(prod_path, version="prod")

# Оцениваем prod на test (честно)
prod_metrics = self._evaluate_model(model, test_features, test_target)
```

### Исправление утечки #2:
```python
def _train_model(self, df, target, target_name, cfg, run_id):
    # Явная сортировка по времени
    time_col = cfg.get("time_column", "match_datetime")
    if time_col in df.columns:
        df = df.sort_values(time_col).reset_index(drop=True)
        logger.info("✓ Данные отсортированы по %s", time_col)
    else:
        logger.warning("⚠️  Колонка %s не найдена. Split может быть некорректным.", time_col)

    # ... далее split
```

---

## 📊 ОЖИДАЕМЫЕ ИЗМЕНЕНИЯ МЕТРИК ПОСЛЕ ИСПРАВЛЕНИЯ

| Метрика | До исправления | После исправления | Комментарий |
|---------|----------------|-------------------|-------------|
| **LogLoss** | 0.0001–0.01 (подозрительно низко) | 0.50–0.65 (реалистично) | Будет хуже, но честно |
| **Brier Score** | 0.0001 | 0.15–0.25 | Будет выше (это нормально) |
| **ROC-AUC** | 1.0000 (perfect) | 0.60–0.75 | Спустится, но честно |

---

## 🎯 ВЫВОДЫ

1. ✅ **Рефакторинг X → features, y → target** завершён
2. ❌ **Найдена критичная утечка** в обучении Prod модели
3. ⚠️  **Потенциальная проблема** с сортировкой по времени
4. 🔧 **Требуется исправление** перед запуском на реальных данных

---

**Следующий шаг:** Выбрать вариант исправления (A или B) и применить.
