# 🏗️ Архитектура Feature Generation System

## 📋 Требования (из обсуждения)

### ✅ Принятые решения:

1. **Формат данных:** Хранить ОБА формата (`wide.parquet` + `long.parquet`)
   - `wide` - для моделей тотала (один матч = одна строка)
   - `long` - для моделей победителя (один матч = две строки: pl/opp)

2. **Конфигурация:** Компактные правила генерации через YAML (spans, contexts, metrics)

3. **Feature selection:** Генерируем все фичи, обучаем на всех (Optuna отложен)

4. **Унификация:** Через маппинги в `clean.py` (home_points/away_points → унифицированные названия)

5. **Генераторы:** Отдельные модули + оркестратор

---

## 🏛️ Архитектура

### 📂 Структура директорий

```
sports_forecast/
  features/
    __init__.py
    
    # Утилиты для трансформации форматов
    long_format.py         # wide ↔ long трансформации
    
    # Генераторы фичей
    generators/
      __init__.py
      base.py              # BaseFeatureGenerator (абстрактный класс)
      ewm_generator.py     # EWMFeatureGenerator
      count_generator.py   # CountFeatureGenerator
      form_generator.py    # FormFeatureGenerator
      adf_generator.py     # ADFFeatureGenerator (опционально)
    
    # Оркестратор
    pipeline.py            # FeaturePipeline
    
    # Существующий модуль (обновим)
    features_build.py      # Обновленный под новую систему
```

---

## 🔧 Компоненты системы

### 1️⃣ **long_format.py** - Трансформации форматов

```python
def wide_to_long(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    Трансформация wide → long format.
    
    wide:
      id | datetime | home_name | away_name | home_points | away_points
      1  | 2024-01  | Team A    | Team B    | 10          | 8
    
    long:
      id | datetime | pl      | opp     | pl_points | opp_points | side | is_home
      1  | 2024-01  | Team A  | Team B  | 10        | 8          | h    | 1
      1  | 2024-01  | Team B  | Team A  | 8         | 10         | a    | 0
    
    Args:
        df: Wide format датафрейм
        cfg: Конфиг с маппингами колонок
    
    Returns:
        Long format датафрейм
    """
    pass

def long_to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """
    Трансформация long → wide format (для сохранения результатов).
    """
    pass
```

---

### 2️⃣ **generators/base.py** - Базовый класс

```python
from abc import ABC, abstractmethod
from typing import Dict, List, Any
import pandas as pd

class BaseFeatureGenerator(ABC):
    """Базовый класс для всех генераторов фичей."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: Конфигурация генератора из YAML
        """
        self.config = config
        self.enabled = config.get("enabled", True)
        self.name = self.__class__.__name__
    
    @abstractmethod
    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Генерация фичей.
        
        Args:
            df: Входной датафрейм (wide или long в зависимости от генератора)
        
        Returns:
            Датафрейм с добавленными фичами
        """
        pass
    
    @abstractmethod
    def get_feature_names(self) -> List[str]:
        """Возвращает список имен сгенерированных фичей."""
        pass
    
    def validate_config(self) -> None:
        """Валидация конфигурации генератора."""
        pass
```

---

### 3️⃣ **generators/ewm_generator.py** - EWM фичи

```python
class EWMFeatureGenerator(BaseFeatureGenerator):
    """
    Генератор экспоненциально взвешенных скользящих средних (EWM).
    
    Генерирует фичи вида:
    - pl_global_ewm_10, pl_global_ewm_20, ...
    - pl_match_state_ewm_10, pl_match_state_ewm_20, ...
    - h2h_ewm_10_diff, h2h_ewm_20_diff, ...
    
    Пример конфига:
        type: "ewm"
        enabled: true
        metric: "diff_ps"  # home_points - away_points (после унификации)
        spans: [5, 10, 20, 50, 100, 150, 200]
        shift: 1
        min_periods: 3
        adjust: false
        contexts:
          - name: "global"
            keys: ["pl"]
            players: ["pl", "opp"]  # Генерируем для обоих
            compute_diff: true      # Создаем all_global_ewm_X_diff
          
          - name: "match_state"
            keys: ["pl", "match_state"]
            players: ["pl", "opp"]
            compute_diff: true
          
          - name: "h2h"
            keys: ["pl", "opp"]
            h2h: true               # H2H фичи (без раздельных pl/opp)
            output_suffix: "_diff"  # h2h_ewm_10_diff
    """
    
    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Генерация EWM фичей согласно конфигу.
        
        Логика:
        1. Создаем базовую метрику: diff_ps = pl_ps - opp_ps
        2. Для каждого span:
           - Для каждого context:
             - Группируем по keys
             - Вычисляем EWM
             - Если players указаны - генерируем для pl и opp отдельно
             - Если compute_diff=true - создаем разницу pl - opp
        """
        long = df.copy()
        
        metric_col = self.config["metric"]
        spans = self.config["spans"]
        shift = self.config.get("shift", 1)
        min_periods = self.config.get("min_periods", 3)
        adjust = self.config.get("adjust", False)
        
        # Создаем базовую метрику (если еще нет)
        if metric_col == "diff_ps" and metric_col not in long.columns:
            long["diff_ps"] = long["pl_ps"] - long["opp_ps"]
        
        # Генерируем фичи
        for span in spans:
            for ctx in self.config["contexts"]:
                self._generate_context_features(
                    long, ctx, metric_col, span, shift, min_periods, adjust
                )
        
        return long
    
    def _generate_context_features(self, df, ctx, metric, span, shift, min_periods, adjust):
        """Генерация фичей для одного контекста."""
        name = ctx["name"]
        keys = ctx["keys"]
        
        if ctx.get("h2h", False):
            # H2H фичи (один признак на пару игроков)
            df[f"{name}_ewm_{span}_diff"] = self._calculate_ewm(
                df, keys, metric, span, shift, min_periods, adjust
            )
        else:
            # Фичи для каждого игрока
            players = ctx.get("players", ["pl", "opp"])
            for player in players:
                group_keys = [player] + [k for k in keys if k != "pl"]
                df[f"{player}_{name}_ewm_{span}"] = self._calculate_ewm(
                    df, group_keys, metric, span, shift, min_periods, adjust
                )
            
            # Разница между игроками
            if ctx.get("compute_diff", False):
                df[f"all_{name}_ewm_{span}_diff"] = (
                    df[f"pl_{name}_ewm_{span}"] - df[f"opp_{name}_ewm_{span}"]
                )
    
    def _calculate_ewm(self, df, group_keys, metric, span, shift, min_periods, adjust):
        """Вычисление EWM для группы."""
        return (
            df.groupby(group_keys, dropna=False)[metric]
            .transform(lambda x: (
                x.shift(shift).ffill().fillna(0.0)
            ).ewm(
                span=span,
                min_periods=min_periods,
                adjust=adjust,
                ignore_na=True,
            ).mean())
        )
    
    def get_feature_names(self) -> List[str]:
        """Возвращает список всех сгенерированных имен фичей."""
        features = []
        spans = self.config["spans"]
        
        for span in spans:
            for ctx in self.config["contexts"]:
                name = ctx["name"]
                if ctx.get("h2h", False):
                    features.append(f"{name}_ewm_{span}_diff")
                else:
                    players = ctx.get("players", ["pl", "opp"])
                    for player in players:
                        features.append(f"{player}_{name}_ewm_{span}")
                    if ctx.get("compute_diff", False):
                        features.append(f"all_{name}_ewm_{span}_diff")
        
        return features
```

---

### 4️⃣ **generators/count_generator.py** - Count фичи

```python
class CountFeatureGenerator(BaseFeatureGenerator):
    """
    Генератор count фичей (количество встреч в контексте).
    
    Генерирует фичи вида:
    - pl_global_count
    - pl_match_state_count
    - h2h_count
    
    Пример конфига:
        type: "count"
        enabled: true
        shift: 1
        contexts:
          - name: "global"
            keys: ["pl"]
            players: ["pl", "opp"]
          
          - name: "h2h"
            keys: ["pl", "opp"]
            h2h: true
    """
    
    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        long = df.copy()
        shift = self.config.get("shift", 1)
        
        for ctx in self.config["contexts"]:
            name = ctx["name"]
            keys = ctx["keys"]
            
            if ctx.get("h2h", False):
                long[f"{name}_count"] = self._calculate_count(long, keys, shift)
            else:
                players = ctx.get("players", ["pl", "opp"])
                for player in players:
                    group_keys = [player] + [k for k in keys if k != "pl"]
                    long[f"{player}_{name}_count"] = self._calculate_count(
                        long, group_keys, shift
                    )
        
        return long
    
    def _calculate_count(self, df, group_keys, shift):
        """Вычисление count."""
        return df.groupby(group_keys, dropna=False).cumcount() + 1 - shift
    
    def get_feature_names(self) -> List[str]:
        features = []
        for ctx in self.config["contexts"]:
            name = ctx["name"]
            if ctx.get("h2h", False):
                features.append(f"{name}_count")
            else:
                players = ctx.get("players", ["pl", "opp"])
                for player in players:
                    features.append(f"{player}_{name}_count")
        return features
```

---

### 5️⃣ **generators/form_generator.py** - Player form фичи

```python
class FormFeatureGenerator(BaseFeatureGenerator):
    """
    Генератор фичей формы игрока (first game, double play, in form).
    
    Генерирует фичи:
    - pl_mins_prev_match, opp_mins_prev_match
    - pl_is_dp, pl_is_fg, pl_is_form
    - opp_is_dp, opp_is_fg, opp_is_form
    - match_state (комбинация форм обоих игроков)
    - diff_mins_prev_match
    
    Пример конфига:
        type: "form"
        enabled: true
        fg_trigger_minutes: 480   # 8 часов
        dp_trigger_minutes: 30
        players: ["pl", "opp"]
    """
    
    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        long = df.copy()
        
        fg_trigger = self.config.get("fg_trigger_minutes", 480) * 60  # в минуты
        dp_trigger = self.config.get("dp_trigger_minutes", 30) * 60
        players = self.config.get("players", ["pl", "opp"])
        
        for player in players:
            # Время с предыдущего матча
            long[f"{player}_mins_prev_match"] = (
                long.groupby(player)["datetime"]
                .diff()
                .dt.total_seconds()
                .div(60.0)
            )
            
            # Определение состояния
            m = long[f"{player}_mins_prev_match"].clip(lower=0)
            is_dp = m.notna() & (m <= dp_trigger)
            is_fg = m.isna() | (m >= fg_trigger)
            
            long[f"{player}_state"] = pd.Series(
                np.select(
                    [is_dp, is_fg],
                    ["dp", "fg"],
                    default="form"
                ),
                index=long.index
            ).astype("category")
            
            # Бинарные индикаторы
            long[f"{player}_is_dp"] = is_dp.astype("int8")
            long[f"{player}_is_fg"] = is_fg.astype("int8")
            long[f"{player}_is_form"] = (~(is_dp | is_fg)).astype("int8")
        
        # Комбинированное состояние матча
        long["match_state"] = (
            long["pl_state"].astype(str) + "|" + long["opp_state"].astype(str)
        )
        
        # Разница во времени
        long["diff_mins_prev_match"] = (
            long["pl_mins_prev_match"] - long["opp_mins_prev_match"]
        )
        
        return long
    
    def get_feature_names(self) -> List[str]:
        players = self.config.get("players", ["pl", "opp"])
        features = []
        
        for player in players:
            features.extend([
                f"{player}_mins_prev_match",
                f"{player}_is_dp",
                f"{player}_is_fg",
                f"{player}_is_form",
            ])
        
        features.extend(["match_state", "diff_mins_prev_match"])
        return features
```

---

### 6️⃣ **pipeline.py** - Оркестратор

```python
class FeaturePipeline:
    """
    Оркестратор генерации фичей.
    
    Читает конфиг, создает генераторы, применяет их последовательно.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: Конфиг из features/*.yaml
        """
        self.config = config
        self.generators = self._init_generators()
        self.logger = get_logger(__name__)
    
    def _init_generators(self) -> List[BaseFeatureGenerator]:
        """Инициализация генераторов из конфига."""
        generators = []
        
        generator_map = {
            "form": FormFeatureGenerator,
            "ewm": EWMFeatureGenerator,
            "count": CountFeatureGenerator,
            # "adf": ADFFeatureGenerator,  # опционально
        }
        
        for gen_config in self.config.get("generators", []):
            gen_type = gen_config.get("type")
            enabled = gen_config.get("enabled", True)
            
            if not enabled:
                self.logger.info(f"Генератор {gen_type} отключен, пропускаем")
                continue
            
            if gen_type not in generator_map:
                self.logger.warning(f"Неизвестный тип генератора: {gen_type}")
                continue
            
            generator_class = generator_map[gen_type]
            generator = generator_class(gen_config)
            generators.append(generator)
            
            self.logger.info(
                f"Инициализирован генератор: {gen_type} "
                f"({len(generator.get_feature_names())} фичей)"
            )
        
        return generators
    
    def generate_features(
        self, 
        df: pd.DataFrame, 
        format: str = "long"
    ) -> tuple[pd.DataFrame, List[str]]:
        """
        Генерация всех фичей.
        
        Args:
            df: Входной датафрейм (wide или long)
            format: Формат входных данных ("wide" или "long")
        
        Returns:
            (df_with_features, feature_names)
        """
        start_time = time.time()
        
        # Если нужен long format, но данные в wide - конвертируем
        if format == "wide" and self.config.get("requires_long", True):
            df = wide_to_long(df, self.config)
            self.logger.info("Конвертация wide → long выполнена")
        
        # Применяем генераторы последовательно
        result_df = df.copy()
        all_features = []
        
        for generator in self.generators:
            self.logger.info(f"Применение {generator.name}...")
            result_df = generator.generate(result_df)
            features = generator.get_feature_names()
            all_features.extend(features)
            self.logger.info(
                f"  ✓ Сгенерировано {len(features)} фичей"
            )
        
        elapsed = time.time() - start_time
        self.logger.info(
            f"⏱️  Генерация фичей завершена за {elapsed:.2f} сек. "
            f"Всего фичей: {len(all_features)}"
        )
        
        return result_df, all_features
```

---

## 📝 Пример конфига: `conf/features/advanced.yaml`

```yaml
# Продвинутая генерация фичей (на основе v2)

# Требуется ли long format для генерации
requires_long: true

# Генераторы фичей (применяются последовательно)
generators:
  # 1. Player form - создает match_state и базовые индикаторы
  - type: "form"
    enabled: true
    fg_trigger_minutes: 480  # 8 часов
    dp_trigger_minutes: 30
    players: ["pl", "opp"]
  
  # 2. EWM features - скользящие средние по контекстам
  - type: "ewm"
    enabled: true
    metric: "diff_ps"
    spans: [5, 10, 15, 20, 30, 50, 100, 150, 200]
    shift: 1
    min_periods: 3
    adjust: false
    
    contexts:
      # Глобальная форма игрока
      - name: "global"
        keys: ["pl"]
        players: ["pl", "opp"]
        compute_diff: true
      
      # Форма в зависимости от состояния (fg/dp/form)
      - name: "match_state"
        keys: ["pl", "match_state"]
        players: ["pl", "opp"]
        compute_diff: true
      
      # Форма в зависимости от номера матча в турнире
      - name: "match_num"
        keys: ["pl", "tour_match_num"]
        players: ["pl", "opp"]
        compute_diff: true
      
      # Форма по дням недели
      - name: "weekday"
        keys: ["pl", "weekday"]
        players: ["pl", "opp"]
        compute_diff: true
      
      # Форма в зависимости от номера турнира
      - name: "tour_num"
        keys: ["pl", "tour_num"]
        players: ["pl", "opp"]
        compute_diff: true
      
      # Форма в зависимости от стороны (home/away) и команды
      - name: "tour_side"
        keys: ["pl", "side"]
        players: ["pl", "opp"]
        compute_diff: true
      
      # H2H фичи
      - name: "h2h"
        keys: ["pl", "opp"]
        h2h: true
        output_suffix: "_diff"
      
      - name: "h2h_match_state"
        keys: ["pl", "opp", "match_state"]
        h2h: true
        output_suffix: "_diff"
      
      - name: "h2h_match_num"
        keys: ["pl", "opp", "tour_match_num"]
        h2h: true
        output_suffix: "_diff"
      
      - name: "h2h_side"
        keys: ["pl", "opp", "side", "pl_team", "opp_team"]
        h2h: true
        output_suffix: "_diff"
  
  # 3. Count features - количество встреч
  - type: "count"
    enabled: true
    shift: 1
    
    contexts:
      - name: "global"
        keys: ["pl"]
        players: ["pl", "opp"]
      
      - name: "match_state"
        keys: ["pl", "match_state"]
        players: ["pl", "opp"]
      
      - name: "match_num"
        keys: ["pl", "tour_match_num"]
        players: ["pl", "opp"]
      
      - name: "weekday"
        keys: ["pl", "weekday"]
        players: ["pl", "opp"]
      
      - name: "tour_num"
        keys: ["pl", "tour_num"]
        players: ["pl", "opp"]
      
      - name: "tour_side"
        keys: ["pl", "side"]
        players: ["pl", "opp"]
      
      # H2H counts
      - name: "h2h"
        keys: ["pl", "opp"]
        h2h: true
      
      - name: "h2h_match_state"
        keys: ["pl", "opp", "match_state"]
        h2h: true
      
      - name: "h2h_match_num"
        keys: ["pl", "opp", "tour_match_num"]
        h2h: true
      
      - name: "h2h_side"
        keys: ["pl", "opp", "side", "pl_team", "opp_team"]
        h2h: true
```

---

## 🔄 Интеграция с существующим пайплайном

### Обновленный `features_build.py`:

```python
def process_tournament(
    tournament_name: str,
    interim_root: Path,
    processed_root: Path,
    features_cfg: dict,
):
    """
    Генерация фичей для турнира.
    
    Сохраняет ДВА файла:
    - train_wide.parquet  (для моделей тотала)
    - train_long.parquet  (для моделей победителя)
    """
    # 1. Загрузка данных
    df = pd.read_parquet(interim_root / tournament_name / "matches.parquet")
    
    # 2. Создание pipeline
    pipeline = FeaturePipeline(features_cfg)
    
    # 3. Генерация фичей (в long format)
    df_long, feature_names = pipeline.generate_features(df, format="wide")
    
    # 4. Сохранение long format
    output_long = processed_root / tournament_name / "train_long.parquet"
    output_long.parent.mkdir(parents=True, exist_ok=True)
    df_long.to_parquet(output_long, index=False)
    
    # 5. Конвертация обратно в wide и сохранение
    df_wide = long_to_wide(df_long)
    output_wide = processed_root / tournament_name / "train_wide.parquet"
    df_wide.to_parquet(output_wide, index=False)
    
    logger.info(f"✓ Сохранено: {output_long} ({len(df_long)} строк)")
    logger.info(f"✓ Сохранено: {output_wide} ({len(df_wide)} строк)")
```

### Обновленный `train.py`:

```python
def load_training_data(tournament: str, model_name: str, paths_cfg: dict):
    """
    Загрузка данных в правильном формате для модели.
    
    - Модели победителя (is_home_win, is_away_win) → long format
    - Модели тотала (total_over_X) → wide format
    """
    processed_dir = Path(paths_cfg.paths.processed_dir)
    
    # Определяем формат по типу модели
    if model_name in ["is_home_win", "is_away_win"]:
        file_path = processed_dir / tournament / "train_long.parquet"
    else:
        file_path = processed_dir / tournament / "train_wide.parquet"
    
    df = pd.read_parquet(file_path)
    logger.info(f"Загружены данные: {file_path} ({len(df)} строк)")
    
    return df
```

---

## 🎯 Примерный результат

### Сгенерированные фичи (пример для spans=[5, 10, 20]):

**Form features (12 фичей):**
- pl_mins_prev_match, opp_mins_prev_match
- pl_is_dp, pl_is_fg, pl_is_form
- opp_is_dp, opp_is_fg, opp_is_form
- match_state, diff_mins_prev_match

**EWM features (6 contexts * 3 spans * (2 players + 1 diff) + 4 h2h contexts * 3 spans):**
- pl_global_ewm_5, pl_global_ewm_10, pl_global_ewm_20
- opp_global_ewm_5, opp_global_ewm_10, opp_global_ewm_20
- all_global_ewm_5_diff, all_global_ewm_10_diff, all_global_ewm_20_diff
- ... аналогично для match_state, match_num, weekday, tour_num, tour_side
- h2h_ewm_5_diff, h2h_ewm_10_diff, h2h_ewm_20_diff
- ... аналогично для h2h_match_state, h2h_match_num, h2h_side

**Count features (6 contexts * 2 players + 4 h2h contexts):**
- pl_global_count, opp_global_count
- pl_match_state_count, opp_match_state_count
- ... и т.д.

**Итого:** ~200+ фичей для spans=[5, 10, 20]

Для полного набора spans=[5, 10, 15, 20, 30, 50, 100, 150, 200]:
**~1000+ фичей** 🚀

---

## ✅ Преимущества архитектуры

1. **Масштабируемость:** Легко добавить новый генератор (ADFGenerator, RollingGenerator, etc.)
2. **Конфигурируемость:** Все правила в YAML, можно менять без кода
3. **Переиспользование:** Одна реализация EWM для всех турниров
4. **Гибкость:** Поддержка wide/long форматов для разных моделей
5. **Читаемость:** Четкое разделение ответственности (генераторы, pipeline, конфиги)
6. **Тестируемость:** Каждый генератор можно тестировать изолированно

---

## 🚀 Следующие шаги

1. ✅ Спроектировать архитектуру
2. ⏳ Реализовать `long_format.py`
3. ⏳ Реализовать `BaseFeatureGenerator`
4. ⏳ Реализовать `EWMFeatureGenerator`
5. ⏳ Реализовать `CountFeatureGenerator`
6. ⏳ Реализовать `FormFeatureGenerator`
7. ⏳ Реализовать `FeaturePipeline`
8. ⏳ Создать конфиг `conf/features/advanced.yaml`
9. ⏳ Обновить `features_build.py`
10. ⏳ Обновить `train.py`
11. ⏳ Протестировать на uel_kz_1

---

**Вопрос:** Все ли выглядит правильно? Можем начинать реализацию? 🚀

