# NHL Web API — проверяемый каталог

> **Источник:** `https://api-web.nhle.com/v1` · **карточка:**
> [`catalogs/nhl-web-api.json`](catalogs/nhl-web-api.json) · **проверено:** 2026-08-25
> · **статус:** complete для публично наблюдаемого surface, описанного ниже.

## Граница доказательства и доступ

Это не опубликованный NHL OpenAPI-контракт. Каталог ограничен путями из публичного
read-only наблюдения и [общественного перечня new-api.md][new-api]; он не утверждает,
что других путей на хосте нет. В частности, `api.nhle.com/stats/rest` — другой host и
не входит в этот source. Полные ответы, cookies, HAR и персональные данные не сохранялись.

## Граница complete-card

`catalog_scope.observed_endpoint_ids` содержит все 18 endpoint patterns из таблицы ниже;
`unobserved_endpoint_ids` пуст, поскольку ни один из внесённых путей не был записан как
`unobserved` или `denied`. Полнота означает все scalar leafs конкретных read-only samples
этих путей на 2026-08-25, а не все object/array nodes, сезоны, game states, будущую схему
или неизвестный/закрытый surface хоста.

Все ниже — `GET`, JSON, без query-параметров и без аутентификации. На 2026-08-25 пути
с `now` ответили `307` на календарный путь; конкретные date/season paths ответили `200`.
Без обычного `User-Agent` предыдущая локальная проверка фиксировала `403`; это условие
доступа, а не разрешение обходить защиту. Публично не объявлены ни квота, ни rate limit:
использовать один последовательный запрос, exponential backoff на 429/5xx и не делать
массовый scrape без отдельного разрешения. `now` в межсезонье может вести в будущую дату
или вернуть пустой `games`; это не означает отсутствие исторических данных.

Evidence в JSON-card — объект `{reference, as_of, evidence_level}`: `observed GET/status`
означает read-only проверку пути, а `observed JSON path/type` — нормализованный перечень
путей и типов; оба выполнены 2026-08-25. `E2`: [new-api.md][new-api], прочитан 2026-08-25.
`units` и `domain` каждой JSON-записи обязательны: для идентификаторов/строк единица
«неприменимо», а domain ограничен наблюдаемым JSON и не является полной спецификацией NHL.
Nullable означает
«ключ/значение может отсутствовать в наблюдаемом варианте матча», а не гарантию NHL.
`L10` — итоговые/текущие показатели, не допустимые как pre-match feature без сохранённого
снимка строго до `startTimeUTC`.

## Методы, параметры и сущности

| ID | Путь | Обязательные path-параметры | Корень | Назначение / pagination |
|---|---|---|---|---|
| `schedule-date` | `/schedule/{date}` | `date`: ISO `YYYY-MM-DD` | object, `gameWeek[]` | Недельное окно лиги; cursor нет, соседние окна пересекаются — dedupe по `game.id`. |
| `schedule-now` | `/schedule/now` | — | redirect → `schedule-date` | Указатель на текущую неделю. |
| `score-date` | `/score/{date}` | `date`: ISO date | object, `games[]` | Scoreboard календарного дня; pagination нет. |
| `score-now` | `/score/now` | — | redirect → `score-date` | Указатель на текущий scoreboard. |
| `club-season` | `/club-schedule-season/{team}/{season}` | `team`: NHL abbreviation; `season`: 8 цифр | object, `games[]` | Полный календарь клуба за сезон; pagination нет. |
| `club-season-now` | `/club-schedule-season/{team}/now` | `team` | redirect → `club-season` | Указатель на текущий сезон. |
| `club-week` | `/club-schedule/{team}/week/{date|now}` | `team`, anchor date либо `now` | object, `games[]` | Недельное окно клуба; пересекается. |
| `club-month` | `/club-schedule/{team}/month/{YYYY-MM|now}` | `team`, месяц либо `now` | object, `games[]` | Месячное окно клуба; пересекается. |
| `standings-date` | `/standings/{date}` | `date`: ISO date | object, `standings[]` | Снимок таблицы после календарного дня; pagination нет. |
| `standings-now` | `/standings/now` | — | redirect → `standings-date` | Текущий снимок. |
| `standings-season` | `/standings-season` | — | object, `seasons[]` | Метаданные исторических сезонов, не standings. |
| `club-stats-season` | `/club-stats-season/{team}` | `team` | array | Доступные пары season/gameType; pagination нет. |
| `club-stats` | `/club-stats/{team}/{season}/{gameType}` | `team`, `season`, `gameType` | object | Кумулятивные season stats игроков; pagination нет. |
| `roster` | `/roster/{team}/{season}` | `team`, `season` | object | Сезонный roster: forwards/defensemen/goalies; pagination нет. |
| `roster-season` | `/roster-season/{team}` | `team` | array of season ids | Доступные roster seasons. |
| `player-landing` | `/player/{playerId}/landing` | integer `playerId` | object | Био и career/season/player aggregates; pagination нет. |
| `boxscore` | `/gamecenter/{gameId}/boxscore` | integer `gameId` | object | Итог/живой boxscore матча; pagination нет. |
| `play-by-play` | `/gamecenter/{gameId}/play-by-play` | integer `gameId` | object, `plays[]` | События и roster spots матча; pagination нет. |

Параметры не принимают доказанных query-полей. `gameId` — natural primary key матча;
`playerId` и numeric team `id` — foreign keys к игроку/команде; `team.abbrev` — natural
team key; `season` / `seasonId` — season key. Из локальной проверки: `/standings-season/{season}`
давал `404` (снимок 2026-04-04), поэтому в каталог не включён.

## Field dictionary

Нотация `[].x` — поле каждой записи массива; `localized` — JSON object с языковыми
ключами (`default` гарантирован только наблюдением, дополнительные локали опциональны).
Во всех таблицах ключи и идентичности относятся к строке/объекту, а не к отображаемому
локализованному имени. Поля `URL`, `logo`, broadcast, recap, hotel/airline/ticket и
локализованные display names — metadata: они не образуют спортивную feature без отдельной
гипотезы и временной проверки.

### Расписание и scoreboard (`schedule-*`, `club-*`, `score-*`)

| JSON path (type; nullable) | Смысл / применение | Время и leakage |
|---|---|---|
| `gameWeek[].date`, `dayAbbrev`, `numberOfGames` (string, string, integer; нет) | календарный день и число игр в недельном окне | pre_event; E1 |
| `games[].id`, `season`, `gameType`, `gameDate`, `startTimeUTC` (integer, integer, integer, date, datetime; нет) | ключ матча, сезон/тип, календарная и точная UTC дата | pre_event для published schedule; переносы требуют snapshot timestamp |
| `games[].gameState`, `gameScheduleState`, `period`, `periodDescriptor.{number,periodType,maxRegulationPeriods}` (string/integer/object; да) | состояние и текущий период | live; не feature до матча |
| `games[].venue.localized`, `venueTimezone`, `venueUTCOffset`, `easternUTCOffset`, `neutralSite` (localized/string/boolean; да) | площадка и часовые пояса/neutral-site | pre_event_if_timestamp_checked: возможны переносы |
| `games[].awayTeam.{id,abbrev,score,sog}` и `homeTeam.{id,abbrev,score,sog}` (integer/string/integer/integer; score/sog да) | стороны, team keys и текущий/итоговый счёт/SOG | id/abbrev pre_event; score/sog live/post_event — leakage |
| `games[].{away,home}Team.{commonName,placeName,placeNameWithPreposition}.localized`, `{logo,darkLogo}` (localized/string; да) | display metadata команды | metadata; не sporting feature |
| `games[].tvBroadcasts[].{id,market,countryCode,network,sequenceNumber}` (integer/string; да) | broadcast record | pre_event_if_timestamp_checked; metadata |
| `games[].gameOutcome.{lastPeriodType,otPeriods}` (string/integer; да) | тип последнего периода / число OT | post_event, target/label only |
| `games[].winningGoalie.{playerId,firstInitial.localized,lastName.localized}`, `winningGoalScorer.{playerId,firstInitial.localized,lastName.localized}` (integer/localized; да) | игроки итогового результата | post_event; leakage |
| `games[].goals[].{playerId,teamAbbrev,period,timeInPeriod,strength,awayScore,homeScore,goalsToDate,goalInGame,goalModifier}` (integer/string; да) | гол и счёт в момент гола | live/post_event; event label, не pre-match feature |
| `games[].goals[].assists[].{playerId,assistsToDate,name.localized}` (integer/localized; да) | ассистент и накопленные assists на событие | live/post_event; leakage |
| `games[].goals[].periodDescriptor.{number,periodType,maxRegulationPeriods}`; `firstName.localized`, `lastName.localized`, `name.localized`, `{mugshot,highlightClip*,discreteClip*}` (object/string/URL; да) | display/event media и период | post-event/media metadata |
| `games[].{gameCenterLink,condensedGame,condensedGameFr,threeMinRecap,threeMinRecapFr}` (URL string; да) | links/recap | metadata; recap post-event |
| root `previous/next{Date,StartDate,Month}`, `currentDate`, `currentMonth`, `calendarUrl`, `clubTimezone`, `clubUTCOffset`, season bounds, `numberOfGames`, `oddsPartners[]` (string/integer/object; да) | навигация, календарь, sponsor metadata | metadata; не odds quote и не betting feature |
| `games[].seriesStatus.{bottomSeedWins,topSeedWins,gameNumberOfSeries,neededToWin,round,seriesAbbrev,seriesLetter,seriesTitle}`, `seriesUrl`, `specialEvent.{parentId,name.localized,lightLogoUrl.localized}` (integer/string; да) | playoff series / special event metadata | series score live/post-event; остальное pre_event_if_timestamp_checked |

`schedule-date` и club schedules используют общий shape games; `score-date` добавляет
`goals[]`, `clock` и в наблюдении `oddsPartners[]`. Не считать `oddsPartners` линией:
там только партнёры сайта, числовых котировок нет.

### Статус классификации полного leaf inventory

На 2026-08-25 JSON-card содержит 1 105 отдельных leaf records: 649 помечены
`pre_event_if_timestamp_checked`, 280 — `post_event`, 176 — `unknown`. По назначению:
300 `feature` (только при temporal snapshot), 280 `label`, 525 `metadata`.
`unknown` сохранён, когда один путь/тип не доказывает момент публикации либо предметную
семантику (прежде всего UI/media/localized поля); его нельзя неявно превращать в feature.
Для чисел, процентов, координат и времени units/domain классифицированы только по
наблюдаемому representation; незафиксированная NHL шкала прямо отмечается как unknown.

### Таблица (`standings-*`, `standings-season`)

| JSON path (type; nullable) | Смысл / применение | Время и leakage |
|---|---|---|
| `standings[].{seasonId,gameTypeId,date}` (integer/integer/date; нет) | ключ контекста standings | snapshot after date; для матча на date брать prior-day snapshot, но intra-day не разрешён |
| `standings[].teamAbbrev.default`, `team{Name,CommonName}.localized`, `placeName.localized`, `teamLogo`, `teamLogoDark` (string; display да) | team natural key и display metadata | teamAbbrev metadata/pre-event; другие display |
| `standings[].{conference,division}{Abbrev,Name}`; `conferenceSequence`, `divisionSequence`, `wildcardSequence`, `leagueSequence`, `waiversSequence` (string/integer; да) | affiliation и ранги | cumulative snapshot; pre_event только historical snapshot |
| `standings[].{gamesPlayed,wins,losses,otLosses,ties,points,pointPctg,winPctg}` (integer/number; да) | aggregate record и points | cumulative; timestamped snapshot only |
| `standings[].{goalFor,goalAgainst,goalDifferential,goalDifferentialPctg,goalsForPctg}` (integer/number; да) | aggregate goals | same, leakage without historical snapshot |
| `standings[].{regulationWins,regulationPlusOtWins,regulationWinPctg,regulationPlusOtWinPctg,shootoutWins,shootoutLosses}` (integer/number; да) | win-type aggregates | same |
| `standings[].home*`, `road*`, `l10*` where suffix is `GamesPlayed,Wins,Losses,OtLosses,Ties,Points,GoalsFor,GoalsAgainst,GoalDifferential,RegulationWins,RegulationPlusOtWins` (integer; да) | home/away/last-10 split aggregate | same; `l10` is time-dependent window |
| `standings[].{conference,division,league}{Home,Road,L10}Sequence`, `clinchIndicator`, `streakCode`, `streakCount`, `wildCardIndicator`, `standingsDateTimeUtc` (integer/string/datetime; да) | rank/situation/streak and API snapshot timestamp | snapshot only; timestamp does not prove data was known before a game |
| `seasons[].{id,standingsStart,standingsEnd}` (integer/date; нет); `{tiesInUse,wildcardInUse,conferencesInUse,divisionsInUse,pointForOTlossInUse,rowInUse,regulationWinsInUse}` (boolean; нет) | historical rules/season coverage | metadata; suitable for rule-aware joins |

### Roster, player and season aggregates

| JSON path (type; nullable) | Смысл / применение | Время и leakage |
|---|---|---|
| `roster-season[]` (integer; нет) | доступный `season` для roster | metadata, E1 |
| `forwards[]`, `defensemen[]`, `goalies[]` `.id` (integer; нет observed) | player foreign key; group gives position class | pre_event_if_timestamp_checked: endpoint is mutable roster snapshot |
| same `.firstName.localized`, `.lastName.localized`, `.birthCity.localized`, `.birthStateProvince.localized`, `.birthCountry`, `.birthDate` (localized/string/date; да) | bio/display | bio metadata; birthDate can be feature but verify identity |
| same `.positionCode`, `.shootsCatches`, `.sweaterNumber`, `.heightIn{Inches,Centimeters}`, `.weightIn{Pounds,Kilograms}`, `.headshot` (string/integer/URL; да) | handedness, position, physical attributes and display | pre_event_if_timestamp_checked; seasonal roster is not historical availability proof |
| `club-stats-season[].season`, `club-stats-season[].gameTypes[]` (integer; нет) | discover valid stats contexts | metadata |
| `club-stats.{season,gameType}` (string/integer; нет) | stats context | aggregates current response; use only dated reconstruction |
| `club-stats.skaters[].playerId` (integer; нет observed), `.positionCode` (string; да), `.firstName.localized`, `.lastName.localized`, `.headshot` | player key/display | identity metadata |
| skater numeric `.gamesPlayed,goals,assists,points,plusMinus,penaltyMinutes,shots,shootingPctg,faceoffWinPctg,powerPlayGoals,shorthandedGoals,gameWinningGoals,overtimeGoals,avgShiftsPerGame,avgTimeOnIcePerGame` (integer/number; да) | season cumulative skater stats | snapshot-required; response has no as-of timestamp |
| `club-stats.goalies[].playerId`, names/headshot (integer/localized/URL; да) | goalie identity | metadata |
| goalie numeric `.gamesPlayed,gamesStarted,wins,losses,overtimeLosses,goalsAgainst,goalsAgainstAverage,savePercentage,saves,shotsAgainst,shutouts,timeOnIce,assists,goals,points,penaltyMinutes` (integer/number; да) | season goalie aggregates | snapshot-required; no as-of timestamp |
| `playerId`, `playerSlug`, `isActive`, `currentTeam{Id,Abbrev}`, `position`, `shootsCatches`, `sweaterNumber`, bio/size fields, `draftDetails.{year,round,pickInRound,overallPick,teamAbbrev}` (integer/string/boolean; да) | player identity/bio/draft | current profile is mutable; do not backfill historical roster from it |
| `player-landing.seasonTotals[]`, `featuredStats.{regularSeason,playoffs}.{career,subSeason}`, `careerTotals.{regularSeason,playoffs}` (numbers plus season/team context; да) | career/season aggregate blocks; detailed stat names: `gamesPlayed,goals,assists,points,plusMinus,pim,shots,shootingPctg,avgToi,faceoffWinningPctg,powerPlayGoals,powerPlayPoints,shorthandedGoals,shorthandedPoints,gameWinningGoals,otGoals` | post/current aggregate unless separately versioned; leakage risk high |
| `last5Games[].{gameId,gameDate,gameTypeId,teamAbbrev,opponentAbbrev,homeRoadFlag}` and stats `{goals,assists,points,plusMinus,pim,shots,toi,shifts,powerPlayGoals,shorthandedGoals}` (integer/string/date; да) | last-five game history | individual game records after game; build pre-match rolling feature only by filtering event time |
| `awards[]`, `badges[]`, `currentTeamRoster[]`, media/shop/social/watch links, `inHHOF`, `inTop100AllTime` | display/honor/current roster metadata | post/current or unknown; not model feature absent hypothesis |

### Match result, boxscore и play-by-play

| JSON path (type; nullable) | Смысл / применение | Время и leakage |
|---|---|---|
| shared game header `id,season,gameType,gameDate,startTimeUTC,gameState,gameScheduleState,regPeriods,maxPeriods,otInUse,shootoutInUse,displayPeriod,clock.*` | match identity and live state | identity/scheduled start pre-event; status/clock live |
| shared teams `awayTeam.*`, `homeTeam.*` incl. `id,abbrev,score,sog`, localized names/logo | side identity and result/live score | ids/abbr pre-event; score/sog live/post |
| `playerByGameStats.{awayTeam,homeTeam}.{forwards,defense}[].{playerId,position,sweaterNumber,name.localized}` | player line identity | available only in boxscore, so actual lineup is live/post unless archived pregame snapshot |
| same skater stats `{goals,assists,points,plusMinus,pim,sog,blockedShots,hits,takeaways,giveaways,faceoffWinningPctg,powerPlayGoals,shifts,toi}` | per-game skater output | post-event target/label; leakage for prematch |
| `playerByGameStats.*.goalies[].{playerId,position,sweaterNumber,name.localized,starter,decision}` | goalie identity/start and decision | starter may be live; decision post-event |
| same goalie stats `{toi,shotsAgainst,saves,goalsAgainst,savePctg,saveShotsAgainst,evenStrength*,powerPlay*,shorthanded*,pim}` | per-game goalie result | post-event |
| `plays[].{eventId,sortOrder,typeCode,typeDescKey,timeInPeriod,timeRemaining,situationCode,homeTeamDefendingSide,pptReplayUrl}` | ordered event identity/type/time/situation | live/post; event stream requires timestamped capture for live model |
| `plays[].periodDescriptor.{number,periodType,maxRegulationPeriods}` | period context | live/post |
| `plays[].details.{eventOwnerTeamId,playerId,shootingPlayerId,scoringPlayerId,assist1PlayerId,assist2PlayerId,blockingPlayerId,hittingPlayerId,hitteePlayerId,committedByPlayerId,drawnByPlayerId,winningPlayerId,losingPlayerId,goalieInNetId}` (integer; да) | participants/team foreign keys | live/post; some event types omit fields |
| `plays[].details.{awayScore,homeScore,awaySOG,homeSOG,goalInGame,scoringPlayerTotal,assist1PlayerTotal,assist2PlayerTotal,duration,typeCode,xCoord,yCoord}` (integer/number; да) | score, cumulative stats, penalty duration, event coordinates | live/post; outcomes leakage |
| `plays[].details.{descKey,reason,secondaryReason,shotType,zoneCode}` (string; да) | event taxonomy and shot context | live/post |
| `plays[].details.{highlightClip*,discreteClip*}` (URL/string; да) | replay/media links | post-event metadata |
| `rosterSpots[].{playerId,teamId,positionCode,sweaterNumber,firstName.localized,lastName.localized,headshot}` | match roster participant map | live/post unless independently captured before start |

## Coverage, missingness и scientist handoff

Историческая глубина доказана только там, где endpoint принимает historical `date`/`season`
и отдал ответ: schedule, standings, roster, club schedule, gamecenter и player. Реальная
полнота по сезонам/плей-офф/переносам не измерена; `roster-season` и `standings-season`
дают discovery lists, а не гарантию остальных объектов. Все arrays могут быть пустыми;
event-specific `details` sparse by `typeDescKey`; localized keys, media, series fields,
score/SOG, winning players и player aggregates могут отсутствовать. NHL может тихо
исправлять historical boxscore/PBP: reproducible study должна сохранить разрешённые
derived snapshots с `retrieved_at`, schema version и source id, но не raw response.

Для pre-match: schedule identity/time/place допустимы только из snapshot до kickoff;
таблица и cumulative stats — только в historical snapshot (для standings локальный код уже
знает prior-day boundary, но не внутридневной порядок); roster/current player landing не
доказывают исторический состав. Boxscore/PBP/result/goal fields — targets или labels.

[new-api]: https://gitlab.com/dword4/nhlapi/-/blob/master/new-api.md



## Машино-синхронизированный перечень leaf-полей


Этот раздел механически синхронизирован с `api_fields` карточки на 2026-08-25: один JSON path — одна строка. Семантика, единицы, domain, temporal metadata и evidence являются полями JSON-card; здесь приведён индекс для чтения.

| endpoint_id | json_path | type | units | domain |
|---|---|---|---|---|
| `boxscore `| `awayTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `awayTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `awayTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `awayTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `awayTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `awayTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `awayTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `awayTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `awayTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `awayTeam.sog` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `clock.secondsRemaining` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `clock.timeRemaining` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `easternUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `gameDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `gameOutcome.lastPeriodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `gameScheduleState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `gameState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `gameType` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `homeTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `homeTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `homeTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `homeTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `homeTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `homeTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `homeTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `homeTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `homeTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `homeTeam.sog` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `periodDescriptor.maxRegulationPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `periodDescriptor.number` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `periodDescriptor.periodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].blockedShots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].faceoffWinningPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].giveaways` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].hits` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].position` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].shifts` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].sog` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].takeaways` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.defense.[].toi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].blockedShots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].faceoffWinningPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].giveaways` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].hits` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].name.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].name.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].name.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].name.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].position` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].shifts` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].sog` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].takeaways` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.forwards.[].toi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].decision` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].evenStrengthGoalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].evenStrengthShotsAgainst` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].goalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].name.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].name.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].position` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].powerPlayGoalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].powerPlayShotsAgainst` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].savePctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].saveShotsAgainst` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].saves` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].shorthandedGoalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].shorthandedShotsAgainst` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].shotsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].starter` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.awayTeam.goalies.[].toi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].blockedShots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].faceoffWinningPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].giveaways` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].hits` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].position` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].shifts` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].sog` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].takeaways` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.defense.[].toi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].blockedShots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].faceoffWinningPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].giveaways` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].hits` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].name.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].name.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].name.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].name.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].position` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].shifts` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].sog` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].takeaways` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.forwards.[].toi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].decision` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].evenStrengthGoalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].evenStrengthShotsAgainst` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].goalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].position` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].powerPlayGoalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].powerPlayShotsAgainst` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].savePctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].saveShotsAgainst` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].saves` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].shorthandedGoalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].shorthandedShotsAgainst` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].shotsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].starter` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `playerByGameStats.homeTeam.goalies.[].toi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `regPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `season` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `startTimeUTC` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `tvBroadcasts.[].countryCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `tvBroadcasts.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `tvBroadcasts.[].market` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `tvBroadcasts.[].network` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `tvBroadcasts.[].sequenceNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `boxscore `| `venue.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `venueLocation.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `boxscore `| `venueUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `calendarUrl` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `clubTimezone` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `clubUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `currentMonth` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.airlineDesc` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.airlineLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].awayTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.placeName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].awayTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].condensedGame` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].condensedGameFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].easternUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].gameCenterLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].gameDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].gameOutcome.lastPeriodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].gameScheduleState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].gameState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].gameType` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].homeTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.airlineDesc` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.airlineLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.hotelDesc` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.hotelLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].homeTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.placeName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].homeTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].periodDescriptor.maxRegulationPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].periodDescriptor.number` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].periodDescriptor.periodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].season` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].seriesStatus.bottomSeedWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].seriesStatus.gameNumberOfSeries` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].seriesStatus.neededToWin` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].seriesStatus.round` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].seriesStatus.seriesAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].seriesStatus.seriesLetter` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].seriesStatus.seriesTitle` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].seriesStatus.topSeedWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].seriesUrl` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].startTimeUTC` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].threeMinRecap` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].threeMinRecapFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].tvBroadcasts.[].countryCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].tvBroadcasts.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].tvBroadcasts.[].market` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].tvBroadcasts.[].network` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].tvBroadcasts.[].sequenceNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].venue.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].venueTimezone` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].venueUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalScorer.firstInitial.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalScorer.lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalScorer.lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalScorer.lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalScorer.lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalScorer.playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `games.[].winningGoalie.firstInitial.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalie.lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalie.lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalie.lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalie.lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `games.[].winningGoalie.playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-month `| `nextMonth` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-month `| `previousMonth` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `clubTimezone` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `clubUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `currentSeason` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].awayTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.airlineDesc` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.airlineLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.commonName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.hotelDesc` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.hotelLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].awayTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.placeName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].awayTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].condensedGame` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].condensedGameFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].easternUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].gameCenterLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].gameDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].gameOutcome.lastPeriodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].gameScheduleState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].gameState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].gameType` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].homeTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.airlineDesc` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.airlineLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.commonName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.hotelDesc` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.hotelLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].homeTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.placeName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].homeTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].neutralSite` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `club-season `| `games.[].periodDescriptor.maxRegulationPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].periodDescriptor.number` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].periodDescriptor.periodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].season` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].seriesStatus.bottomSeedWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].seriesStatus.gameNumberOfSeries` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].seriesStatus.neededToWin` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].seriesStatus.round` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].seriesStatus.seriesAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].seriesStatus.seriesLetter` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].seriesStatus.seriesTitle` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].seriesStatus.topSeedWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].seriesUrl` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].specialEvent.lightLogoUrl.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].specialEvent.name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].specialEvent.parentId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].startTimeUTC` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].threeMinRecap` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].threeMinRecapFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].tvBroadcasts.[].countryCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].tvBroadcasts.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].tvBroadcasts.[].market` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].tvBroadcasts.[].network` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].tvBroadcasts.[].sequenceNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].venue.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].venue.es` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].venue.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].venueTimezone` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].venueUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalScorer.firstInitial.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalScorer.lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalScorer.lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalScorer.lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalScorer.lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalScorer.playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `games.[].winningGoalie.firstInitial.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalie.lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalie.lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalie.lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalie.lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-season `| `games.[].winningGoalie.playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `nextSeason` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-season `| `previousSeason` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `gameType` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].firstName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `goalies.[].gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].gamesStarted` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].goalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].goalsAgainstAverage` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].headshot` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `goalies.[].lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `goalies.[].lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `goalies.[].lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `goalies.[].losses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].overtimeLosses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].penaltyMinutes` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].savePercentage` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].saves` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].shotsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].shutouts` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].timeOnIce` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `goalies.[].wins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `season` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].avgShiftsPerGame` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].avgTimeOnIcePerGame` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].faceoffWinPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].firstName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].firstName.de` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].firstName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].firstName.es` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].firstName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].firstName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].firstName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].gameWinningGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].headshot` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].lastName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].overtimeGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].penaltyMinutes` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].positionCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-stats `| `skaters.[].powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].shootingPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].shorthandedGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats `| `skaters.[].shots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats-season `| `[].gameTypes.[]` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-stats-season `| `[].season` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `calendarUrl` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `clubTimezone` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `clubUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.airlineDesc` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.airlineLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].awayTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.placeName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].awayTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].condensedGame` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].condensedGameFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].easternUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].gameCenterLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].gameDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].gameOutcome.lastPeriodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].gameScheduleState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].gameState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].gameType` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].homeTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].homeTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].homeTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].homeTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].homeTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].homeTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].homeTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].homeTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].homeTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].periodDescriptor.maxRegulationPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].periodDescriptor.number` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].periodDescriptor.periodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].season` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].startTimeUTC` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].threeMinRecap` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].threeMinRecapFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].tvBroadcasts.[].countryCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].tvBroadcasts.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].tvBroadcasts.[].market` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].tvBroadcasts.[].network` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].tvBroadcasts.[].sequenceNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].venue.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].venueTimezone` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].venueUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].winningGoalScorer.firstInitial.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].winningGoalScorer.lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].winningGoalScorer.lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].winningGoalScorer.lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].winningGoalScorer.lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].winningGoalScorer.playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `games.[].winningGoalie.firstInitial.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].winningGoalie.lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].winningGoalie.lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].winningGoalie.lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `games.[].winningGoalie.playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `club-week `| `nextStartDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `club-week `| `previousStartDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `awayTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `awayTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `awayTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `awayTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `awayTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `awayTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `awayTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `awayTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `awayTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `awayTeam.sog` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `clock.secondsRemaining` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `clock.timeRemaining` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `displayPeriod` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `easternUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `gameDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `gameOutcome.lastPeriodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `gameScheduleState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `gameState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `gameType` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `homeTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `homeTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `homeTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `homeTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `homeTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `homeTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `homeTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `homeTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `homeTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `homeTeam.sog` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `maxPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `otInUse` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `play-by-play `| `periodDescriptor.maxRegulationPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `periodDescriptor.number` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `periodDescriptor.periodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].details.assist1PlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.assist1PlayerTotal` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.assist2PlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.assist2PlayerTotal` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.awaySOG` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.awayScore` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.blockingPlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.committedByPlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.descKey` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].details.discreteClip` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.discreteClipFr` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.drawnByPlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.duration` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.eventOwnerTeamId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.goalInGame` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.goalieInNetId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.highlightClip` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.highlightClipFr` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.highlightClipSharingUrl` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].details.highlightClipSharingUrlFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].details.hitteePlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.hittingPlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.homeSOG` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.homeScore` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.losingPlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.reason` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].details.scoringPlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.scoringPlayerTotal` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.secondaryReason` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].details.shootingPlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.shotType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].details.typeCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].details.winningPlayerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.xCoord` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.yCoord` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].details.zoneCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].eventId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].homeTeamDefendingSide` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].periodDescriptor.maxRegulationPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].periodDescriptor.number` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].periodDescriptor.periodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].pptReplayUrl` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].situationCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].sortOrder` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].timeInPeriod` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].timeRemaining` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `plays.[].typeCode` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `plays.[].typeDescKey` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `regPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `rosterSpots.[].firstName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].firstName.de` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].firstName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].firstName.es` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].firstName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].firstName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].firstName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].headshot` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].lastName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `rosterSpots.[].positionCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `rosterSpots.[].sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `rosterSpots.[].teamId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `season` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `shootoutInUse` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `play-by-play `| `startTimeUTC` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `tvBroadcasts.[].countryCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `tvBroadcasts.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `tvBroadcasts.[].market` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `tvBroadcasts.[].network` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `tvBroadcasts.[].sequenceNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `play-by-play `| `venue.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `venueLocation.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `play-by-play `| `venueUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `awards.[].seasons.[].assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `awards.[].seasons.[].blockedShots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `awards.[].seasons.[].gameTypeId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `awards.[].seasons.[].gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `awards.[].seasons.[].goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `awards.[].seasons.[].hits` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `awards.[].seasons.[].pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `awards.[].seasons.[].plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `awards.[].seasons.[].points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `awards.[].seasons.[].seasonId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `awards.[].trophy.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `awards.[].trophy.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `badges.[].logoUrl.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `badges.[].title.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `birthCity.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `birthCountry` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `birthDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `birthStateProvince.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `birthStateProvince.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `careerTotals.playoffs.assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.avgToi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `careerTotals.playoffs.faceoffWinningPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.gameWinningGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.otGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.powerPlayPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.shootingPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.shorthandedGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.shorthandedPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.playoffs.shots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.avgToi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `careerTotals.regularSeason.faceoffWinningPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.gameWinningGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.otGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.powerPlayPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.shootingPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.shorthandedGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.shorthandedPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `careerTotals.regularSeason.shots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `currentTeamAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `currentTeamRoster.[].firstName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].firstName.de` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].firstName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].firstName.es` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].firstName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].firstName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].firstName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].lastName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `currentTeamRoster.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `currentTeamRoster.[].playerSlug` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `draftDetails.overallPick` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `draftDetails.pickInRound` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `draftDetails.round` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `draftDetails.teamAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `draftDetails.year` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.gameWinningGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.otGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.powerPlayPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.shootingPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.shorthandedGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.shorthandedPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.career.shots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.gameWinningGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.otGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.powerPlayPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.shootingPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.shorthandedGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.shorthandedPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.playoffs.subSeason.shots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.gameWinningGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.otGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.powerPlayPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.shootingPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.shorthandedGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.shorthandedPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.career.shots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.gameWinningGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.otGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.powerPlayPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.shootingPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.shorthandedGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.shorthandedPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.regularSeason.subSeason.shots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `featuredStats.season` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `firstName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `fullTeamName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `fullTeamName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `headshot` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `heightInCentimeters` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `heightInInches` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `heroImage` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `inHHOF` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `inTop100AllTime` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `isActive` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `player-landing `| `last5Games.[].assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].gameDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `last5Games.[].gameId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].gameTypeId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].homeRoadFlag` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `last5Games.[].opponentAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `last5Games.[].pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].shifts` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].shorthandedGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].shots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `last5Games.[].teamAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `last5Games.[].toi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `playerSlug` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `position` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].assists` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].avgToi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].faceoffWinningPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].gameTypeId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].gameWinningGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].goals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].leagueAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].otGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].pim` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].plusMinus` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].powerPlayGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].powerPlayPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].season` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].sequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].shootingPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].shorthandedGoals` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].shorthandedPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].shots` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `seasonTotals.[].teamCommonName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamCommonName.de` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamCommonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamCommonName.es` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamCommonName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamCommonName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamCommonName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamName.de` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamName.es` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamPlaceNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `seasonTotals.[].teamPlaceNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `shootsCatches` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `shopLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `teamCommonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `teamLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `teamPlaceNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `teamPlaceNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `twitterLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `watchLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `player-landing `| `weightInKilograms` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `player-landing `| `weightInPounds` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `defensemen.[].birthCity.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `defensemen.[].birthCountry` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `defensemen.[].birthDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `defensemen.[].birthStateProvince.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `defensemen.[].firstName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `defensemen.[].headshot` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `defensemen.[].heightInCentimeters` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `defensemen.[].heightInInches` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `defensemen.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `defensemen.[].lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `defensemen.[].positionCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `defensemen.[].shootsCatches` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `defensemen.[].sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `defensemen.[].weightInKilograms` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `defensemen.[].weightInPounds` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `forwards.[].birthCity.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].birthCity.de` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].birthCity.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].birthCity.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].birthCity.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].birthCity.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].birthCity.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].birthCountry` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].birthDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].birthStateProvince.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].firstName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].firstName.de` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].firstName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].firstName.es` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].firstName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].firstName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].firstName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].headshot` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].heightInCentimeters` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `forwards.[].heightInInches` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `forwards.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `forwards.[].lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].lastName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].positionCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].shootsCatches` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `forwards.[].sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `forwards.[].weightInKilograms` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `forwards.[].weightInPounds` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `goalies.[].birthCity.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].birthCity.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].birthCountry` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].birthDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].firstName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].headshot` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].heightInCentimeters` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `goalies.[].heightInInches` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `goalies.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `goalies.[].lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].positionCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].shootsCatches` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `roster `| `goalies.[].sweaterNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `goalies.[].weightInKilograms` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster `| `goalies.[].weightInPounds` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `roster-season `| `[]` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].date` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].dayAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].alternateBroadcasts.[].country` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].alternateBroadcasts.[].descriptions.[].default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].awayTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].awayTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].awayTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].awayTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].awayTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].awayTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].awayTeam.placeName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].awayTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].awayTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].awayTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].condensedGame` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].condensedGameFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].easternUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].gameCenterLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].gameOutcome.lastPeriodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].gameScheduleState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].gameState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].gameType` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.commonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.commonName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.darkLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.placeName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.placeNameWithPreposition.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.placeNameWithPreposition.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].homeTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].periodDescriptor.maxRegulationPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].periodDescriptor.number` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].periodDescriptor.periodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].season` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].startTimeUTC` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].threeMinRecap` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].threeMinRecapFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].tvBroadcasts.[].countryCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].tvBroadcasts.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].tvBroadcasts.[].market` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].tvBroadcasts.[].network` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].tvBroadcasts.[].sequenceNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].venue.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].venue.es` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].venue.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].venueTimezone` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].venueUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalScorer.firstInitial.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalScorer.lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalScorer.lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalScorer.lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalScorer.lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalScorer.playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].games.[].winningGoalie.firstInitial.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalie.lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalie.lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalie.lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalie.lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalie.lastName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `gameWeek.[].games.[].winningGoalie.playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `gameWeek.[].numberOfGames` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `nextStartDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `numberOfGames` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `schedule-date `| `playoffEndDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `preSeasonStartDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `previousStartDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `regularSeasonEndDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `schedule-date `| `regularSeasonStartDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `currentDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `gameWeek.[].date` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `gameWeek.[].dayAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `gameWeek.[].numberOfGames` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].awayTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].awayTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].awayTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].awayTeam.name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].awayTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].awayTeam.sog` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].clock.secondsRemaining` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].clock.timeRemaining` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].condensedGame` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].condensedGameFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].easternUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].gameCenterLink` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].gameDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].gameOutcome.lastPeriodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].gameOutcome.otPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].gameScheduleState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].gameState` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].gameType` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].assists.[].assistsToDate` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].assists.[].name.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].assists.[].name.de` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].assists.[].name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].assists.[].name.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].assists.[].name.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].assists.[].name.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].assists.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].awayScore` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].discreteClip` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].discreteClipFr` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].firstName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].firstName.de` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].firstName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].firstName.es` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].firstName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].firstName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].firstName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].goalInGame` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].goalModifier` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].goalsToDate` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].highlightClip` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].highlightClipFr` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].highlightClipSharingUrl` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].highlightClipSharingUrlFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].homeScore` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].lastName.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].lastName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].lastName.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].lastName.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].lastName.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].mugshot` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].name.cs` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].name.fi` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].name.sk` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].name.sv` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].period` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].periodDescriptor.maxRegulationPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].periodDescriptor.number` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].periodDescriptor.periodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].playerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].goals.[].strength` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].teamAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].goals.[].timeInPeriod` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].homeTeam.abbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].homeTeam.id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].homeTeam.logo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].homeTeam.name.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].homeTeam.name.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].homeTeam.score` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].homeTeam.sog` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].period` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].periodDescriptor.maxRegulationPeriods` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].periodDescriptor.number` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].periodDescriptor.periodType` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].season` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].startTimeUTC` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].threeMinRecap` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].threeMinRecapFr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].tvBroadcasts.[].countryCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].tvBroadcasts.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].tvBroadcasts.[].market` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].tvBroadcasts.[].network` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].tvBroadcasts.[].sequenceNumber` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `games.[].venue.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].venueTimezone` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `games.[].venueUTCOffset` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `nextDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `oddsPartners.[].accentColor` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `oddsPartners.[].bgColor` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `oddsPartners.[].country` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `oddsPartners.[].imageUrl` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `oddsPartners.[].name` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `oddsPartners.[].partnerId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `score-date `| `oddsPartners.[].siteUrl` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `oddsPartners.[].textColor` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `score-date `| `prevDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].clinchIndicator` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].conferenceAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].conferenceHomeSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].conferenceL10Sequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].conferenceName` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].conferenceRoadSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].conferenceSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].date` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].divisionAbbrev` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].divisionHomeSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].divisionL10Sequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].divisionName` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].divisionRoadSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].divisionSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].gameTypeId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].gamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].goalAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].goalDifferential` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].goalDifferentialPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].goalFor` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].goalsForPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homeGamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homeGoalDifferential` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homeGoalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homeGoalsFor` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homeLosses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homeOtLosses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homePoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homeRegulationPlusOtWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homeRegulationWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homeTies` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].homeWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10GamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10GoalDifferential` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10GoalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10GoalsFor` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10Losses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10OtLosses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10Points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10RegulationPlusOtWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10RegulationWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10Ties` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].l10Wins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].leagueHomeSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].leagueL10Sequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].leagueRoadSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].leagueSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].losses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].otLosses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].placeName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].placeName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].pointPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].points` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].regulationPlusOtWinPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].regulationPlusOtWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].regulationWinPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].regulationWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadGamesPlayed` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadGoalDifferential` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadGoalsAgainst` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadGoalsFor` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadLosses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadOtLosses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadPoints` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadRegulationPlusOtWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadRegulationWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadTies` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].roadWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].seasonId` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].shootoutLosses` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].shootoutWins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].streakCode` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].streakCount` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].teamAbbrev.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].teamCommonName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].teamCommonName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].teamLogo` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].teamLogoDark` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].teamName.default` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].teamName.fr` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `standings.[].ties` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].waiversSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].wildcardSequence` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].winPctg` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standings.[].wins` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-date `| `standingsDateTimeUtc` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-date `| `wildCardIndicator` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `standings-season `| `currentDate` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-season `| `seasons.[].conferencesInUse` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `standings-season `| `seasons.[].divisionsInUse` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `standings-season `| `seasons.[].id` | number | неприменимо или не подтверждено | наблюдаемый JSON тип: number |
| `standings-season `| `seasons.[].pointForOTlossInUse` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `standings-season `| `seasons.[].regulationWinsInUse` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `standings-season `| `seasons.[].rowInUse` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `standings-season `| `seasons.[].standingsEnd` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-season `| `seasons.[].standingsStart` | string | неприменимо или не подтверждено | наблюдаемый JSON тип: string |
| `standings-season `| `seasons.[].tiesInUse` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `standings-season `| `seasons.[].wildcardInUse` | boolean | неприменимо или не подтверждено | наблюдаемый JSON тип: boolean |
| `schedule-now `| `gameWeek[].games[].id` | number | неприменимо | наблюдаемый leaf штатно перенаправленного JSON |
| `score-now `| `games[].id` | number | неприменимо | наблюдаемый leaf штатно перенаправленного JSON |
| `club-season-now `| `games[].id` | number | неприменимо | наблюдаемый leaf штатно перенаправленного JSON |
| `standings-now `| `standings[].teamAbbrev.default` | string | неприменимо | наблюдаемый leaf штатно перенаправленного JSON |
