# TASK-030-1 — Закреплённый NHL universe для финансового исследования

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-030](../EPIC-030-financial-research-validation.md)
> **Требование:** [REQ-030](../../product/requirements/REQ-030-financial-research-validation.md) (`confirmed`)
> **Решение:** [ADR-032](../../architecture/adr/ADR-032-reproducible-financial-research-evaluation.md) (`accepted`)
> **Протокол:** [NHL protocol](../../research/epic-030-nhl-protocol.md)

## Результат и границы

Получить локальный expected universe NHL для исследовательского окна
`[2023-10-01, 2026-05-01)` UTC из спортивного источника, закрепить его в
проверяемом `ir1` snapshot и вывести отчёт строгого сопоставления с source
events исторических odds. В expected universe входят только `regular` и
`playoffs`, как в существующем NHL model preprocessing. Все прочие строки
окна (включая `preseason`) учитываются отдельно как `excluded_non_model_game_type`;
это фильтр до odds и не часть betting coverage. Universe строится независимо
от наличия линии, прогнозов и итогов ставок. Использовать существующий
`EntityRegistry`, NHL team seed, snapshot exporter и batch resolver; не создавать
второй registry или fuzzy matcher.

Вход — локальный `raw/nhl/matches.parquet` с fingerprint из
[аудита](../../research/epic-030-data-audit.md). Для идентичности читать только
`id`, `nhl_id`, `datetime`, `home_team`, `away_team`, `game_type` и необходимые
source поля. `game_type` задаёт включение в NHL model universe; игровые исходы
и статистики не читаются.
БД и snapshot создавать в отдельном локальном research каталоге, не менять
production/current pointer и исходные parquet/cache. Выходной manifest
сохраняет fingerprint входа, версию политики, окно, `ir1`, счётчики и причины
неразрешённых/конфликтных строк. Полные внешние ответы в Git не добавлять.

Эта TASK не оценивает признаки, цены, вероятность, ставки или ROI. Эти шаги
следуют отдельно после закрепления universe.

## Критерии приёмки

1. Повторный запуск на том же локальном registry и входе не создаёт новые
   event ID, relations, designations или иной snapshot. Изменение входного
   fingerprint/окна/seed не принимается как прежний pinned universe.
2. Проверенные tournament/team designation из NHL seed и точный UTC kickoff
   дают событию один project UUID и подтверждённый NHL source key. Дубликат
   `nhl_id`, две спортивные записи на один идентичный матч, неизвестная
   команда, отсутствие времени или противоречие с прежним решением дают
   явную диагностику и не подтверждаются автоматически.
3. Raw строки окна regular/playoffs составляют expected universe; число
   preseason/прочих `game_type` отдельно показано как pre-model exclusions.
   `RegistryEventResolver.resolve_many` проверяет bookmaker source
   refs с reverse uniqueness. Только однозначно разрешённые source IDs
   сохраняются как confirmed The Odds API event designations до финального
   `ir1` export; они доступны существующему historical coverage resolver.
   `resolved`, `unresolved`, `ambiguous`, `conflict` считаются раздельно, и
   каждый подтверждённый odds source ID указывает максимум на один project event.
4. `ir1` экспортируется и повторно проверяется; отчёт содержит ID snapshot,
   fingerprint входа, числа событий по годам/месяцам, причины исключений и
   provenance правил. Исходы матчей не читаются и не попадают в отчёт.
5. На текущих локальных входах запускается реальный offline smoke. Он
   показывает фактический resolved universe и причину расхождения с
   предварительными 3294 точными совпадениями; это число не является порогом
   приёмки. Проверка не изменяет основной checkout или current registry.

## Фактический результат

- Адресный red был зафиксирован: новый focused test завершился ошибкой импорта
  отсутствующего `sports_forecast.research.nhl_universe`.
- После реализации focused и смежные identity/historical tests: 59 passed.
  `ruff check` и `git diff --check` завершились успешно.
- Offline smoke на локальных входах завершился за ~94 секунды. Команда,
  manifest и SQLite находятся в `/tmp/epic-030-nhl-universe-final/`;
  fingerprint NHL parquet: `sha256:b6eaed0092a8d7dad4d6fd070b0f71d64493003b4fc6d7c55095a01dd7bb8fb3`,
  run ID `13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5`,
  snapshot `65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498`.
- В исходном временном окне 4450 строк; 300 строк исключены до model universe
  по `game_type` (259 preseason и 41 прочая), expected universe — 4150 regular/
  playoffs. NHL mapping разрешил 4150, unresolved — 0. Для исторических source
  events: 2788 resolved, 755 unresolved, 610 conflict, 0 ambiguous. Это
  счётчики всех импортированных source event IDs в окне, не только событий с
  Pinnacle h2h. Подтверждённые source designations записаны до `ir1` export.
- Предварительные 3294 — кандидатные точные совпадения в отдельном Pinnacle
  h2h срезе, а smoke использует полный импортированный historical source
  universe; сравнивать эти значения как одинаковый denominator нельзя.
  Фильтрация и строгая reverse uniqueness также оставляют конфликтные события
  без подтверждения.
- Smoke использовал только `/tmp`; основной registry и исходные данные не
  менялись. Следующая роль — независимый Reviewer. Dataset и evaluator в этот
  TASK не входят.

### Уточнения после review

- До сохранения любого resolved odds source ID сверяется UTC kickoff project
  relation. Уже закреплённый source ID с новым kickoff классифицируется как
  `conflict` и не попадает в список новых confirmed decisions; общая логика
  `RegistryEventResolver` не менялась.
- CLI проверяет registry location до `EntityRegistry.initialize()`. Пути под
  `data/registry` и `data/entity-registry*` в корне проекта запрещены; отдельные
  `/tmp` и worktree research каталоги остаются допустимыми.
- Входную historical SQLite читаем через read-only connection: импортированные
  event facts и fingerprints всех строк `historical_cache_files`, включая
  пустые cache imports. На локальной smoke БД это те же 1609 файлов и прежний
  fingerprint; частичная БД на ошибке остаётся побайтно неизменной.
- Регрессионные tests на сдвинутый kickoff, protected CLI registry, пустые
  historical imports и read-only ошибочный input добавлены; промежуточная
  focused проверка после этих исправлений: 63 passed.
- Дополнительная CLI проверка отклоняет registry database, совпадающую с
  historical input по пути, symlink или hardlink, до инициализации. Источник
  остаётся побайтно прежним; focused набор после этого исправления: 66 passed.

## Red → green → refactor

1. Synthetic fixture: два NHL матча с подтверждёнными алиасами, один odds
   source event, матч без линии; повтор запуска и новый проверенный `ir1`.
2. Negative fixtures: дубли NHL ID, повторный матч тех же команд, смещение
   UTC kickoff, неизвестная команда, отсутствующее время, конфликт bookmaker
   source IDs, изменение fingerprint. Диагностика не должна создавать связь.
3. Реализовать минимальный offline entrypoint и локальные структуры отчёта;
   использовать `pathlib.Path` и существующий logger. Исследовательская БД,
   snapshots и отчёты создаются внутри отдельного output каталога. Машинное
   основание `confirmed` source designation содержит версию политики и
   объяснение точного UTC/team/reverse uniqueness правила. После green выполнить
   refactor только затронутой области.
4. Прогнать адресные identity/historical tests и реальный smoke; записать
   фактические команды и счётчики в
   [done](../../changes/done/TASK-030-1-pinned-nhl-universe.md).

## Handoff

Developer передаёт Product Owner `ir1` ID, местоположение локального evidence,
счётчики и отчёт `done`; затем независимый Reviewer проверяет связь с
REQ-030/ADR-032, корректность матчинга и отсутствие утечки исходов. После
review следующая TASK строит historical provider-as-of dataset с per-event T.
