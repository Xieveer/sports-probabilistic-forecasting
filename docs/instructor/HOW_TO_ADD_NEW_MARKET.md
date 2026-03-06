# Как добавить новый маркет

Пошаговое руководство по добавлению нового рынка (маркета) для прогнозирования.

---

## Обзор

Система маркетов в проекте разделена на два уровня:

1. **Market family** (`conf/market/`) — семейство рынков (winner, total, handicap)
2. **Market spec** (`conf/market_spec/`) — конкретная спецификация (winner_home, total_over, total_under)

Также необходимо, чтобы турнирный (спортивный) конфиг определял `target_sources` — как вычислять таргет для данного маркета.

---

## Существующие маркеты

| Family | Spec | Формат | Описание |
|--------|------|--------|----------|
| winner | winner | long | Победа игрока (player vs opponent) |
| winner | winner_home | wide | Победа хозяев |
| total | total_over | wide | Тотал больше линии |
| total | total_under | wide | Тотал меньше линии |

---

## Пример: Добавление маркета "Handicap"

### Шаг 1. Создать market family

```yaml
# conf/market/handicap.yaml
family: handicap
description: "Handicap (Asian Handicap) market family"

target_logic:
  type: comparison_with_line
  operands:
    - player_points
    - opponent_points
  operator: greater_with_handicap

available_sides:
  - home
  - away
```

### Шаг 2. Создать market spec

```yaml
# conf/market_spec/handicap_home.yaml
name: handicap_home
market_family: handicap
side: home
description: "Home team handicap"

# Линия обязательна для handicap
line: ???  # REQUIRED! Пример: market_spec.line=-1.5

# Формат данных
data_format: wide

# Источник таргета
target_source_key: home_handicap
target_name: "target_handicap_home"

prematch_line:
  enabled: true
  source: "odds_feed"
  timing: "close"
  market_key: "handicap"
```

### Шаг 3. Добавить target_source в спортивный конфиг

Добавьте в `conf/sport/<sport>.yaml`:

```yaml
target_sources:
  # ... существующие source'ы ...

  # Handicap Home: (home_points + line) > away_points
  home_handicap:
    format: wide
    home_column: home_points
    away_column: away_points
    comparison: handicap_home
    # Или через формулу:
    # formula: "(home_points + line) > away_points"
```

### Шаг 4. Добавить comparison в targets.py

Если используется новый тип сравнения, добавьте его в `sports_forecast/utils/targets.py`.

`FormulaTargetBuilder` поддерживает декларативные формулы:

```yaml
target_sources:
  home_handicap:
    format: wide
    formula: "home_points + {line} > away_points"
```

Либо можно использовать встроенные comparison типы:
- `greater` — A > B
- `total_over` — (A + B) > line
- `total_under` — (A + B) < line
- Формулы через `FormulaTargetBuilder`

### Шаг 5. Обновить allowed_market_specs

В `conf/sport/<sport>.yaml`:

```yaml
allowed_market_specs:
  winner:
    specs: [winner, winner_home]
  total:
    lines: [6.5, 7.5, 8.5]
    specs: [total_over, total_under]
  handicap:                        # ← Добавить
    lines: [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5]
    specs: [handicap_home]
```

---

## Шаг 6. Запустить обучение

```bash
uv run python -m sports_forecast.train \
    tournament=uel_kz_1 \
    market=handicap \
    market_spec=handicap_home \
    market_spec.line=-1.5 \
    algorithm=catboost \
    features=basic
```

---

## Формат данных: Long vs Wide

### Long format

Каждый матч представлен **двумя строками**:
- `player=home, opponent=away` (target=1 если home win)
- `player=away, opponent=home` (target=1 если away win)

**Когда использовать:** winner маркет без привязки к стороне (h2h).

### Wide format

Каждый матч — **одна строка** с колонками `home_*` и `away_*`.

**Когда использовать:** total, handicap, winner_home/winner_away.

**Указание формата:**
```yaml
# В market_spec
data_format: long   # или wide
```

---

## Маркеты с параметром (line)

Для маркетов с линией (total, handicap):

1. Линия задаётся как `???` (обязательный параметр) в market_spec
2. Передаётся через CLI: `market_spec.line=6.5`
3. Используется в target computation: `compute_target_from_market_spec(df, market_spec, tournament_cfg, line=6.5)`
4. Линия добавляется к имени таргета: `target_total_over_6_5`

---

## Чеклист

- [ ] Создан `conf/market/<family>.yaml`
- [ ] Создан `conf/market_spec/<spec>.yaml`
- [ ] Добавлен `target_source` в `conf/sport/<sport>.yaml`
- [ ] Обновлён `allowed_market_specs` в спортивном конфиге
- [ ] Если нужен новый `comparison` — добавлен в `targets.py`
- [ ] Тестовый запуск обучения прошёл
- [ ] Таргет распределён корректно (не 100% одного класса)
- [ ] Результаты видны в MLflow

---

## Частые ошибки

### 1. `KeyError: '<target_source_key>'`

`target_source_key` в market_spec не найден в `tournament.target_sources`. Проверьте, что ключ совпадает.

### 2. `ValueError: line is required`

Для маркетов с линией (total, handicap) обязательно передавайте `market_spec.line=X.X`.

### 3. `Target contains only one class`

Линия выбрана слишком далеко от среднего. Проверьте `stats.avg_total` в турнирном конфиге и выберите линию в разумном диапазоне.

### 4. `data_format mismatch`

Убедитесь, что `data_format` в market_spec совпадает с `format` в target_source:
- `data_format: long` → `target_source.format: long`
- `data_format: wide` → `target_source.format: wide`
