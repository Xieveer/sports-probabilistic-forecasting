# TASK-027-2 — Покрытие истории и итоговая проверка Pinnacle

> **Статус:** done, ожидает финальный независимый review
> **Владелец:** Developer
> **Эпик:** [EPIC-027](../EPIC-027-historical-odds.md)
> **Требование:** [REQ-027](../../product/requirements/REQ-027-historical-odds.md) (`confirmed`)
> **ADR:** [ADR-031](../../architecture/adr/ADR-031-historical-odds.md) (`accepted`)
> **Зависимость:** [TASK-027-1](TASK-027-1-local-historical-odds.md), реализация и независимое review

## Результат и границы

Поверх готового immutable importer и pinned query добавить локальный отчёт
покрытия, диагностику отсутствий и завершить реальные критерии приёмки REQ-027.
Этот срез закрывает критерии 5–6 и проверяет полный сценарий критериев 1–6.

Область Developer: новые odds coverage/report модули и локальный CLI, focused
и regression tests, описание источника/usage, TASK/done. Общие service DB,
Alembic, prediction revisions и production runtime не меняются. При выявленном
противоречии observation/query contract вернуть решение Product Owner.

## Критерии приёмки

- [x] Expected universe берётся из pinned registry по UTC kickoff `[from, to)`;
  report фиксирует T либо явные T событий, bookmaker, market, ir1 и fingerprint
  импортированного набора. Знаменатель включает события, отсутствующие в cache.
- [x] Взаимоисключающие категории no_line/no_snapshot/mapping_error/covered
  следуют ADR-031; subreasons различают отсутствие source evidence, неподходящий
  timestamp и invalid data. Непривязанные source events идут отдельным счётчиком.
- [x] Отчёт показывает числитель/знаменатель, import failures, конфликты,
  unknown retrieval и late retrieval; нулевое покрытие честно отражается без
  порога и без current odds fallback. Нет двойного счёта outcomes/файлов.
- [x] Полный локальный реальный цикл import → query → coverage выполнен на
  выбранном окне. Два изменившихся snapshots одного confirmed события дают
  правильные before/between/after ответы; контрольное отсутствие линии видно
  отдельной причиной. При отсутствии подходящего реального контроля явно
  зафиксировать блокер, не выдавать synthetic fixture за реальный evidence.
- [x] Реальный повтор импорта идемпотентен; legacy retrieval остаётся неизвестным;
  итоговые evidence содержат IDs/digests/времена/счётчики без full responses.
- [x] Старые close/T−15 и current odds остаются читаемы; пройдены применимые
  store/backfill/client/current odds и identity regressions, входные данные
  не изменены. Локальный report не требует API key и сети.

## Red → green → refactor

1. Red: fixtures expected universe и источников с covered/no_line/no_snapshot,
   unknown market/mapping, конфликтом и полностью пустым покрытием; сверка суммы
   категорий и отдельного счётчика unmapped source events.
2. Green: aggregation и report CLI поверх TASK-027-1; сохранить один query
   contract и один способ pinned resolution, не дублировать правила отбора.
3. Провести реальный acceptance и минимально достаточные regressions; refactor
   только внутри затронутых модулей. Если mapping отсутствует, использовать
   существующий процесс registry и документировать блокер до его решения.
4. Обновить usage и статусы, создать
   `docs/changes/done/TASK-027-2-historical-odds-coverage.md` с командами red/green,
   фактическим покрытием, параметрами evidence и остаточными ограничениями.

## Проверка и handoff

Focused coverage tests, odds store/backfill/client/current odds и identity
regressions по diff, lint изменённых Python. Сопоставить каждый критерий REQ
с evidence первой и второй TASK; не повторять тесты без конкретного риска.

Developer → Product Owner → независимый Reviewer; findings исправляются до
итогового review инициативы. Затем каноническая документация, финальные проверки,
PR и terminal CI. Production release не запрошен; зелёные synthetic tests
не закрывают отсутствующий реальный acceptance.

## Текущий ход реализации

2026-10-10: добавлены отчёт coverage и команда `historical_cli coverage` поверх
существующего `ho1`/`ir1` контракта. Synthetic tests подтверждают expected
universe, `covered`, `no_line`, `no_snapshot`, `mapping_error`, unmapped source
events, import diagnostics, timestamp conflicts, нулевое покрытие и отбор по T.
Регрессии old store/backfill/client и identity зелёные.

Реальный acceptance выполнен на подтверждённом CAR–BUF и контрольном ANA–STL.
Владелец подтвердил второй bridge `2023020271` ↔
`c4e420f552d6ffa6f1a1e5dec5a0db3e`; изолированный pinned snapshot вне Git:
`ir1:7f6ee9a8004c00dde23e42017de491f44dbccf6150a75ec9ca01d65773e7c9c9`.
Coverage окна `[2023-11-07T00:00:00Z, 2023-11-21T00:00:00Z)` при
`T=2023-11-19T13:00:00Z`: 2 expected, 1 covered (CAR–BUF), 1 `no_line`
(ANA–STL, `no_pinnacle`), 0 `no_snapshot`, 0 `mapping_error`; 6 imported files,
0 import diagnostics/conflicts/late retrieval, 6 unknown retrieval, 32 unmapped
source IDs (`30 mismatch`, `2 missing`). Fingerprint:
`sha256:20e0ff034f6a5c095d8910df1979acce11bada3ae8202534d70f88743956a962`.

В повторном импорте всех шести cache files каждый вызов вставил 0 observations.
Для CAR–BUF queries before/between/after дали null, ранний и поздний snapshot;
retrieval неизвестен, `locally_known_at_t=false`. SHA-256 исходных шести файлов
совпали до и после импорта. В Git не добавлялись cache responses, registry,
SQLite или локальные evidence artifacts.
