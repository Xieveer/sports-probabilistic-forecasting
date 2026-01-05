# 📊 Диапазоны тоталов и правила определения победителей

**Дата:** 2026-01-05  
**Версия:** 2.0 (исправлена критическая ошибка для настольного тенниса)

---

## ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ

### Настольный теннис: победитель по СЕТАМ, тотал по ПОИНТАМ

**Было (НЕПРАВИЛЬНО):**
```yaml
is_win:
  player_column: "pl_points"  # ❌ Используем поинты
  opponent_column: "opp_points"
```

**Стало (ПРАВИЛЬНО):**
```yaml
is_win:
  player_column: "pl_sets"    # ✅ Используем сеты!
  opponent_column: "opp_sets"
  comparison: "greater"
```

**Почему это критично:**
- **Победитель** определяется по СЕТАМ (кто выиграл 3+ сета)
- **Тотал** считается по ПОИНТАМ (сумма всех очков во всех сетах)
- Использование поинтов для определения победителя давало НЕПРАВИЛЬНЫЕ таргеты!

---

## 🎯 Диапазоны тоталов по спортам

### Киберхоккей (UEL)

**Турниры:** uel_kz_1, uel_kz_2, uel_cz

```yaml
total_ranges:
  min: 3.5      # Минимальный тотал
  max: 9.5      # Максимальный тотал
  step: 1.0     # Шаг
  default: 5.5  # Базовое значение для демо
```

**Линии тоталов:**
- 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5

**Обоснование:**
- Средний матч: 5-6 голов
- Редко бывает меньше 3
- Редко бывает больше 10

---

### Настольный теннис (LP)

**Турниры:** lp_ru, lp_by, lp_eu, lp_eu_a18

```yaml
total_ranges:
  min: 60.5     # Минимальный тотал
  max: 80.5     # Максимальный тотал
  step: 1.0     # Шаг
  default: 70.5 # Базовое значение для демо
```

**Линии тоталов:**
- 60.5, 61.5, 62.5, ..., 79.5, 80.5 (21 значение)

**Обоснование:**
- Матч до 11 очков × 5 сетов = ~55-85 очков
- Средний матч: 65-75 очков
- Зависит от уровня игроков и стиля игры

---

## 🏓 Структура данных настольного тенниса

### Исходные колонки (source.csv):

```
home_score  - Счет по СЕТАМ хозяев (например: 3)
away_score  - Счет по СЕТАМ гостей (например: 1)
_hmps       - Home Match Points Sum (сумма ПОИНТОВ хозяев)
_amps       - Away Match Points Sum (сумма ПОИНТОВ гостей)
scores      - JSON с деталями: {"parts": [[11,9], [8,11], [11,7], [11,6]], "match": [3,1]}
```

### Column mapping (в конфиге):

```yaml
column_mapping:
  home_score: home_sets    # Сеты хозяев
  away_score: away_sets    # Сеты гостей
  _hmps: home_points       # Поинты хозяев
  _amps: away_points       # Поинты гостей
```

### После clean.py (interim):

```
home_sets   - Счет по СЕТАМ (для определения победителя)
away_sets   - Счет по СЕТАМ
home_points - Сумма ПОИНТОВ из всех сетов (для тотала и фичей)
away_points - Сумма ПОИНТОВ
```

### Пример:

**Исходные данные:**
```
home_score = 3 (выиграл 3 сета)
away_score = 1 (выиграл 1 сет)
scores = {"parts": [[11,9], [8,11], [11,7], [11,6]]}
```

**После обработки:**
```
home_sets = 3
away_sets = 1
home_points = 11 + 8 + 11 + 11 = 41
away_points = 9 + 11 + 7 + 6 = 33
```

**Таргеты:**
```
is_win (home perspective):
  target = 1  (home_sets=3 > away_sets=1) ✅

total_over_70.5:
  total = 41 + 33 = 74
  target = 1  (74 > 70.5) ✅

total_under_70.5:
  target = 0  (74 > 70.5) ❌
```

---

## 🏒 Структура данных киберхоккея

### Исходные колонки (source.csv):

```
h_m_s  - Home match score (голы хозяев)
a_m_s  - Away match score (голы гостей)
```

### После clean.py (interim):

```
home_points - Голы хозяев (для победителя И тотала)
away_points - Голы гостей
```

### Пример:

**Исходные данные:**
```
h_m_s = 4
a_m_s = 2
```

**Таргеты:**
```
is_win (home perspective):
  target = 1  (4 > 2) ✅

total_over_5.5:
  total = 4 + 2 = 6
  target = 1  (6 > 5.5) ✅

total_under_5.5:
  target = 0  (6 > 5.5) ❌
```

---

## 📝 Конфигурация target_sources

### Киберхоккей (прост):

```yaml
is_win:
  player_column: "pl_points"     # Голы текущего игрока
  opponent_column: "opp_points"  # Голы оппонента
  comparison: "greater"
  format: "long"

total_over:
  home_column: "home_points"     # Голы хозяев
  away_column: "away_points"     # Голы гостей
  comparison: "total_over"
  base: 5.5
  format: "wide"
```

### Настольный теннис (ВАЖНО различать!):

```yaml
is_win:
  player_column: "pl_sets"       # ⚠️ СЕТЫ, не поинты!
  opponent_column: "opp_sets"
  comparison: "greater"
  format: "long"

total_over:
  home_column: "home_points"     # ⚠️ ПОИНТЫ (сумма из всех сетов)
  away_column: "away_points"
  comparison: "total_over"
  base: 70.5
  format: "wide"
```

---

## 🛠️ Автоматическая генерация моделей

Диапазоны позволяют автоматически создавать модели для всех линий:

```python
# Пример генерации моделей total_over для всех баз
def generate_total_models(tournament_name: str):
    config = load_tournament_config(tournament_name)
    ranges = config['total_ranges']
    
    for base in range(ranges['min'], ranges['max'] + ranges['step'], ranges['step']):
        model_name = f"total_over_{base}"
        # Создаем и обучаем модель
        train_model(tournament=tournament_name, model=model_name, base=base)
```

**Для киберхоккея:**
- 7 моделей: total_over_3.5, 4.5, ..., 9.5

**Для настольного тенниса:**
- 21 модель: total_over_60.5, 61.5, ..., 80.5

---

## 🔍 Валидация

### Проверка что используются правильные колонки:

```bash
# LP турниры должны использовать сеты
grep "pl_sets\|home_sets" conf/tournament/lp_*.yaml

# UEL турниры используют поинты
grep "pl_points\|home_points" conf/tournament/uel_*.yaml
```

### Проверка диапазонов:

```bash
# Проверить что все турниры имеют total_ranges
grep -A 4 "total_ranges:" conf/tournament/*.yaml
```

---

## 📊 Итоговая таблица

| Турнир | Спорт | Победитель | Тотал | Range | Default |
|--------|-------|------------|-------|-------|---------|
| uel_kz_1, uel_kz_2, uel_cz | Киберхоккей | points | points | 3.5-9.5 | 5.5 |
| lp_ru, lp_by, lp_eu, lp_eu_a18 | Настольный теннис | **sets** | **points** | 60.5-80.5 | 70.5 |

---

## ⚠️ Важные моменты

1. **Настольный теннис особенный:**
   - Победитель ≠ Тотал (разные метрики)
   - Сеты для is_win, поинты для total

2. **Киберхоккей простой:**
   - Победитель = Тотал (одна метрика - голы)

3. **Диапазоны в конфиге:**
   - Позволяют автоматизировать создание моделей
   - Документируют допустимые значения
   - Упрощают валидацию

4. **Поинты уже в данных:**
   - В исходных данных есть готовые колонки `_hmps` и `_amps`
   - Они содержат сумму всех поинтов из всех сетов
   - Не нужен парсинг JSON, просто делаем маппинг

---

## 📚 См. также:

- `MODELS_AND_TARGETS.md` - архитектура моделей
- `FEATURE_GENERATION_ARCHITECTURE.md` - генерация фичей

---

*Обновлено: 2026-01-05 (исправлена критическая ошибка для настольного тенниса)*

