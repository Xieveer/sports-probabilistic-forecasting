# Football (Smart Tables) — целевые колонки датасета

**Статус:** Phase 1 ingest (R42).
**Источник:** неофициальный backend Smart Tables (`backend.smart-tables.ru`).
**Scope:** матчи **национальных сборных** (37 турниров, `for_national_teams=1`), ~11.6k матчей.
**Разведка API:** [`smart_tables.md`](smart_tables.md), каталог [`smart-tables/competition_catalog.json`](smart-tables/competition_catalog.json).

| Слой | Путь |
|------|------|
| Bronze JSON | `data/source/smart_tables/raw/{match_id}/` |
| Ingest CSV | `data/source/smart_tables/source.csv` |
| DVC raw | `data/raw/football_nationals/matches.parquet` |
| DVC interim | `data/interim/football_nationals/matches_interim.parquet` |

Ingest-турнир: `football_nationals` (конфиг `conf/tournament/football_nationals.yaml`).
Каталог данных и bronze-кэш: `data/source/smart_tables/` (поле `name` в `conf/source/smart_tables.yaml`).

> **HAR:** файлы `*.har` содержат cookies — не коммитить (см. `.gitignore`).

---

## Planned markets (Phase 2)

| Family | Specs | Lines | Target | Prematch odds |
|--------|-------|-------|--------|---------------|
| `winner` | `winner_home` (3-class с ничьей) | — | `home_win` (draw-aware) | внешний источник; ST card — best-effort колонки |
| `total` | `total_over`, `total_under` | **1.5, 2.5, 3.5, 4.5** | `total_sum` / `total_sum_under` | внешний источник |

Формула тотала: `total_goals = home_points + away_points` (FT, без доп. API).
Для линии `L`: over если `total_goals > L`, under если `total_goals < L` (push при равенстве — по политике market_spec).

Обучение: отдельный прогон на каждую пару `(market_spec, line)`, как в киберхоккее (`market=total`, `market_spec=total_over`, `market_spec.line=2.5`).

---

## Контракт идентификаторов

| Поле source | Назначение |
|-------------|------------|
| `match_id` | Primary key ingest → `id` после clean |
| `match_center_id` | Match-center, stat-odds (incremental) |
| `competition_id` | FK турнира ST |
| `competition_code` | WC, EURO, FRII, … — фильтр при обучении |

---

## Обязательные колонки (ядро)

| Колонка | Тип | API / правило |
|---------|-----|---------------|
| `id` | str | `match_id` (после clean) |
| `datetime` | ISO UTC | `begin_at` |
| `status` | str | derived: `finished` / `upcoming` из `match_is_end` + счёт |
| `match_is_end` | 0/1 | `status == finished` |
| `home_team` | str | `home_team_name` (`common_title`) |
| `away_team` | str | `away_team_name` |
| `home_points` | float | `home_score_ft` |
| `away_points` | float | `away_score_ft` |

---

## Мета и контекст турнира

| Колонка | Описание |
|---------|----------|
| `match_center_id` | ID match-center |
| `competition_id`, `competition_code`, `season_id` | Турнир / сезон |
| `match_status` | Сырой статус ST (`finished`, `not-started`, …) |
| `match_importance` | 1=friendly … 4=flagship (см. ниже) |
| `is_friendly` | 1 если `competition_code == FRII` |
| `competition_is_cup`, `competition_is_top` | Из объекта `competition` |
| `stage`, `round`, `group` | Стадия (если есть) |
| `home_team_id`, `away_team_id` | ID команд ST |
| `home_is_national`, `away_is_national` | Фильтр ingest: оба = 1 |
| `home_score_ht`, `away_score_ht` | Из `stat[goals]` period=`first` |
| `referee_id`, `referee_name` | Судья |
| `home_coach_id`, `home_coach_name`, `away_coach_id`, `away_coach_name` | Тренеры |

### `match_importance`

| Значение | Условие |
|----------|---------|
| 1 | `competition.code == 'FRII'` |
| 4 | `competition.is_top == 1` |
| 3 | `competition.is_cup == 1` (и не tier 1/4) |
| 2 | остальные сборные (`for_national_teams=1`) |

---

## Статистика матча (wide)

11 кодов × 3 периода (`all`, `1h`, `2h`):

`goals`, `xg`, `corners`, `yellowcards`, `offsides`, `shotstarget`, `attacks`, `dattacks`, `possession`, `redcards`, `yellowcards_bet365`

Именование: `home_{code}_{period}`, `away_{code}_{period}`
Периоды API: `all` → `all`, `first` → `1h`, `second` → `2h`.

---

## Chart (голы по минутам)

| Колонка | Содержание |
|---------|------------|
| `home_goal_minutes_all`, `away_goal_minutes_all` | JSON-массив минут, period=all |
| `home_goal_minutes_1h`, `away_goal_minutes_1h` | period=first |
| `home_goal_minutes_2h`, `away_goal_minutes_2h` | period=second |

---

## Коэффициенты (best-effort, nullable)

| Колонка | API |
|---------|-----|
| `odd_home`, `odd_draw`, `odd_away` | `odd_home`, `odd_x`, `odd_away` в карточке матча |

Исторические кэфы winner + total (1.5–4.5) — **отдельный epic** (API-Football / Odds API).
Stat-odds ST — только incremental upcoming/live → sidecar `match_stat_odds.parquet`.

---

## API → CSV (краткая таблица)

| Endpoint | Файл bronze | Колонки |
|----------|---------------|---------|
| `GET /matches/{id}` + relatedEntities | `card.json` | id, teams, score, odds, competition, coaches, referee |
| `GET /matches/{id}/stat?period=*` | `stat_{period}.json` | `home_*_{period}`, `away_*_{period}` |
| `GET /matches/{id}/chart?stat=goals` | `chart_{period}.json` | `*_goal_minutes_{period}` |
| `GET /matches/{id}/similar` | `similar.json` | (опционально, для features) |
| `GET /matches?filter[competition_id]=` | `lists/` | список `match_id` |

---

## Фильтры

**Ingest:** `for_national_teams == 1`, `home_is_national == 1`, `away_is_national == 1`.
**Обучение (конфиг):** `is_friendly == 0` или `match_importance >= 3`.

---

## Ссылки

- Полная разведка: [`smart_tables.md`](smart_tables.md)
- Каталог турниров: [`smart-tables/competition_catalog.json`](smart-tables/competition_catalog.json)
- Source config: `conf/source/smart_tables.yaml`
- Sport: `conf/sport/football.yaml`
- Tournament: `conf/tournament/football_nationals.yaml`
