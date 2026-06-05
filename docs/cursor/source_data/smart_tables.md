# Smart Tables — футбол / сборные: разведка API и объём данных

**Статус:** готово для передачи архитектору (разведка завершена, реализация ingest — нет).
**Дата актуализации:** 2026-05-31.
**Артефакты:** [`smart-tables/`](smart-tables/) (HAR, HTML, `competition_catalog.json`).

| Слой | URL |
|------|-----|
| Фронт (Nuxt SSR) | `https://smart-tables.ru/` |
| Backend (реальный JSON API) | `https://backend.smart-tables.ru/api/v1/` |
| Odds-подмодуль | `https://backend.smart-tables.ru/api/v1/odds/` |

---

## Кратко для архитектора

### Цель

Подключить **неофициальный** backend Smart Tables как источник матчевой и турнирной статистики **сборных** к ЧМ-2026 и смежным турнирам. Образец интеграции в репо — NHL (`conf/source/nhl.yaml`, `docs/cursor/source_data/nhl.md`).

### Решения (зафиксировано / открыто)

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | **Scope датасета** | **Все матчи сборных** по всем доступным турнирам: **37** competitions, **`for_national_teams=1`**, **~11 599** матчей (`competition_catalog.json`). Клубные турниры со страницы nationals (**76** лиг, ~181k матчей) — **вне scope**. |
| 2 | **Товарищеские vs важные** | В датасет попадают **оба типа**; обязательна колонка **`match_importance`** (см. раздел ниже) для фильтрации при обучении. |
| 3 | **Статистика для обучения** | Собирать **всё доступное через backend** по каждому матчу: карточка, stat×3 периода, chart goals×3 периода, similar, тренер; prematch 1X2 из карточки. |
| 4 | **stat-odds** | Отдельный **prematch-only** слой; для finished-истории **пусто**. |
| 5 | **Составы** | **Не в backend API** (см. раздел «Составы»); для MVP ingest — **не блокер**; отдельный трек / другой источник. |
| 6 | **ID primary key** | **`match_id`** — основной; `match_center_id` — для stat-odds и match-center. |
| 7 | **Правовой риск** | Личный проект: rate limit + кэш; прод — API-Football / договор. |

### Минимальный backlog (после решений)

1. `docs/cursor/source_data/football.md` — целевые колонки (черновик ниже в этом файле).
2. `conf/source/smart_tables.yaml` — provider, rate limit, competition whitelist.
3. `sports_forecast/ingest/smart_tables.py` (или `data/providers/smart_tables/`) — bronze JSON → `source.csv`.
4. Скрипт каталога: `competition_catalog.json` уже сгенерирован; добавить в CI/ops периодический refresh.
5. DAG / Makefile target: backfill ЧМ, incremental nearest-matches.
6. `.gitignore` для `*.har` (cookies внутри).

### Оценка объёма запросов (полный backfill сборных)

| Шаг | На 1 матч | На ~11 599 матчей |
|-----|-----------|-------------------|
| Каталог 37 турниров (by-slug + total) | — | ~80 |
| Список матчей (пагинация) | — | ~200–400 |
| `/matches/{id}` + 3×`/stat` + 3×`/chart` + `/similar` | **8** | **~92 800** |
| **Итого** | | **~93 000** |
| При **1.5 req/s** | | **~17 ч** (один IP, консервативно) |
| При **1 req/s** + backoff | | **~26 ч** (рекомендуется для первого прогона) |

### Критические ограничения API

- Публичного контракта **нет**; поля и лимиты могут измениться.
- **Два пространства ID:** `match_id` ≠ `match_center_id`.
- Статистика **сборных урезана** (11 метрик vs 31 у клубов); набор **одинаков** для WC, EURO, FRII, UNL, отборочных (проверено live).
- **stat-odds** только для **предстоящих/live** match-center; finished → `stat: []`.
- **Составы** — только SSR HTML (`window.__NUXT__`), не backend; качество под вопросом (см. ниже).
- Captcha на **HTML** фронта; **backend** без captcha (на момент проверки).
- `acl-page-render` → 403 на части вкладок (подписка).

---

## Зачем подключаем

- Матчевая и турнирная статистика **национальных сборных** (ЧМ, EURO, отборочные, Nations League и т.д.).
- Обход HTML-парсинга и Yandex captcha: прямые JSON-ручки на `backend.smart-tables.ru`.
- Быстрый старт к ЧМ-2026; NHL-пайплайн — референс архитектуры ingest.

**Ограничение:** ToS Smart Tables не разрешают автосбор явно. Для продакшена — лицензируемый API (API-Football и др.) или договор с ST.

---

## Методология разведки

Сетевой tab браузера на страницах **finished** часто **не показывает** XHR к backend (данные уже в SSR `window.__NUXT__`). Надёжная цепочка:

```
1. Сохранить HTML страницы (или открыть в браузере с MCP)
2. Найти в HTML ссылки на /_nuxt/*.js
3. В бандлах (grep): axios/fetch URL, Vuex actions (tables/matchStatOdds/UPDATE и т.д.)
4. Пробить backend.smart-tables.ru напрямую (curl/python)
5. Зафиксировать сценарий в HAR (DevTools → Save all as HAR with content)
```

Ключевые бандлы (match-center / odds): `7d49f77.js` — `stat_format`, odds Vuex, пути `/odds/*`.

**Инструменты агента:**

| Инструмент | Назначение |
|------------|------------|
| HAR с content | Полный список backend-запросов + тела ответов |
| `curl` / `urllib` на backend | Live-проверка без captcha |
| Browser MCP | Обход captcha на фронте; навигация по UI |
| `competition_catalog.json` | Машиночитаемый каталог 117 slug |

---

## Пространства идентификаторов (критично)

| Сущность | Поле API | Пример UI URL | Пример |
|----------|----------|---------------|--------|
| Матч (finished, stat, chart) | `match_id` | `/finished/{match_id}` | **314668** (финал ЧМ-2022) |
| Match center (расписание, odds) | `match_center_id` | `/match-center/{match_center_id}` | **123535** (тот же финал) |
| Турнир | `competition_id` | `/league/{country_slug}/{competition_slug}` | **27** (World Cup) |
| Сезон | `season_id` | — | **15** (финал 2022) |
| Команда | `team_id` | `/team/{slug}` | **387** (Argentina) |
| Страна (блок International) | `country_id` | — | **18** |
| Судья | `referee_id` | — | **426** |

**Правило:** для `/matches/{id}/stat` нужен **`match_id`**. Для `/match-center/{id}/stat-odds` — **`match_center_id`**. Подстановка одного вместо другого даёт 200 с пустым `stat`.

Связь в карточке матча: `GET /matches/{match_id}` → поле `match_center_id`.

---

## Формат ответов API

```json
{
  "success": true,
  "data": { ... }
}
```

Ошибки: `success: false`, `errors`, `validation` (HTTP 400/403/404).

Рекомендуемые заголовки:

```http
Origin: https://smart-tables.ru
Referer: https://smart-tables.ru/
Accept: application/json
```

Authorization / Cookie в HAR **не требовались** для перечисленных ручек.

---

## Полный каталог endpoint'ов

### Матч

| Метод | Путь | Query | Назначение | HAR |
|-------|------|-------|------------|-----|
| GET | `/matches/{match_id}` | `relatedEntities=home_team_with_coach,away_team_with_coach,referee,competition` | Карточка матча | HAR1 |
| GET | `/matches/{match_id}/stat` | **`period`**: `all` \| `first` \| `second` | Помatcheвая статистика | HAR1 |
| GET | `/matches/{match_id}/chart` | **`period`**, **`stat`** | Таймлайн событий по минутам | HAR1 |
| GET | `/matches/{match_id}/similar` | — | Похожие матчи | HAR1 |
| GET | `/matches/{match_id}/stat-odds` | `stat`, `stat_format`, `stat_period` | Stat-odds (finished URL) | live |
| GET | `/matches` | см. ниже | Список матчей турнира | HAR1 |

**`/matches` — типичные query:**

| Параметр | Пример | Описание |
|----------|--------|----------|
| `filter[competition_id]` | `27` | Фильтр турнира |
| `offset` / `limit` | `0` / `200` | Пагинация |
| `orderBy` | `begin_at` | Сортировка |
| `orderDir` | `DESC` | Направление |
| `relatedEntities` | `home_team,away_team` | Вложенные команды |

```http
GET /matches?offset=0&limit=200&filter[competition_id]=27&orderBy=begin_at&orderDir=DESC
→ data.total: 128
```

### Match center (расписание, prematch)

| Метод | Путь | Query | Назначение | HAR |
|-------|------|-------|------------|-----|
| GET | `/match-center/{match_center_id}` | — | Карточка предстоящего/live | HAR2 |
| GET | `/match-center/{match_center_id}/stat-odds` | `stat`, `stat_format`, `stat_period` | Коэффициенты на статистику | HAR2 |
| GET | `/match-center/nearest-matches` | `filter[competition_id]`, `offset`, `limit`, `relatedEntities` | Ближайшие матчи | HAR1 |
| GET | `/match-center/odds` | `betsapiId`, `type` | Линии БК (внешний id) | bundle |
| GET | `/match/trends/{match_center_id}` | `location_home`, `location_away` | Тренды команд | HAR2 |

### Турнир / лига

| Метод | Путь | Query | Назначение | HAR |
|-------|------|-------|------------|-----|
| GET | `/competitions/by-slug/` | `country_slug`, `competition_slug`, `relatedEntities` | Slug → `competition_id` | HAR1 |
| GET | `/competitions` | `filter[country_id]=18` | Турниры блока International | HAR1 |
| GET | `/competitions/{id}/stat` | — | Агрегаты турнира | HAR1 |
| GET | `/competitions/{id}/stat/seasons` | — | Статистика по сезонам | HAR1 |
| GET | `/competitions/{id}/stat/teams` | `stat`, `period`, `place`, `last_matches_limit`, `oddsrange` | Таблица команд | HAR1 |
| GET | `/competitions/standings` | `competition_id`, `season_id`, `stage_id[]`, `match_id` | Турнирная таблица | HAR2 |
| GET | `/predictions/competition/{id}` | — | Прогнозы ST | HAR1 |

**Slug-примеры:**

| country_slug | competition_slug | competition_id | for_national_teams | code |
|--------------|------------------|----------------|---------------------|------|
| International | World_Cup | 27 | 1 | WC |
| Europe | Euro | 28 | 1 | EURO |
| Europe | Nations_League | 33 | 1 | UNL |

### Команды, H2H, судья

| Метод | Путь | Query | HAR |
|-------|------|-------|-----|
| GET | `/teams/{id}/head-to-head/{id}` | `stat`, `season[]`, `competition[]`, `period`, `place`, `last_matches_limit` | HAR2 |
| GET | `/referee/stat/base` | `referee_id`, `competition_id` | HAR1 |

### UI-метаданные (stat-pickers)

| Метод | Путь | Query | Назначение |
|-------|------|-------|------------|
| GET | `/stat-pickers/form/match_stat` | — | Допустимые `period` |
| GET | `/stat-pickers/form/match_chart` | — | Допустимые `stat` для chart |
| GET | `/stat-pickers/form/match_stat_odds` | — | Допустимые `stat` для stat-odds |
| GET | `/stat-pickers/form/competition_teams` | `competition_id` | Фильтры таблицы команд |
| GET | `/stat-pickers/form/competition_standings` | `competition_id` | Фильтры standings |
| GET | `/stat-pickers/form/team_to_team` | `competition_id`, `team_id`, `match_center_id` | H2H UI |
| GET | `/stat-pickers/form/template_bot` | — | Telegram bot templates |

### Odds-подмодуль (`/api/v1/odds/`)

| Метод | Путь | Статус разведки |
|-------|------|-----------------|
| GET | `/odds/byIds` | `match_center_id[]`, `bk` — из bundle |
| GET | `/odds/main` | **400** без обязательных params |
| GET | `/odds/mainMatch` | не полностью документирован |
| GET | `/odds/matchHistory` | не полностью документирован |
| GET | `/odds/matchLatest` | не полностью документирован |
| GET | `/odds/trendsType` | не полностью документирован |

Vuex: `tables/matchStatOdds/UPDATE` → `GET match-center/{id}/stat-odds` (для finished в UI: `matches/{id}/stat-odds`).

### ACL / подписка

| Метод | Путь | Результат |
|-------|------|-----------|
| GET | `/acl-page-render` | **403** для `tab=competition_referee`, `competition_id=27` |

### Прочее (низкий приоритет ingest)

| Метод | Путь | HAR |
|-------|------|-----|
| GET | `/telegram-bot/football/template` | `filter[match_center_id]` | HAR2 |

---

## Схемы JSON и маппинг bronze

### `GET /matches/{id}` → `data.item`

| Поле API | Тип | Bronze / feature | Примечание |
|----------|-----|------------------|------------|
| `id` | int | `match_id` | PK |
| `match_center_id` | int | `match_center_id` | для odds |
| `competition_id` | int | `competition_id` | FK |
| `season_id` | int | `season_id` | |
| `begin_at` | ISO datetime | `datetime` | UTC |
| `status` | string | `match_status` | finished / not-started / … |
| `home_team_id`, `away_team_id` | int | `home_team_id`, `away_team_id` | |
| `home_goals`, `away_goals` | int | `home_score_ft`, `away_score_ft` | итог матча |
| `odd_home`, `odd_x`, `odd_away` | float | `odd_1x2_*` | prematch 1X2 ST |
| `referee_id` | int | `referee_id` | |
| `competition` | object | denormalize | `code`, `for_national_teams` |
| `home_team_with_coach` | object | `home_team_name`, `is_national` | |
| `away_team_with_coach` | object | `away_team_name`, `is_national` | |
| `referee` | object | `referee_name` | |

### `GET /matches` list item

Те же ключи, что карточка, плюс вложенные `home_team`, `away_team` (без coach): `id`, `slug`, `title`, `common_title`, `is_national`, `logo`, `total_market_value`.

### `GET /matches/{id}/stat` → `data.stat[]`

| Поле | Тип | Bronze |
|------|-----|--------|
| `code` | string | имя колонки (`goals`, `xg`, …) |
| `home` | number \| null | `home_{code}` |
| `away` | number \| null | `away_{code}` |
| `titles` | object | метаданные UI |

**Нормализация:** одна строка bronze на `(match_id, period)` с wide-колонками `home_goals`, `away_goals`, … или long-format `(match_id, period, stat_code, home, away)`.

### `GET /matches/{id}/chart` → `data.chart`

```json
{
  "home": { "team": {...}, "minutes": ["23", "36"] },
  "away": { "team": {...}, "minutes": ["..."] }
}
```

Для сборных **работает** `stat=goals`; остальные stat в picker **disabled**.

### `GET /competitions/by-slug/` → `data.item`

Ключевые поля: `id`, `code`, `title`, `common_title`, `country_id`, `for_national_teams`, `is_international_cup`, `champion_team_id`, `continent_id`.

### `GET /match-center/{id}/stat-odds`

**`data.stat`** — структура зависит от `stat_format`:

#### `stat_format=totals`

Верхний уровень: `total`, `it1`, `it2`.

```
stat.total.{bookmaker}.{line}.{over|under}.current: { odd, movement, blocked }
stat.total.{bookmaker}.{line}.{over|under}.prev: [{ odd, event_added_at, movement }]
stat.total.{bookmaker}.{line}.margin
```

Линии (пример goals, pari): `0.5`, `1`, `1.5`, `2`, `2.5`, `3`, `3.5`, `4`, `4.5`.

#### `stat_format=1x2_handicaps`

Верхний уровень: `double_change`, `asian_handicap_1`, `asian_handicap_2`, `1x2`.

**`data.bookmakers`:** список БК (10 в HAR): `tennisi`, `pari`, `fonbet`, `winline`, `ligastavok`, `betcity`, `baltbet`, `olimp`, `marathon`, `betBoom`.

---

## Статистика: клуб vs сборная

### Клуб (Liverpool – Brentford, `match_id=584896`)

`GET /matches/584896/stat?period=all` → **31** метрика:

`goals`, `xg`, `corners`, `yellowcards`, `offsides`, `fouls`, `shotstarget`, `throwins`, `attacks`, `dattacks`, `goalkicks`, `possession`, `redcards`, `shots`, `passes`, `saves`, `yellowcards_bet365`, `penalties`, `blockedshots`, `freekicks`, `accpasses`, `passsucc`, `dribbleswon`, `subs`, `aerialswon`, `aerialssucc`, `succtackles`, `tacklesucc`, `interceptions`, `deep`, `ppda`.

### Финал ЧМ-2022 (Argentina – France, `match_id=314668`)

`GET /matches/314668/stat?period=all` → **11** метрик:

| code | home–away | Примечание |
|------|-----------|------------|
| goals | 2–2 | |
| xg | 1.77–1.09 | |
| corners | 4–3 | |
| yellowcards | 2–2 | |
| offsides | 3–2 | |
| shotstarget | 7–3 | |
| possession | 54–46 | |
| redcards | 0–0 | |
| yellowcards_bet365 | 2–2 | |
| attacks | null | |
| dattacks | null | |

**Вывод:** API отдаёт урезанный набор для сборных. Paywall на сайте (замки) **не режет** то, что уже в JSON — данные приходят без подписки.

---

## Stat-odds: полная матрица (live-проверка)

Матч: `match_center_id=505381` (ЧМ-2026, `not-started`, teams 118 vs 1109).
Число в ячейке — количество **верхнеуровневых ключей** в `data.stat` (0 = пустой ответ).

### `stat_format=totals` (ожидаются ключи: total, it1, it2 → **3**)

| stat | all | first | second |
|------|-----|-------|--------|
| goals | 3 | 3 | 3 |
| corners | 3 | 3 | 0 |
| cards | 0 | 0 | 0 |
| yellowcards | 3 | 3 | 1 |
| shotstarget | 1 | 1 | 0 |
| fouls | 1 | 1 | 0 |
| throwins | 1 | 1 | 0 |
| shots | 1 | 1 | 0 |

### `stat_format=1x2_handicaps` (ожидаются 4 ключа)

| stat | all | first | second |
|------|-----|-------|--------|
| goals | 4 | 4 | 4 |
| corners | 4 | 4 | 4 |
| cards | 0 | 0 | 0 |
| yellowcards | 4 | 4 | 4 |
| shotstarget | 4 | 4 | 0 |
| fouls | 4 | 4 | 0 |
| throwins | 3 | 4 | 0 |
| shots | 2 | 0 | 0 |

### Допустимые `stat` (picker `/stat-pickers/form/match_stat_odds`)

`corners`, `cards`, `yellowcards`, `shotstarget`, `goalkicks`, `offsides`, `fouls`, `throwins`, `shots`, `poss`, `saves`, `dribbs`, `interceptions`, `tackles`, `aerials`.

**Примечание:** `goals` в UI по умолчанию, но в picker отдельной строкой не перечислен — работает при прямом запросе.

### `stat_period`

| Значение | Статус |
|----------|--------|
| `all` | OK |
| `first` | OK |
| `second` | OK |
| `2`, `2h`, `halftime` | **400** |

### Finished matches

`match_id=314668`, `match_center_id=123535`: `/stat-odds` → `success: true`, **`stat: []`**.

---

## HAR-файлы: что внутри

### `smart-tables.ru.har` (HAR1)

- **237** записей, **30** уникальных GET к backend (51 с дублями).
- Сценарии: финал ЧМ-2022 (`finished/314668`), турнир World Cup, nationals list.
- Ключевые сущности:

| Поле | Значение |
|------|----------|
| `match_id` | 314668 |
| `match_center_id` | 123535 |
| `competition_id` | 27 |
| `season_id` | 15 |
| `country_id` (International) | 18 |
| `home_team_id` / `away_team_id` | 387 / 300 |
| `is_national` | 1 |

### `smart-tables match with odds.har` (HAR2)

- **~12 MB**, **12** уникальных GET к backend.
- Страница: `match-center/505381` (ЧМ, `competition_id=27`).
- **4×** `/match-center/505381/stat-odds` (goals × totals/1x2_handicaps × all/first).
- Дополнительно: standings, H2H, trends, stat-pickers, telegram-bot template.

---

## Сборные: охват турниров и объём

### Блок `country_id=18` (International) — узкий срез

15 competitions; **9** с `for_national_teams=1`; сумма матчей **~3792** (без клубного FRIC).

### Страница `choose_league/nationals` — полный каталог slug

- HTML: **117** пар `country_slug/competition_slug`.
- Скрипт обхода (2026-05-31): [`competition_catalog.json`](smart-tables/competition_catalog.json).
- **113** slug резолвятся; **4** битые ссылки в HTML (404):

| country_slug | competition_slug | Ошибка |
|--------------|------------------|--------|
| Argentina | Copa_Diego_Maradona | 404 |
| Czech_Republic | 1 | 404 |
| Japan | J | 404 |
| Mexico | Cup | 404 |

### Итоги каталога (113 OK)

| Категория | Турниров | Матчей (sum API `total`) |
|-----------|----------|---------------------------|
| `for_national_teams=1` | **37** | **11 599** |
| `for_national_teams=0` (клубы на странице nationals) | 76 | 181 634 |
| **Всего** | 113 | **193 233** |

### Турниры сборных (37) — полная таблица

| country_slug | competition_slug | id | code | title | matches |
|--------------|------------------|-----|------|-------|---------|
| International | Friendlies | 222 | FRII | Friendlies | 2694 |
| Europe | World_Cup_Qualification | 205 | WCQE | World Cup Qualification | 740 |
| Europe | EURO_U21_Qualification | 341 | EU21Q | EURO U21 Qualification | 692 |
| Europe | Nations_League | 33 | UNL | Nations League | 662 |
| Europe | EURO_U21 | 80 | EU21 | EURO U21 | 657 |
| International | World_Cup_Women_Qualification | 342 | WCWQ | World Cup Women Qualification | 525 |
| Europe | euro-qualification | 365 | EURQ | EURO Qualifiction | 501 |
| Asia | World_Cup_Qualification | 214 | WCQA | World Cup Qualification | 488 |
| Europe | EURO_Women | 306 | EUROW | EURO Women | 471 |
| Europe | EURO_U19 | 204 | EU19 | EURO U19 | 468 |
| Africa | World_Cup_Qualification | 209 | WCQAF | World Cup Qualification | 462 |
| Africa | cup-of-nations-qualification | 366 | AFCNQ | Cup Of Nations Qualification | 458 |
| Central_America | World_Cup_Qualification | 216 | WCCA | World Cup Qualification | 242 |
| Africa | Cup_of_Nations | 78 | AFCN | Cup of Nations | 240 |
| CONCACAF | concacaf-nations-league | 471 | CNCNL | Nations League | 213 |
| South_America | World_Cup_Qualification | 220 | WCQSA | World Cup Qualification | 209 |
| International | World_Cup_U20 | 217 | WCU20 | World Cup U20 | 208 |
| Asia | asian-cup-qualification | 367 | ACCQ | Asian Cup Qualification | 206 |
| Europe | euro-women-qualification | 470 | EURWQ | EURO Women Qualification | 192 |
| Africa | African_Nations_Championship | 305 | AFCNC | African Nations Championship | 172 |
| Europe | EURO | 28 | EURO | EURO | 153 |
| International | World_Cup_Women | 218 | WCW | World Cup Women | 130 |
| International | World_Cup | 27 | WC | World Cup | 128 |
| Europe | euro-u19-qualification | 511 | EU19Q | EURO U19 Qualification | 120 |
| South_America | Copa_America | 71 | COPA | Copa America | 118 |
| Asia | AFC_Asian_Cup | 212 | AFCAC | AFC Asian Cup | 102 |
| International | Olympic_Games | 309 | OLYM | Olympic Games | 96 |
| Central_America | Gold_Cup | 308 | CAGC | Gold Cup | 93 |
| Africa | CECAFA_Championship | 210 | CECAFA | CECAFA Championship | 57 |
| Asia | afc-u23-asian-cup | 522 | AFCU23 | AFC U23 Asian Cup | 32 |
| Africa | cosafa-cup | 520 | COSAFA | COSAFA Cup | 22 |
| Africa | cosafa-women-s-cup | 521 | COSAFW | COSAFA Women's Cup | 19 |
| Oceania | world-cup-qualification | 482 | WCCO | World Cup Qualification | 18 |
| International | world-cup-qualification-intercontinental-playoff | 340 | WCQIC | WC Qual. Inter Confederation Playoffs | 10 |
| International | finalissima | 319 | FIN | Finalissima | 1 |
| Europe | euro-u19-women | 513 | EU19W | EURO U19 Women | 0 |
| International | world-cup-u20-women | 512 | WCU20W | World Cup U20 Women | 0 |

Полный JSON (включая 76 клубных турниров со страницы nationals): `smart-tables/competition_catalog.json`.

---

## Классификация: товарищеские vs «важные» матчи

В датасет входят **все** ~11 599 матчей сборных, включая **2 694** товарищеских (`FRII`, `competition_id=222`). Для обучения и фильтрации — производная колонка **`match_importance`** (int 1–4 или enum).

### Правила (предложение для ingest)

| `match_importance` | Условие | Примеры `competition.code` | Матчей (approx) |
|--------------------|---------|----------------------------|-----------------|
| **1 — friendly** | `code == 'FRII'` | FRII | 2 694 |
| **2 — regional / youth / minor** | `for_national_teams=1` и не tier 1/3/4 | EU21, EU19, COSAFA, CECAFA, U20/U23, женские отборочные | ~3 500 |
| **3 — competitive** | Отборочные, Nations League, континентальные кубки (не топ) | WCQE, WCQA, WCQAF, UNL, EURQ, AFCNQ, CNCNL | ~4 200 |
| **4 — flagship** | `is_top == 1` или финальные турниры | WC, EURO, COPA, AFCAC, AFCN, OLYM, FIN | ~600 |

Альтернатива попроще для первой итерации:

```python
is_friendly = competition.code == "FRII"
is_competitive = not is_friendly and competition.is_cup == 1
is_flagship = competition.is_top == 1
```

### Поля competition для тегирования (из API)

| Поле | FRII (товарищ.) | WC | EURO | UNL | WCQE |
|------|-----------------|-----|------|-----|------|
| `code` | FRII | WC | EURO | UNL | WCQE |
| `for_national_teams` | 1 | 1 | 1 | 1 | 1 |
| `is_cup` | 0 | 1 | 1 | 1 | 1 |
| `is_top` | 0 | 1 | 1 | 0 | 1 |
| `is_international_cup` | 0 | 0 | 0 | 0 | 0 |
| `is_free` | 0 | 0 | 0 | 0 | 0 |

Дополнительно в матче: `season_id`, `stage` / `round` / `group` (из match-center, если нужен контекст стадии плей-офф).

**Для обучения:** хранить все матчи в `source.csv`; в конфиге модели / split — `exclude_friendly: true` или `min_match_importance: 3`.

---

## Полный перечень данных для обучения (backend)

Для **каждого** матча с `for_national_teams=1` и обеими командами `is_national=1`:

### Обязательно (bronze → source)

| # | Endpoint | Что сохраняем |
|---|----------|---------------|
| 1 | `GET /matches/{id}?relatedEntities=home_team_with_coach,away_team_with_coach,referee,competition` | IDs, счёт, дата, status, odd_1x2, competition metadata, **тренеры**, судья |
| 2 | `GET /matches/{id}/stat?period=all` | 11 метрик × home/away |
| 3 | `GET /matches/{id}/stat?period=first` | то же, первый тайм |
| 4 | `GET /matches/{id}/stat?period=second` | то же, второй тайм |
| 5 | `GET /matches/{id}/chart?period=all&stat=goals` | минуты голов home/away |
| 6 | `GET /matches/{id}/chart?period=first&stat=goals` | голы 1-й тайм |
| 7 | `GET /matches/{id}/chart?period=second&stat=goals` | голы 2-й тайм |
| 8 | `GET /matches/{id}/similar` | список похожих матчей (опционально для feature engineering) |

### 11 метрик сборных (единый набор, проверено на WC / EURO / FRII / UNL / WCQE)

`goals`, `xg`, `corners`, `yellowcards`, `offsides`, `shotstarget`, `attacks`, `dattacks`, `possession`, `redcards`, `yellowcards_bet365`.

`attacks` / `dattacks` часто **null**, но поле присутствует — сохранять как nullable.

### Производные для source.csv (без доп. запросов)

- `home_score_ht`, `away_score_ht` ← `stat[goals].home/away` при `period=first`
- `match_importance` ← правила из раздела выше
- `is_friendly` ← `competition.code == 'FRII'`

### Не для исторического backfill (отдельный incremental слой)

- `GET /match-center/{id}/stat-odds` — только prematch/live
- `GET /competitions/{id}/stat/teams` — турнирные агрегаты (для pre-match features «форма в турнире», не per-match backfill)

### Не собирать

- Клубные турниры (`for_national_teams=0`) — даже если есть на странице nationals
- HTML/SSR парсинг в основном пайплайне (captcha) — исключение: составы (отдельный трек)

---

## Составы и игроки

### Краткий ответ

**Полноценных составов (lineups) в backend API нет.** В разведке **не найдено** рабочих ручек вида `/matches/{id}/lineups` (все варианты → 404 или пусто). Составы отдаются **только в SSR** страницы `/finished/{match_id}` внутри `window.__NUXT__.state.finished.detail.lineups`.

### Что есть в API без HTML

| Ручка | Сборные | Клубы | Содержание |
|-------|---------|-------|------------|
| `relatedEntities=home_team_with_coach` | да | да | **`coaches[]`**: id, name, birth_date, is_current |
| `GET /teams/{id}/players` | **пустой `[]`** (Argentina 387) | полный список (Liverpool 11, ~тысячи игроков) | id, name_en, name_ru, country, … |
| `/teams/{id}/squad`, `/roster`, `/lineup` | 404 | 404 | — |
| `relatedEntities=lineups` / `players` | не расширяет ответ матча | — | — |

Тренеры для сборных **доступны** (финал ЧМ-2022: Lionel Scaloni в `home_team_with_coach.coaches`).

### Структура lineups в SSR (если парсить HTML)

Путь в Nuxt: `state.finished.detail.lineups.items`.

```json
{
  "home": {
    "base": [{ "number": 23, "position": "НАП", "country": "ar", "name": "..." }],
    "replacement": [{ "number":  ..., "position": "...", "country": "...", "name": "..." }]
  },
  "away": { "base": [...], "replacement": [...] }
}
```

Поля: **`number`**, **`position`** (ВРТ/ЗАЩ/ПЗЩ/НАП), **`country`** (ISO-подобный код), **`name`**. **`player_id` нет** — только имя.

### Проблема качества (важно)

На сохранённой странице финала ЧМ-2022 (`finished/314668`) в `lineups` — **явно нерелевантные игроки** (Tim Krul, Max Aarons, Grant Hanley — не состав Аргентины/Франции в финале). То же в HAR. Возможные причины: заглушка без подписки, баг ST, урезанный demo-block.

**Вывод для датасета:** не закладывать составы в MVP ingest через ST; для player-level features — **другой источник** (API-Football lineups, Transfermarkt, и т.д.) или отдельная разведка с проверкой качества на выборке из 50 матчей через browser MCP.

### Рекомендация архитектору

| Данные | Источник ST | Действие |
|--------|-------------|----------|
| Матч, счёт, stat, chart | backend API | **основной ingest** |
| Тренер | backend API | **включить** |
| Судья | backend API | **включить** |
| Состав поле / скамейка | SSR HTML only | **фаза 2** или другой provider |
| Ростер сборной | `/teams/{id}/players` пусто | **не использовать ST** |

---

## Целевые колонки датасета (черновик football / smart_tables)

Аналог `docs/cursor/source_data/nhl.md`. Scope: **все матчи сборных**, ~11.6k строк.

### Идентификация и контекст

- `match_id` (ST)
- `match_center_id`
- `competition_id`, `competition_code` (WC, EURO, FRII, …)
- `season_id`
- `datetime` (`begin_at`, UTC)
- `match_status` (finished / not-started / live / …)
- `match_is_end` (1/0)
- `match_importance` (1–4, см. классификацию)
- `is_friendly` (0/1, `competition_code == 'FRII'`)
- `competition_is_cup`, `competition_is_top` (из competition)
- `stage`, `round`, `group` (если есть в match-center)

### Команды

- `home_team_id`, `away_team_id`
- `home_team_name`, `away_team_name` (`common_title`)
- `home_is_national`, `away_is_national`
- `home_market_value`, `away_market_value` (опционально)

### Счёт

- `home_score_ft`, `away_score_ft`
- `home_score_ht`, `away_score_ht` (из `period=first` stat `goals`, если нужно)

### Тренеры

- `home_coach_id`, `home_coach_name`
- `away_coach_id`, `away_coach_name`

### Статистика матча (wide; 11 кодов × 3 периода)

Коды: `goals`, `xg`, `corners`, `yellowcards`, `offsides`, `shotstarget`, `attacks`, `dattacks`, `possession`, `redcards`, `yellowcards_bet365`.

Именование: `home_{code}_{period}` / `away_{code}_{period}`, где `period` ∈ `all`, `1h`, `2h`.

### События (chart, `stat=goals`)

- `home_goal_minutes_all`, `away_goal_minutes_all`
- `home_goal_minutes_1h`, `away_goal_minutes_1h`
- `home_goal_minutes_2h`, `away_goal_minutes_2h` (JSON arrays минут)

### Коэффициенты (опционально, prematch)

- `odd_home`, `odd_draw`, `odd_away` (из карточки матча)
- stat-odds — отдельная таблица `match_stat_odds` (long format)

### Судья

- `referee_id`, `referee_name`

### Составы (не в MVP ST-ingest)

- `home_lineup_base`, `away_lineup_base` — только при подключении SSR/внешнего источника
- без `player_id` в ST

### Фильтры качества ingest

- `competition.for_national_teams == 1`
- `home_is_national == 1 AND away_is_national == 1`

### Фильтры обучения (конфиг модели, не ingest)

- `is_friendly == 0` или `match_importance >= 3`

---

## Rate limit / бан

| Тест | Результат |
|------|-----------|
| 30× подряд `GET /matches/314668/stat` | все **200**, ~9 с |
| Captcha на backend | **нет** |
| Captcha на smart-tables.ru HTML | **да** (Yandex) |
| Явный `X-RateLimit-*` в ответах | **не обнаружен** |

### Рекомендации ingest

- Только **backend.smart-tables.ru** (не качать HTML в bulk).
- `Origin` + `Referer` как у браузера.
- **1–2 req/s** при массовой выкачке.
- Кэш raw JSON на диск (`data/source/smart_tables/raw/`).
- Exponential backoff на 429/403/5xx.
- Checkpoint-файл (как `.nhl_checkpoint.txt`).

### План контролируемого stress-теста (не выполнен)

| Этап | Запросов | Критерий остановки |
|------|----------|-------------------|
| 1 | 500 | все 200, нет 429 |
| 2 | 2000 | то же, 1 req/s |
| 3 | 5000 | ночной батч, лог latency |

Оценка полного backfill сборных (~11.6k × 8 req): **~93k запросов** → при 1.5 req/s ≈ **17 ч** (см. раздел архитектора).

---

## Пайплайн ingest (черновик)

```
Phase A — каталог
  1. Загрузить competition_catalog.json ИЛИ
     competitions?filter[country_id]=18 + by-slug для whitelist
  2. Отфильтровать for_national_teams == 1

Phase B — матчи
  3. matches?filter[competition_id]={id}&limit=200&offset=...&orderBy=begin_at
  4. Checkpoint по (competition_id, offset)

Phase C — детали матча (на каждый match_id)
  5. GET /matches/{id}?relatedEntities=home_team_with_coach,away_team_with_coach,referee,competition
  6. GET /matches/{id}/stat?period=all|first|second
  7. GET /matches/{id}/chart?period=all|first|second&stat=goals
  8. GET /matches/{id}/similar
  9. Вычислить match_importance, is_friendly из competition

Phase D — prematch incremental (DAG)
  10. match-center/nearest-matches?filter[competition_id]=...
  11. GET /match-center/{id}/stat-odds (только not-started/live)

Phase E — normalize
  12. bronze JSON → source.csv (football schema)
  13. Фильтр is_national; все матчи включая FRII

Phase F — составы (опционально, вне основного backend-пайплайна)
  14. Browser / SSR parse finished HTML → lineups (качество проверить!)
  15. Или внешний provider с player_id
```

Конфиг (будущее): `conf/source/smart_tables.yaml`, `conf/sport/football.yaml`.

---

## Скрипт каталога slug (outline)

```python
# docs/cursor/source_data/smart-tables/build_competition_catalog.py (предложение)
import re, json, time, urllib.request
from pathlib import Path

HTML = Path("Полный список футбольных лиг на Smart Tables.html")
BASE = "https://backend.smart-tables.ru/api/v1"
HEADERS = {"Origin": "https://smart-tables.ru", "Referer": "https://smart-tables.ru/"}

pairs = sorted(set(re.findall(r"/league/([^/]+)/([^\"']+)", HTML.read_text(encoding="utf-8"))))
catalog = []
for country, comp in pairs:
    time.sleep(0.35)  # ~1.5 req/s с двумя вызовами
    # GET by-slug → competition_id
    # GET matches?filter[competition_id]=...&limit=1 → total
    ...
Path("competition_catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
```

Актуальный результат уже в `smart-tables/competition_catalog.json` (117 записей, 4 ошибки).

---

## Правовые риски и mitigations

| Риск | Вероятность | Mitigation |
|------|-------------|------------|
| Блокировка IP / 429 | средняя | rate limit, backoff, не парсить фронт |
| Изменение API без notice | высокая | versioned raw cache, contract tests на sample IDs |
| ToS / авторские права | неясно | личный некоммерческий use; не републиковать сырые данные |
| Зависимость от ST | высокая | абстракция provider; позже API-Football |
| Cookies в HAR | — | не коммитить HAR в публичный репо |

---

## Пробелы / следующие шаги

- [x] HAR с реальными XHR на backend (HAR1 + HAR2)
- [x] `/stat-odds`, `stat_format` = `totals` | `1x2_handicaps`
- [x] Матрица stat-odds (goals, corners, … × period)
- [x] Скрипт обхода 117 slug → `competition_catalog.json`
- [x] Сравнение метрик EURO / FRII / UNL / отборочные vs ЧМ — **везде 11 stat**
- [ ] Качество lineups SSR на выборке 50 матчей (сейчас: заглушки на финале ЧМ-2022)
- [ ] Внешний источник составов (если нужны player-level features)
- [ ] Контролируемый rate-limit тест: 500 / 2000 / 5000
- [ ] Полная документация `/odds/*` (обязательные query)
- [ ] `docs/cursor/source_data/football.md` как отдельный файл
- [ ] Адаптер ingest по образцу NHL
- [ ] `.gitignore` для `*.har`

---

## Файлы в `smart-tables/`

| Файл | Содержание |
|------|------------|
| `smart-tables.ru.har` | Финал ЧМ-2022, World Cup, nationals; **cookies внутри** |
| `smart-tables match with odds.har` | Match-center 505381; stat-odds подтверждён |
| `competition_catalog.json` | 117 slug → id, code, for_national_teams, match_count |
| `Аргентина - Франция ...html` | Финал ЧМ-2022, SSR |
| `Полный список футбольных лиг ...html` | Каталог 117 лиг со страницы nationals |

**Примечание:** исходно файлы лежали в `~/Документы/SportsProbabilisticForecasting/`; копия синхронизирована в `PyCharmProject/.../docs/cursor/source_data/smart-tables/`.

---

## Как снимать HAR (для будущих сценариев)

1. DevTools → Network → Preserve log.
2. Открыть нужную страницу (match-center, league, finished).
3. Пройти по вкладкам UI (stat, odds, standings).
4. ПКМ → Save all as HAR **with content**.
5. Проверить: `grep backend.smart-tables.ru file.har | wc -l` > 0.

Если backend-запросов 0 — данные в SSR; смотреть `/_nuxt/*.js` или перейти на match-center (там больше XHR).
