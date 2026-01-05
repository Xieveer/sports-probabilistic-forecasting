# 📊 Модели и таргеты: Архитектура

**Дата:** 2026-01-05
**Версия:** 2.0 (с поддержкой long/wide форматов)

---

## 🎯 Типы моделей

### Long Format Models (train_long.parquet)

Используют данные в long формате, где один матч = две строки (home + away).

**Модели:**
- `is_win` - Победа текущего игрока (pl vs opp)

**Преимущества:**
- ✅ Одна модель для обеих сторон
- ✅ Больше данных для обучения (2x строк)
- ✅ Естественная группировка по игроку/команде
- ✅ Удобно для фичей истории игрока

**Использование:**
```bash
uv run python -m sports_forecast.train \
    tournament=uel_kz_1 \
    model=is_win
```

---

### Wide Format Models (train_wide.parquet)

Используют данные в wide формате, где один матч = одна строка (home vs away).

**Модели:**
- `is_home_win` - Победа хозяев (legacy)
- `is_away_win` - Победа гостей (legacy)
- `is_draw` - Ничья (для хоккея)
- `total_over` - Тотал больше базы
- `total_under` - Тотал меньше базы

**Преимущества для тоталов:**
- ✅ Естественное представление матча
- ✅ Фичи обеих команд в одной строке
- ✅ Проще интерпретировать

**Использование:**
```bash
# Модель тотала
uv run python -m sports_forecast.train \
    tournament=uel_kz_1 \
    model=total_over

# Legacy модель победителя
uv run python -m sports_forecast.train \
    tournament=uel_kz_1 \
    model=is_home_win
```

---

## 📋 Конфигурация турниров

### Структура target_sources

Каждый турнир определяет:
1. **total_base** - базовая линия тотала
2. **target_sources** - правила вычисления таргетов

```yaml
# conf/tournament/uel_kz_1.yaml

# База для тотала
total_base: 5.5  # Киберхоккей: обычно 5-6 голов

target_sources:
  # === LONG FORMAT MODELS ===
  is_win:
    player_column: "pl_points"
    opponent_column: "opp_points"
    comparison: "greater"  # pl_points > opp_points
    format: "long"

  # === WIDE FORMAT MODELS ===
  total_over:
    home_column: "home_points"
    away_column: "away_points"
    comparison: "total_over"  # sum > base
    base: 5.5
    format: "wide"

  total_under:
    home_column: "home_points"
    away_column: "away_points"
    comparison: "total_under"  # sum < base
    base: 5.5
    format: "wide"
```

---

## 🏒 Базы тоталов по турнирам

### Киберхоккей (UEL)
```yaml
total_base: 5.5  # Обычно 4-7 голов за матч
```

**Турниры:**
- uel_kz_1, uel_kz_2, uel_cz

---

### Настольный теннис (LP)
```yaml
total_base: 21.5  # Матчи до 11 очков × 3-5 сетов
```

**Турниры:**
- lp_ru, lp_by, lp_eu, lp_eu_a18

---

## 🎓 Типы сравнений (comparison)

### Для победителей:

| Comparison | Формула | Long | Wide |
|------------|---------|------|------|
| `greater` | pl > opp / home > away | ✅ | ✅ |
| `less` | pl < opp / home < away | ❌ | ✅ |
| `equal` | pl == opp / home == away | ❌ | ✅ |

### Для тоталов:

| Comparison | Формула | Format |
|------------|---------|--------|
| `total_over` | (home + away) > base | Wide |
| `total_under` | (home + away) < base | Wide |

---

## 📊 Примеры вычисления таргетов

### is_win (Long Format)

**Исходные данные (Wide):**
```
id  | home_name | away_name | home_points | away_points
1   | Team A    | Team B    | 3           | 2
```

**После трансформации в Long:**
```
id | pl      | opp     | pl_points | opp_points | target_win
1  | Team A  | Team B  | 3         | 2          | 1  (3 > 2)
1  | Team B  | Team A  | 2         | 3          | 0  (2 < 3)
```

✅ **Одна модель обучается на обеих строках!**

---

### total_over / total_under (Wide Format)

**Исходные данные:**
```
id | home_points | away_points | total | base
1  | 3           | 2           | 5     | 5.5
2  | 4           | 3           | 7     | 5.5
```

**Таргеты:**
```
id | target_total_over | target_total_under
1  | 0  (5 < 5.5)      | 1  (5 < 5.5)
2  | 1  (7 > 5.5)      | 0  (7 > 5.5)
```

---

## 🔧 Добавление новой модели

### 1. Создать конфиг модели

```yaml
# conf/model/my_model.yaml

name: "my_model"
type: "catboost"
description: "My custom model"
data_format: "long"  # или "wide"

target_config:
  source_key: "my_target"
  name: "target_my_model"

features:
  - "f_pl_is_dp"
  - "f_pl_global_count"

params:
  loss_function: "Logloss"
  eval_metric: "Logloss"
  iterations: 300
```

### 2. Добавить target_source в турниры

```yaml
# conf/tournament/uel_kz_1.yaml

target_sources:
  my_target:
    player_column: "pl_points"  # для long
    # или
    home_column: "home_points"  # для wide
    away_column: "away_points"
    comparison: "custom_logic"
    format: "long"  # или "wide"
```

### 3. Обучить модель

```bash
uv run python -m sports_forecast.train \
    tournament=uel_kz_1 \
    model=my_model
```

---

## 📝 Best Practices

### ✅ Рекомендуется:

1. **Для моделей победителя:** Используйте `is_win` (long format)
   - Больше данных
   - Одна модель для обеих сторон
   - Естественные фичи игрока

2. **Для моделей тотала:** Используйте `total_over/under` (wide format)
   - Естественное представление
   - Фичи обеих команд доступны
   - Проще для бизнес-логики

3. **База тотала:** Выбирайте на основе статистики турнира
   - Медиана или среднее значение
   - Чаще всего используемая букмекерская линия

### ⚠️ Legacy модели:

- `is_home_win` / `is_away_win` - оставлены для обратной совместимости
- Рекомендуется мигрировать на `is_win` (long format)

---

## 🔍 Проверка конфигов

### Список всех моделей:
```bash
ls conf/model/
```

**Доступные:**
- `is_win.yaml` ✨ (рекомендуется для победителей)
- `total_over.yaml` ✨ (рекомендуется для тоталов)
- `total_under.yaml` ✨
- `is_home_win.yaml` (legacy)
- `catboost_baseline.yaml` (legacy)

### Проверка target_sources турнира:
```bash
grep -A 30 "target_sources:" conf/tournament/uel_kz_1.yaml
```

### Проверка базы тотала:
```bash
grep "total_base:" conf/tournament/*.yaml
```

**Результат:**
```
uel_*.yaml: 5.5   (киберхоккей)
lp_*.yaml:  21.5  (настольный теннис)
```

---

## 📚 См. также:

- `FEATURE_GENERATION_ARCHITECTURE.md` - архитектура фичей
- `FEATURE_SYSTEM_QUICKSTART.md` - быстрый старт
- `FINAL_REPORT.md` - итоговый отчет по системе

---

*Обновлено: 2026-01-05*
