# 📊 Архитектура хранения букмекерских коэффициентов

**Дата:** 2026-01-05
**Версия:** 1.0

---

## 🎯 Зачем нужны коэффициенты

Букмекерские коэффициенты нужны для:

1. **Оценки quality моделей** - можем ли мы обыграть букмекера
2. **Калибровки вероятностей** - implied probability vs model probability
3. **Расчета ROI** - return on investment для стратегий
4. **Фильтрации ставок** - выбор матчей с положительным EV (expected value)

---

## 📁 Архитектура хранения

### Структура файлов:

```
data/
  raw/
    uel_kz_1/
      matches.parquet    ← Данные матчей
      odds.parquet       ← Коэффициенты букмекера ✨
    uel_kz_2/
      matches.parquet
      odds.parquet
    lp_ru/
      matches.parquet
      odds.parquet       ← Может быть пустым (если нет коэффициентов)
```

### Преимущества отдельного файла:

✅ **Быстрый джойн** по `match_id`
✅ **Независимая обработка** - можно обновлять odds отдельно
✅ **Опциональность** - турниры без odds не ломают пайплайн
✅ **Расширяемость** - легко добавить коэффициенты от других букмекеров

---

## 🗂️ Структура таблицы odds.parquet

### Базовые колонки:

| Колонка | Тип | Описание |
|---------|-----|----------|
| `match_id` | string | ID матча (связь с matches.parquet) |
| `bookmaker` | string | Источник коэффициентов (например: "fonbet") |
| `timestamp` | datetime | Когда были получены коэффициенты |

### Коэффициенты на исход (Winner):

| Колонка | Тип | Описание | Пример |
|---------|-----|----------|--------|
| `odds_home_win` | float | Коэф. на победу хозяев | 4.7 |
| `odds_draw` | float | Коэф. на ничью | 5.0 |
| `odds_away_win` | float | Коэф. на победу гостей | 1.52 |

### Коэффициенты на тотал (Total):

| Колонка | Тип | Описание | Пример |
|---------|-----|----------|--------|
| `odds_total_over_X.5` | float | Коэф. на тотал больше X.5 | 2.17 |
| `odds_total_under_X.5` | float | Коэф. на тотал меньше X.5 | 1.65 |

### Коэффициенты на фору (Handicap):

| Колонка | Тип | Описание | Пример |
|---------|-----|----------|--------|
| `odds_handicap_home_X.X` | float | Коэф. на фору хозяев X.X | 3.55 |
| `odds_handicap_away_X.X` | float | Коэф. на фору гостей X.X | 1.25 |

---

## 📊 Формат исходных данных

### UEL (киберхоккей):

**Колонка:** `fon_bet_odds_feed`
**Формат:** Python dict в строковом виде
**Заполненность:** ~65%

**Пример:**
```python
{
    '1': 4.7,          # Home Win
    'x': 5.0,          # Draw
    '2': 1.52,         # Away Win
    'f10.0': 3.55,     # Home Handicap 0.0
    'f20.0': 1.25,     # Away Handicap 0.0
    'f1_1.5': 1.70,    # Home Handicap +1.5
    'f2_-1.5': 2.10,   # Away Handicap -1.5
    'tu_5.5': 1.65,    # Total Under 5.5
    'to_5.5': 2.17,    # Total Over 5.5
    'tu_4.5': 2.23,    # Total Under 4.5
    'to_4.5': 1.58     # Total Over 4.5
}
```

### LP (настольный теннис):

**Колонка:** `sdf_odds_feed`
**Формат:** Python dict в строковом виде
**Заполненность:** ~27-28%

**Пример:**
```python
{
    '1': 1.48,    # Home Win
    '2': 2.45     # Away Win
}
```

**Особенности:**
- Только коэффициенты на победителя (нет ничьи, нет тоталов, нет фор)
- Букмекер: SDF (неизвестный источник)
- Меньше коэффициентов чем в UEL

---

## 🔧 Парсинг коэффициентов

### Алгоритм:

```python
import ast
import pandas as pd

def parse_odds(odds_str: str) -> dict:
    """
    Парсит строку с коэффициентами в структурированный dict.

    Args:
        odds_str: Python dict в строковом виде

    Returns:
        dict с нормализованными ключами
    """
    if pd.isna(odds_str):
        return {}

    # Безопасный парсинг Python dict
    odds_raw = ast.literal_eval(odds_str)

    # Нормализация ключей
    odds = {
        'odds_home_win': odds_raw.get('1'),
        'odds_draw': odds_raw.get('x'),
        'odds_away_win': odds_raw.get('2'),
    }

    # Парсинг тоталов
    for key, val in odds_raw.items():
        if key.startswith('to_'):  # Total Over
            base = key.replace('to_', '')
            odds[f'odds_total_over_{base}'] = val
        elif key.startswith('tu_'):  # Total Under
            base = key.replace('tu_', '')
            odds[f'odds_total_under_{base}'] = val
        elif key.startswith('f1'):  # Home Handicap
            hcap = key.replace('f1', '')
            odds[f'odds_handicap_home{hcap}'] = val
        elif key.startswith('f2'):  # Away Handicap
            hcap = key.replace('f2', '')
            odds[f'odds_handicap_away{hcap}'] = val

    return odds
```

---

## 🎓 Использование коэффициентов

### 1. Implied Probability

Преобразование коэффициента в вероятность:

```python
def odds_to_probability(odds: float) -> float:
    """
    Коэффициент → implied probability (с учетом маржи букмекера).

    Examples:
        odds=2.0 → 50%
        odds=4.0 → 25%
    """
    return 1.0 / odds
```

### 2. Expected Value (EV)

```python
def calculate_ev(model_prob: float, odds: float) -> float:
    """
    Расчет expected value ставки.

    EV > 0 → ставка выгодна
    EV < 0 → ставка невыгодна

    Args:
        model_prob: Вероятность по нашей модели (0-1)
        odds: Коэффициент букмекера

    Returns:
        Expected value (в долях ставки)
    """
    return (model_prob * odds) - 1.0
```

**Пример:**
```python
# Наша модель дает 40% на победу хозяев
# Букмекер дает коэф. 3.0

model_prob = 0.40
odds = 3.0

ev = calculate_ev(model_prob, odds)
# ev = (0.40 * 3.0) - 1.0 = 0.20 (20% прибыль!)
```

### 3. ROI (Return on Investment)

```python
def calculate_roi(predictions: pd.DataFrame, odds: pd.DataFrame) -> float:
    """
    Расчет ROI стратегии на исторических данных.

    Returns:
        ROI в процентах
    """
    df = predictions.merge(odds, on='match_id')

    # Фильтруем только ставки с положительным EV
    df['ev'] = df.apply(
        lambda row: calculate_ev(row['pred_prob'], row['odds']),
        axis=1
    )
    df_bets = df[df['ev'] > 0]

    # Считаем прибыль
    df_bets['profit'] = df_bets['is_win'] * df_bets['odds'] - 1.0

    roi = df_bets['profit'].sum() / len(df_bets) * 100
    return roi
```

---

## 📝 Конфигурация турниров

Добавим в конфиг турнира информацию о коэффициентах:

```yaml
# conf/tournament/uel_kz_1.yaml

odds:
  enabled: true
  source_column: "fon_bet_odds_feed"
  bookmaker: "fonbet"
  parse_format: "python_dict"  # или "json"

# conf/tournament/lp_ru.yaml

odds:
  enabled: true
  source_column: "sdf_odds_feed"
  bookmaker: "sdf"
  parse_format: "python_dict"
  coverage: 27.4  # % матчей с коэффициентами
```

---

## 🔄 Интеграция в пайплайн

### 1. Ingest stage:

```python
# sports_forecast/data/ingest.py

def process_tournament(source_dir: Path, raw_root: Path) -> None:
    # ... существующая обработка matches ...

    # Парсинг коэффициентов (если есть)
    odds_df = parse_tournament_odds(df, tournament_cfg)
    if not odds_df.empty:
        odds_path = output_dir / "odds.parquet"
        odds_df.to_parquet(odds_path, index=False)
        logger.info(f"  ✓ Odds: {len(odds_df)} records → {odds_path}")
```

### 2. Predict stage:

```python
# sports_forecast/predict.py

def predict_with_odds_analysis(
    predictions: pd.DataFrame,
    odds_path: Path
) -> pd.DataFrame:
    """
    Обогащение предсказаний коэффициентами букмекера.
    """
    if not odds_path.exists():
        logger.warning("No odds data available")
        return predictions

    odds = pd.read_parquet(odds_path)
    enriched = predictions.merge(odds, on='match_id', how='left')

    # Добавляем implied probability
    enriched['bookmaker_prob'] = 1.0 / enriched['odds_home_win']

    # Добавляем EV
    enriched['expected_value'] = (
        enriched['pred_prob'] * enriched['odds_home_win'] - 1.0
    )

    return enriched
```

---

## 📊 Структура финального датасета

После джойна с коэффициентами:

```
predictions.parquet:
  match_id
  datetime
  home_team
  away_team
  pred_prob_home_win       ← Наша модель
  pred_prob_total_over_5.5
  bookmaker_prob_home_win  ← Букмекер (implied)
  odds_home_win            ← Коэффициент
  odds_total_over_5.5
  expected_value_home_win  ← EV = (pred * odds) - 1
  expected_value_total_over
  recommended_bet          ← True если EV > threshold
```

---

## 🎯 Best Practices

1. **Отдельное хранение** - odds.parquet независим от matches
2. **Опциональность** - код работает без odds (для турниров без коэффициентов)
3. **Нормализация ключей** - `odds_*` префикс для всех колонок
4. **Timestamp** - сохраняем когда были получены коэффициенты
5. **Bookmaker source** - указываем источник (для multi-bookmaker поддержки)

---

## 📚 См. также:

- `MODELS_AND_TARGETS.md` - архитектура моделей
- `TOTAL_RANGES.md` - диапазоны тоталов для моделей

---

*Создано: 2026-01-05*
