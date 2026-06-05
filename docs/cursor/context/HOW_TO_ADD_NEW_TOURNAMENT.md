# Как добавить новый турнир

Пошаговое руководство по добавлению нового турнира в систему прогнозирования.

---

## Обзор

Добавление турнира состоит из следующих шагов:

1. Определить спорт (существующий или новый)
2. Создать source конфиг (при необходимости — выбрать `provider`, см. шаг 2а)
3. Положить исходные данные
4. Создать tournament конфиг
5. Запустить DVC pipeline
6. Проверить результат

---

## Шаг 1. Определить спорт

Турнир всегда привязан к спорту. Спорт определяет:

- `target_sources` — как вычислять таргеты
- `allowed_market_specs` — допустимые рынки и линии
- `data_clean` — маппинг колонок, типы данных
- `form_params` — пороги FG/DP для формы игрока
- **`feature_pipeline.groups`** — какие **опциональные** пакеты генераторов включать помимо каркаса пресета `features` (см. ниже и `docs/cursor/context/feature_pipeline_composition.md`)

### Пайплайн фичей (`feature_pipeline`, R29)

Пресет **`features=basic`** / **`features=advanced`** задаёт **общий каркас** (`time`, `form`, `rolling`: EWM/Count с библиотекой контекстов). **Не хоккейные** турниры не должны получать NHL pre-gen (`nhl_schedule` / `nhl_standings` / `nhl_roster`) и **`streak`** только из-за пресета.

Каноника задаётся в **`conf/sport/<sport>.yaml`**:

```yaml
feature_pipeline:
  groups:
    nhl_boxscore: true   # только ice_hockey (NHL API + boxscore колонки)
    streak: true         # серии / win-rate (по умолчанию для хоккея)
```

Для киберхоккея и настольного тенниса в репозитории уже выставлено `nhl_boxscore: false`, `streak: false`.

**Турнир** при необходимости задаёт только дифф:

```yaml
feature_pipeline_overrides:
  groups:
    streak: true         # пример: opt-in streak для киберхоккея
  exclude_generators: []  # опционально: явно убрать ключи из generators
```

Композиция выполняется в коде (`compose_feature_pipeline` → `materialize_features_config`). Подробнее: **`docs/cursor/context/feature_pipeline_composition.md`**.

---

### Существующие спорты

| Спорт | Конфиг | Участники (wide) |
|-------|--------|------------------|
| Ice hockey | `conf/sport/ice_hockey.yaml` | `home_team` / `away_team` |
| Cyberhockey | `conf/sport/cyberhockey.yaml` | `home_team` / `away_team` |
| Table Tennis | `conf/sport/table_tennis.yaml` | `home_team` / `away_team` |
| Football (nationals) | `conf/sport/football.yaml` | `home_team` / `away_team` |

> **Стандартизация:** Имена участников всегда приводятся к `home_team` / `away_team`
> на clean-стадии (через `column_mapping`). В long format: `pl` / `opp`.

Если ваш турнир относится к существующему спорту, переходите к **Шагу 2**.

### Новый спорт

Если нужен новый спорт, создайте файл `conf/sport/<sport_name>.yaml`:

```yaml
# conf/sport/basketball.yaml
sport: basketball

form_params:
  fg_trigger_minutes: 1440    # 24 часа → First Game
  dp_trigger_minutes: 60      # 60 минут → Double Play

allowed_market_specs:
  winner:
    specs: [winner, winner_home]
  total:
    lines: [180.5, 190.5, 200.5, 210.5, 220.5]
    specs: [total_over, total_under]

target_sources:
  player_win:
    format: long
    player_column: pl_points
    opponent_column: opp_points
    comparison: greater

  home_win:
    format: wide
    home_column: home_points
    away_column: away_points
    comparison: greater

  total_sum:
    format: wide
    home_column: home_points
    away_column: away_points
    comparison: total_over

  total_sum_under:
    format: wide
    home_column: home_points
    away_column: away_points
    comparison: total_under

data_clean:
  column_mapping:
    raw_home_score: home_points
    raw_away_score: away_points
    raw_home_team: home_team      # ← обязательно привести к home_team / away_team
    raw_away_team: away_team
    odds_column: odds_raw

  required_columns: [id, status, datetime]
  drop_na_columns: [id, datetime, status]

  dtype_mapping:
    numeric:
      home_points: float
      away_points: float
    string: [id, status]
    datetime:
      datetime:
        format: null
        errors: coerce
```

**Важно:**
- `target_sources` определяет, какие столбцы используются для таргета
- Для спортов с двойной системой счёта (например, теннис: сеты + очки) создайте отдельные target_sources для winner (по сетам) и total (по очкам)
- `column_mapping` маппит исходные имена столбцов в стандартные

---

## Шаг 2. Создать source конфиг

Source конфиг описывает, как обрабатывать исходный файл данных.

Создайте `conf/source/<source_name>.yaml`:

```yaml
# conf/source/nba.yaml
name: nba
sport: basketball
region: usa
description: "NBA Basketball"

provider:
  type: file

# Если source содержит один турнир
split_strategy:
  enabled: false

# Букмекерские коэффициенты
odds:
  enabled: true
  source_column: odds_feed_column_name
  bookmaker: fonbet
  format: python_dict
```

### Если source содержит несколько подтурниров

```yaml
# conf/source/uel.yaml
split_strategy:
  enabled: true
  method: column_based
  split_column: tour_name_en

  rules:
    - condition: "contains('stream 1', case=False)"
      output_tournament: uel_kz_1
      description: "Kazakhstan Stream 1"

    - condition: "contains('stream 2', case=False)"
      output_tournament: uel_kz_2
      description: "Kazakhstan Stream 2"

    - condition: default
      output_tournament: uel_cz
      description: "Czech Republic"
```

### Шаг 2а. Выбрать провайдер данных

Ingest читает один CSV/Parquet на турнир. Источник файла задаётся секцией `provider` в `conf/source/<source_name>.yaml`. Если секции нет, используется **`type: file`** (как раньше: `data/source/<name>/source.csv`).

Локальный файл (по умолчанию):

```yaml
provider:
  type: file
```

Скачивание по HTTP (proof-of-concept `HttpApiSourceProvider` в `sports_forecast/data/providers/http_provider.py`): перед ingest выполняется `GET`, ответ записывается в `data/source/<source_name>/source.csv`, дальше pipeline не менается.

```yaml
provider:
  type: http_api
  url: "https://example.com/path/to/export.csv"
  timeout_sec: 30
  retries: 3
```

NHL Web API (`NhlWebApiSourceProvider`, пакет `sports_forecast/data/providers/nhl/`): многократные запросы к `api-web.nhle.com`, сбор `source.csv` по полям из `docs/cursor/source_data/nhl.md`. См. `conf/source/nhl.yaml` (`provider.type: nhl_web_api`): при `finished_only: false` в файл попадают и предстоящие матчи (`match_is_end=0`), завершённые обогащаются boxscore/PBP (`match_is_end=1`). Коэффициенты БК в этом API отсутствуют — для линий букмекеров используется отдельный источник (The Odds API); политика: сбор кэфов для валидации/бенчмарка, **не** как признаки для обучения — см. `docs/cursor/source_data/the_odds_api.md`.

Smart Tables API (`SmartTablesSourceProvider`, пакет `sports_forecast/data/providers/smart_tables/`): футбол / **сборные** через `backend.smart-tables.ru`. См. `conf/source/smart_tables.yaml` (`provider.type: smart_tables_api`), ingest-slug `football_nationals` (`conf/source/football_nationals.yaml` → defaults на smart_tables). Bronze и `source.csv` лежат в **`data/source/football_nationals/`** (как у NHL: каталог = ingest-slug).

**Отличия от NHL:**

| Аспект | NHL | Football (Smart Tables) |
|--------|-----|-------------------------|
| Ничья | Нет | `winner` = 1X2 (home / draw / away); таргет Phase 2 — 3-class |
| Тоталы | линии 3.5–9.5 | линии **1.5, 2.5, 3.5, 4.5** (`conf/sport/football.yaml`) |
| Турниры | один `nhl` | один pool `football_nationals`, фильтр `competition_code` / `match_importance` |
| Источник odds | The Odds API (merge) | ST card 1X2 best-effort; исторические кэфы — отдельный epic |
| Backfill | ~26 ч, checkpoint | ~93k запросов, rate limit 1 req/s, raw JSON cache |

Ops: `make football-catalog-refresh`, `make football-backfill`, `make football-ingest-debug` (env `SF_SMART_TABLES_MAX_MATCHES`, `SF_SMART_TABLES_COMPETITION_CODES`). Документация колонок: `docs/cursor/source_data/football.md`.

Контракт всех адаптеров — абстрактный класс `SourceProvider` в `sports_forecast/data/providers/base.py` (метод `fetch(source_name) -> Path`).

### Как создать свой SourceProvider

1. Добавьте класс, наследуйте `SourceProvider`, реализуйте `fetch` (и при необходимости переопределите `is_available`).
2. Введите понятные исключения-подклассы `SourceProviderError`, чтобы ingest мог логировать сбой единообразно.
3. Зарегистрируйте тип в `ProviderRegistry.create` в `sports_forecast/data/providers/registry.py` (новое значение `provider.type`).
4. Опишите поля конфига в комментариях к классу и в этом документе.
5. Добавьте unit-тесты с моками внешних систем.

---

## Odds для обучения и BettingSimulator (dict vs merge wide)

На **test/holdout** тренер может считать бизнес-метрики (`BettingSimulator`), если в строках датасета есть коэффициенты в форме, которую понимает единый вход `sports_forecast.betting.odds.extract_betting_odds` (по сути `odds_raw` или явный `odds_transport` в профиле букмекера).

| Источник | Как попадает в parquet | Конфиг |
|----------|-------------------------|--------|
| CSV/фид с Python-dict в колонке | `column_mapping` → `odds_raw`, ingest | `conf/source/*.yaml` → `odds.bookmaker: fonbet` (или другой dict-профиль) |
| The Odds API (merge wide в `source.csv`) | На **clean** из `pinnacle_*` close собирается **synthetic** строка `odds_raw` (контракт как у UEL/LP) | `conf/bookmaker/the_odds_api.yaml` (`synthetic_odds_raw`, `market_keys`, `side_keys`); турнир: `data_clean.build_synthetic_odds_raw`, `synthetic_odds_raw_bookmaker` (см. `conf/tournament/nhl.yaml`) |

- **Реестр команд** для сопоставления API ↔ источник: `conf/bookmaker/team_name_registry/` (NHL и др.).
- **Источник и авто-merge**: `conf/source/nhl.yaml` → секция `odds` (`bookmaker`, `bookmakers`, `store_path`, …).
- **Профиль букмекера для train**: для NHL с дефолтным `fonbet` из корня `conf/config.yaml` перед обучением подставляется `the_odds_api` (`apply_tournament_default_bookmaker` в `sports_forecast.config.validation`).
- **Не в модель**: `pinnacle_*` снимаются перед FeaturePipeline (`features_build.py`); `odds_raw` остаётся мета-колонкой (`column_utils.META_COLUMNS`).

Альтернатива без dict (редко): в профиле букмекера задать `odds_transport.mode: wide_columns` и кандидатов колонок — см. комментарии в `conf/bookmaker/the_odds_api.yaml`.

---

## Шаг 3. Положить исходные данные

Разместите CSV/JSON файл в:

```
data/source/<source_name>/source.csv
```

Пример:
```
data/source/nba/source.csv
```

**Минимальные обязательные столбцы:**
- `id` — уникальный идентификатор матча
- `datetime` — дата и время матча
- `status` — статус матча (finished, upcoming, live)
- Столбцы со счётом (будут замаплены через `column_mapping`)
- Имена участников

---

## Шаг 4. Создать tournament конфиг

Создайте `conf/tournament/<tournament_name>.yaml`:

```yaml
# conf/tournament/nba.yaml

# Наследование от спорта
defaults:
  - /sport@_here_: basketball

name: nba
region: usa

# Пути к обработанным данным
data:
  processed_dir: data/processed/nba
  formats:
    long: train_long.parquet
    wide: train_wide.parquet
  inference:
    long: inference_long.parquet
    wide: inference_wide.parquet

# Опционально: override form_params для конкретного турнира
# form_params:
#   fg_trigger_minutes: 2880
#   dp_trigger_minutes: 120

# Турнир-специфичные настройки clean
data_clean:
  # Если нужны дополнительные derived_columns
  derived_columns:
    season:
      source: datetime
      transform: extract_year

  # Финальный набор колонок для interim
  select_columns:
    - id
    - datetime
    - status
    - home_points
    - away_points
    - home_team
    - away_team

# Метаданные (опционально)
stats:
  avg_home_points: 110
  avg_away_points: 108
  avg_total: 218

time_range:
  start: "2024-01-01"
  end: "2025-12-31"
```

**Ключевые моменты:**

- `defaults: [/sport@_here_: <sport>]` — наследует все настройки от спорта
- `feature_pipeline_overrides` — при необходимости дифф к `feature_pipeline` спорта (см. раздел выше)
- `data.processed_dir` — куда будут сохранены обработанные данные
- `data_clean.select_columns` — какие столбцы попадут в interim данные
- `target_sources`, `allowed_market_specs` — наследуются из спорта (можно override)

---

## Шаг 5. Обновить DVC и feature pipeline

DVC для этапа `features` уже использует **multirun** по списку турниров; менять `features=` в команде не требуется: состав генераторов определяется **спортом** и `feature_pipeline` (R29). После изменения `conf/features/`, `conf/sport/` или модулей композиции выполните `dvc repro features` (или полный `make dvc-repro`) и закоммитьте обновлённый **`dvc.lock`** — хэши `processed` и зависимостей сменятся.

### Добавить турнир в DVC pipeline

Отредактируйте `dvc.yaml`, добавив новый турнир в список:

```yaml
features:
  cmd: >-
    uv run python -m sports_forecast.features.features_build --multirun
    tournament=uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by,nba
    features=${features.config}
```

---

## Шаг 6. Запустить pipeline

```bash
# Полный pipeline: ingest → clean → features
make dvc-repro

# Или поэтапно:
uv run python -m sports_forecast.data.ingest
uv run python -m sports_forecast.data.clean
uv run python -m sports_forecast.features.features_build \
    tournament=nba features=basic
```

---

## NHL: baseline-обучение, promote и API (оператору)

Канонический slug турнира — **`nhl`**: единственный файл ``conf/tournament/nhl.yaml`` (в т.ч.
``train_eval_split`` для holdout), ``data/source/nhl/``, ``models/nhl/…``, MLflow-префикс ``nhl__<market>``.
Deprecated-алиас ``conf/tournament/nhl_train.yaml`` удалён (R41): везде ``tournament=nhl``.
Подробности миграции: ``docs/cursor/context/nhl_single_tournament_slug.md``.

```bash
# Sweep обучения (CatBoost + LightGBM, advanced фичи, season holdout — см. YAML)
make train-sweep-nhl

# Лучшая модель в MLflow UI, затем promote (эксперимент = имя турнира + рынок)
make promote EXP=nhl__winner METRIC=test_logloss DIR=minimize

# Материализация из promoted ``models/nhl/winner/best/deploy.yaml``
make materialize TOURNAMENT=nhl MARKET=winner SPEC=winner

# Smoke API (после ``make api-dev``): предстоящие матчи и конкретный game_id
curl -s "http://127.0.0.1:8000/predict/upcoming/nhl?market=winner"
curl -s "http://127.0.0.1:8000/predict/<GAME_ID>?market=winner"
```

---

## Шаг 7. Проверить результат

```bash
# Проверить структуру данных
ls data/raw/nba/
ls data/interim/nba/
ls data/processed/nba/

# Валидация данных
make validate-data

# Тестовое обучение
make train TOURNAMENT=nba MARKET=winner SPEC=winner ALG=catboost FEAT=basic

# Просмотр результатов в MLflow
make mlflow-ui
```

---

## Чеклист

- [ ] Спорт определён (существующий или новый `conf/sport/<name>.yaml`)
- [ ] Source конфиг создан: `conf/source/<name>.yaml`
- [ ] **Один файл турнира**: `conf/tournament/<slug>.yaml` — defaults из source/sport через Hydra `@packaging`, без отдельного `*_train` YAML для того же slug (правило R38/R41, см. `nhl_single_tournament_slug.md`)
- [ ] Данные размещены: `data/source/<name>/source.csv`
- [ ] Турнир добавлен в `dvc.yaml`
- [ ] `make dvc-repro` — pipeline отработал без ошибок
- [ ] `make validate-data` — данные прошли валидацию
- [ ] `make train TOURNAMENT=<name>` — обучение прошло
- [ ] Результаты видны в MLflow

---

## Частые ошибки

### 1. `KeyError: '<column_name>'`

Проверьте `column_mapping` в спортивном конфиге. Исходные имена столбцов в CSV должны точно соответствовать ключам маппинга.

### 2. `Target contains only one class`

Таргет вычисляется некорректно. Проверьте `target_sources` — правильные ли столбцы используются для сравнения.

### 3. `No data for tournament <name>`

Source конфиг или split rules не находят данные. Проверьте `split_strategy.split_column` и условия `rules`.

### 4. Пустые фичи

Проверьте `data_clean.select_columns` — все необходимые столбцы должны быть в списке.

### 5. `odds_raw` не проходит через pipeline

Убедитесь, что `column_mapping` содержит маппинг для odds столбца:
```yaml
column_mapping:
  your_odds_column_name: odds_raw
```
