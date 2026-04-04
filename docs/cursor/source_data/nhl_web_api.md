# NHL Web API (`api-web.nhle.com`) — обзор эндпоинтов

Документ для проектирования загрузки данных в `source.csv`: какие JSON-структуры отдаёт публичный **NHL Web API**, что в них полезно для матчей/статистики/составов.

> **Неофициально.** API используется сайтом NHL; контракт может меняться без предупреждения.
> Старая документация [dword4/nhlapi на GitHub](https://github.com/dword4/nhlapi) описывает исторический `statsapi.web.nhl.com` (в части окружений **недоступен по DNS**). Актуальное веб-API собирают в [GitLab nhlapi / new-api.md](https://gitlab.com/dword4/nhlapi/-/blob/master/new-api.md).

**Проверено запросами** из репозитория: дата снимка ответов **2026-04-04**.

---

## Базовый URL и HTTP

| Параметр | Значение |
|----------|----------|
| База | `https://api-web.nhle.com/v1/` |
| Формат | JSON |
| Auth | не требуется для перечисленных путей |

**Заголовок `User-Agent`:** голый `urllib` без UA в том же окружении получил **403**; клиент с типовым `User-Agent` (или `requests` из браузера) — **200**.

---

## Идентификаторы (как в ответах)

| Имя | Пример | Комментарий |
|-----|--------|-------------|
| **GAME_ID** (`id` игры) | `2025021173` | Целое; вместе с `season`, `gameDate` однозначно дергаем `gamecenter/...` |
| **SEASON_ID** | `20252026` | Восемь цифр: старт год + финиш год сезона (2025–26) |
| **TEAM_ABBR** | `PIT`, `NYR` | Трёхбуквенный код в URL |
| **gameType** | `1`, `2`, `3` | По смыслу NHL: пресезон / регулярка / плей-офф (уточнять по `gameType` в JSON) |
| **gameState** | `OFF`, `FUT`, `LIVE`, … | `OFF` = завершена (на снимке; в старых примерах встречалось `FINAL`) |

---

## Эндпоинты: таблица

Значение **HTTP** — результат проверки в сессии 2026-04-04.

| HTTP | Метод | Путь | Назначение |
|------|--------|------|------------|
| 200 | GET | `/schedule/now` | Неделя вокруг «сегодня»: `gameWeek[]`, метадаты сезона, `oddsPartners` |
| 200 | GET | `/schedule/{YYYY-MM-DD}` | То же по якорной дате (неделя в ответе) |
| 200 | GET | `/score/now` | Текущий «скорборд»: плоские `games[]` + те же даты; у игр часто есть **`goals`** (голы с ассистами, SOG) |
| 200 | GET | `/club-schedule-season/{TEAM_ABBR}/now` | Полный календарь клуба в текущем контексте: `currentSeason`, массив `games[]` |
| 200 | GET | `/club-schedule/{TEAM_ABBR}/week/now` | Окно недели для клуба |
| 200 | GET | `/club-schedule/{TEAM_ABBR}/month/now` | Окно месяца для клуба |
| 200 | GET | `/standings/now` | Таблица: `standings[]` — одна строка на команду, очки, дифф, дом/гость, streak… |
| 200 | GET | `/standings-season` | Справочник **сезонов** для standings (длинный список `seasons[]` с датами и флагами правил), не сами места команд |
| 404 | GET | `/standings-season/{SEASON_ID}` | В этой проверке **нет** такого пути |
| 200 | GET | `/club-stats-season/{TEAM_ABBR}` | Список по сезонам с кратким `gameTypes` (на PIT — 58 элементов, урезённая сводка) |
| 200 | GET | `/roster/{TEAM_ABBR}/{SEASON_ID}` | Активный состав: `forwards`, `defensemen`, `goalies` — массивы объектов игрока |
| 200 | GET | `/roster-season/{TEAM_ABBR}` | Список **доступных** `SEASON_ID` (массив целых) |
| 200 | GET | `/player/{PLAYER_ID}/landing` | Карточка игрока: био, команда, `featuredStats`, `careerTotals`, `last5Games`, … |
| 200 | GET | `/gamecenter/{GAME_ID}/boxscore` | Бокссчёт: команды (`score`, `sog`, …), `playerByGameStats`, и т.д. |
| 200 | GET | `/gamecenter/{GAME_ID}/play-by-play` | Полный PBP: массив **`plays`** (сотни событий), плюс метаданные матча |

Дополнительные пути перечислены в [new-api.md](https://gitlab.com/dword4/nhlapi/-/blob/master/new-api.md); здесь — только то, что явно «подёргано» и зафиксировано.

---

## Примеры фрагментов JSON (реальные поля)

### 1. Игра в `schedule/{date}` — ключи верхнего уровня объекта игры

Типичные поля одного матча в `gameWeek[].games[]`:

- `id`, `season`, `gameType`, `venue`, `neutralSite`, `startTimeUTC`, таймзоны
- `gameState`, `gameScheduleState`
- `tvBroadcasts[]`
- `awayTeam` / `homeTeam` (в т.ч. `abbrev`, `score` для завершённых)
- `periodDescriptor`, `gameOutcome`, `winningGoalie`, `winningGoalScorer`
- ссылки `gameCenterLink`, `threeMinRecap`, …

### 2. `score/now` — игра с перечнем голов (удобно для «линии» без второго запроса)

Искусственно укорочено; в ответе те же поля, что в живом API:

```json
{
  "id": 2025021207,
  "season": 20252026,
  "gameType": 2,
  "gameDate": "2026-04-04",
  "venue": { "default": "Madison Square Garden" },
  "startTimeUTC": "2026-04-04T16:30:00Z",
  "gameState": "OFF",
  "awayTeam": {
    "id": 17,
    "name": { "default": "Red Wings" },
    "abbrev": "DET",
    "score": 1,
    "sog": 32,
    "logo": "https://assets.nhle.com/logos/nhl/svg/DET_light.svg?season=20252026"
  },
  "homeTeam": {
    "id": 3,
    "name": { "default": "Rangers" },
    "abbrev": "NYR",
    "score": 4,
    "sog": 20
  },
  "clock": {
    "timeRemaining": "00:00",
    "secondsRemaining": 0,
    "running": false
  },
  "periodDescriptor": { "number": 3, "periodType": "REG", "maxRegulationPeriods": 3 },
  "gameOutcome": { "lastPeriodType": "REG" },
  "goals": [
    {
      "period": 1,
      "timeInPeriod": "13:19",
      "playerId": 8482877,
      "name": { "default": "J. Chmelar" },
      "teamAbbrev": "NYR",
      "awayScore": 0,
      "homeScore": 1,
      "strength": "ev",
      "assists": [
        { "playerId": 8478882, "name": { "default": "V. Gavrikov" }, "assistsToDate": 19 }
      ]
    }
  ]
}
```

### 3. `standings/now` — одна строка (`standings[]`)

Много числовых метрик (очки, голы, дом/гость, L10, …). Пример начала объекта:

```json
{
  "conferenceAbbrev": "W",
  "conferenceName": "Western",
  "divisionAbbrev": "C",
  "divisionName": "Central",
  "seasonId": 20252026,
  "gameTypeId": 2,
  "teamAbbrev": { "default": "COL" },
  "teamName": { "default": "Colorado Avalanche", "fr": "Avalanche du Colorado" },
  "gamesPlayed": 74,
  "wins": 49,
  "losses": 15,
  "otLosses": 10,
  "points": 108,
  "goalDifferential": 90,
  "streakCode": "L",
  "streakCount": 1
}
```

### 4. `roster/{TEAM}/{SEASON}` — нападающий

```json
{
  "id": 8478569,
  "headshot": "https://assets.nhle.com/mugs/nhl/20252026/PIT/8478569.png",
  "firstName": { "default": "Noel" },
  "lastName": { "default": "Acciari" },
  "sweaterNumber": 55,
  "positionCode": "C",
  "shootsCatches": "R",
  "birthDate": "1991-12-01",
  "birthCountry": "USA"
}
```

### 5. `player/{PLAYER_ID}/landing` — верхний уровень

Ключи (часть):
`playerId`, `isActive`, `currentTeamAbbrev`, `firstName`, `lastName`, `position`, `featuredStats`, `careerTotals`, `last5Games`, `seasonTotals`, …

### 6. `gamecenter/{GAME_ID}/boxscore` — фрагмент

```json
{
  "id": 2025021173,
  "season": 20252026,
  "gameType": 2,
  "gameDate": "2026-03-30",
  "gameState": "OFF",
  "awayTeam": {
    "id": 5,
    "abbrev": "PIT",
    "score": 8,
    "sog": 32,
    "commonName": { "default": "Penguins" }
  },
  "homeTeam": {
    "id": 2,
    "abbrev": "NYI",
    "score": 3,
    "sog": 26
  }
}
```

Полный ответ также содержит **`playerByGameStats`** (статы по игрокам за матч).

### 7. `gamecenter/{GAME_ID}/play-by-play` — одно событие

Массив `plays[]` большой; элемент — тип события, период, время, коды ситуации и т.д.:

```json
{
  "eventId": 52,
  "periodDescriptor": { "number": 1, "periodType": "REG", "maxRegulationPeriods": 3 },
  "timeInPeriod": "00:00",
  "timeRemaining": "20:00",
  "situationCode": "1551",
  "homeTeamDefendingSide": "left",
  "typeCode": 520,
  "typeDescKey": "period-start",
  "sortOrder": 8
}
```

### 8. `club-stats-season/{TEAM}` — элемент списка

```json
{ "season": 20252026, "gameTypes": [2] }
```

(На практике список длинный — по одному объекту на сезон/контекст.)

### 9. `standings-season` (корень)

```json
{
  "currentDate": "2026-04-04",
  "seasons": [
    {
      "id": 19171918,
      "standingsStart": "1917-12-19",
      "standingsEnd": "1918-03-06",
      "tiesInUse": true,
      "wildcardInUse": false
    }
  ]
}
```

---

## Практические заметки для сборки `source`

1. **Дедупликация:** один и тот же матч может попасть в выборку из разных вызовов `schedule/{date}` (недельное окно). Ключ — **`id` игры**.
2. **Минимальный пайплайн «матч + счёт»:** `schedule/...` или `score/now` → при необходимости детализации один вызов **`gamecenter/{id}/boxscore`**.
3. **Голы/события без тяжёлого PBP:** в **`score/now`** (и иногда в других ответах) уже есть массив **`goals`** с ассистами и счётом на момент гола.
4. **Игроко-центричные фичи:** цепочка `roster` → `player/{id}/landing` → при необходимости сезонная статистика из вложенных блоков лендинга.
5. **Отдельный Stats REST:** в сообществе упоминают `api.nhle.com/stats/rest` для табличной статистики; в **этом** файле не проверялось.

---

## Ссылки

- [dword4/nhlapi (GitHub, архив)](https://github.com/dword4/nhlapi)
- [dword4/nhlapi (GitLab, new-api.md)](https://gitlab.com/dword4/nhlapi/-/blob/master/new-api.md)
