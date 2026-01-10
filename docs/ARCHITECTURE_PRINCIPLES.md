# 🏗️ Принципы архитектуры конфигов v2.0

**Дата:** 2026-01-10
**Версия:** 2.0

---

## 🎯 Главный принцип: Разделение ответственности

Каждая группа конфигов отвечает **только за своё**:

| Директория | Ответственность | Независима от |
|------------|-----------------|---------------|
| `tournament/` | Данные: пути, маппинги, реестр market_specs | Алгоритмов, фичей |
| `market/` | Семейство рынка: winner, total, handicap | Алгоритмов, фичей |
| `market_spec/` | Конкретная задача: side, line, format | Алгоритмов, фичей |
| `algorithm/` | **Алгоритм ML: dummy, logreg, catboost, stacking** | **Маркетов, турниров** |
| `features/` | Генерация фичей: basic, advanced | Алгоритмов, маркетов |
| `recipe/` | План эксперимента: какие алгоритмы + фичи пробовать | Турниров |

---

## ✅ ПРАВИЛЬНО: Algorithm независим от задачи

### Пример: `conf/algorithm/stacking.yaml`

```yaml
name: stacking
description: "Stacking ensemble: base models + meta-model"
_target_: sports_forecast.training.ensembles.stacking.StackingEnsemble

# Мета-модель
meta_model:
  type: logreg
  params:
    C: 0.1
    solver: lbfgs

# НЕ указываем base_models здесь!
# Они определяются в recipe
```

**Почему правильно:**
- ✅ `stacking` можно использовать для **любого маркета** (winner, total, handicap)
- ✅ `stacking` можно использовать для **любого турнира**
- ✅ Базовые модели определяются в `recipe`, который зависит от задачи

---

## ❌ НЕПРАВИЛЬНО: Привязка алгоритма к маркету

### Анти-пример: `conf/algorithm/stacking_total.yaml`

```yaml
name: stacking_total  # ❌ Привязка к маркету!
base_models:
  - catboost
  - lgbm
  - logreg
```

**Почему неправильно:**
- ❌ Нужно дублировать конфиг для каждого маркета (`stacking_winner`, `stacking_handicap`)
- ❌ Нарушает принцип DRY (Don't Repeat Yourself)
- ❌ Невозможно переиспользовать для других задач

---

## 🎯 Как правильно: Recipe определяет комбинации

### `conf/recipe/total_with_ensemble.yaml`

```yaml
name: total_with_ensemble

# Алгоритмы (порядок важен!)
algorithms:
  - catboost
  - lgbm
  - logreg
  - stacking  # ✅ Используем универсальный stacking

# Конфигурация ансамбля
ensemble_config:
  stacking:
    base_models:
      - catboost  # ✅ Базовые модели указываем в recipe
      - lgbm
      - logreg
```

**Преимущества:**
- ✅ `algorithm/stacking.yaml` остаётся универсальным
- ✅ Для `winner` можно создать `recipe/winner_with_ensemble.yaml` с другими базовыми моделями
- ✅ Легко экспериментировать с разными комбинациями

---

## 📋 Примеры правильных конфигов

### ✅ Algorithm: Универсальный класс модели

```yaml
# conf/algorithm/catboost.yaml
name: catboost
_target_: sports_forecast.training.models.catboost.CatBoostModel
params:
  iterations: 1000
  depth: 6
  learning_rate: 0.03
```

**Независим от:**
- ❌ Маркета (winner/total/handicap)
- ❌ Турнира (uel_kz_1/lp_by)
- ❌ Фичей (basic/advanced)

### ✅ Market Spec: Конкретная задача

```yaml
# conf/market_spec/total_over.yaml
name: total_over
family: total
side: over
data_format: wide
# line задаётся через CLI: market_spec.line=6.5
```

**Независим от:**
- ❌ Алгоритма (catboost/lgbm)
- ❌ Фичей (basic/advanced)

### ✅ Recipe: План эксперимента

```yaml
# conf/recipe/total_baseline.yaml
name: total_baseline
algorithms: [dummy, logreg, catboost, lgbm]
featuresets: [basic, advanced]
```

**Зависит от:**
- ✅ Маркета (total) — указан в имени
- ❌ Турнира — можно применить к любому
- ❌ Линии — параметризуется через CLI

---

## 🔄 Потоки зависимостей

### Правильная иерархия (снизу вверх)

```
CLI запуск
    ↓
Recipe (план: какие алгоритмы + фичи)
    ↓
Algorithm (универсальный класс модели) + Features (генерация фичей)
    ↓
Market Spec (конкретная задача: side, line)
    ↓
Market (семейство: total)
    ↓
Tournament (данные: пути, реестр)
```

### ❌ Антипаттерн: Обратная зависимость

```
Algorithm → зависит от Market  ❌ НЕПРАВИЛЬНО!
```

---

## 📚 Примеры использования

### Сценарий 1: Обучение на разных маркетах с одним алгоритмом

```bash
# Total Over 6.5
uv run python -m sports_forecast.train_v3 \
    market=total market_spec=total_over market_spec.line=6.5 \
    algorithm=catboost  # ✅ Универсальный

# Winner Home
uv run python -m sports_forecast.train_v3 \
    market=winner market_spec=winner_home \
    algorithm=catboost  # ✅ Тот же конфиг!
```

### Сценарий 2: Stacking для разных маркетов

```bash
# Total с Stacking
uv run python -m sports_forecast.train_v3 \
    market=total market_spec=total_over market_spec.line=6.5 \
    recipe=total_with_ensemble  # base_models в recipe

# Winner с Stacking (другие базовые модели)
uv run python -m sports_forecast.train_v3 \
    market=winner market_spec=winner_home \
    recipe=winner_with_ensemble  # другие base_models в recipe
```

---

## 🎯 Критерии проверки архитектуры

При создании нового конфига задайте себе вопросы:

### ✅ Для `algorithm/`:
- Может ли этот алгоритм использоваться для **любого маркета**?
- Может ли он использоваться для **любого турнира**?
- Зависит ли он от конкретных фичей?

**Если хотя бы один ответ "нет" → перенесите зависимость в `recipe`!**

### ✅ Для `market_spec/`:
- Определяет ли он **только задачу** (side, line, format)?
- Не содержит ли он гиперпараметров моделей?
- Не содержит ли он списка алгоритмов?

**Если "да" на последние два → вынесите в `recipe` или `algorithm`!**

### ✅ Для `recipe/`:
- Указывает ли он **список алгоритмов и фичей** для эксперимента?
- Может ли он применяться к **разным турнирам**?
- Содержит ли он конфигурацию ансамблей (base_models)?

**Если recipe привязан к турниру → возможно, нужен отдельный recipe для турнира.**

---

## 🚀 Итог

**Главное правило:**

> **`algorithm/` содержит универсальные алгоритмы, независимые от задачи.**
> **`recipe/` определяет, какие алгоритмы использовать для конкретного маркета.**

**Плохо:** `stacking_total.yaml`, `catboost_winner.yaml`
**Хорошо:** `stacking.yaml` + `recipe/total_with_ensemble.yaml`

---

**Дата обновления:** 2026-01-10
**Версия:** 2.0
