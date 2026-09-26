# TASK-025-3 — Durable Data Cycle runs и failed acquisition

> **Статус:** done — локальный срез, runtime gate остаётся в EPIC
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

Runner создаёт durable run со всеми фиксированными stage rows до вызова NHL
source. Source failure завершает календарную стадию, Data Cycle и coverage
attempt; API показывает состояние недоступности и времена последней попытки и
последнего успеха раздельно. Успешный canonical import запускает и закрывает
calendar, quality, predictions, publication и archive stages. Legacy odds
acquisition явно остаётся `partial_success`, пока future canonical odds path
не добавлен в [TASK-025-6](TASK-025-6-future-odds.md).

## Критерии приёмки этого TASK

- [x] Durable run и фиксированные stage results создаются до внешнего NHL
  acquisition; DB constraint допускает не более одного active run на турнир.
  PostgreSQL race проверяется в TASK-025-7.
- [x] Runner записывает статусы, timestamps, безопасные failure codes и
  неотрицательные счётчики стадий; stages, которые не запускались, получают
  явный `skipped`.
- [x] Ошибка NHL acquisition, в том числе malformed weekly anchor, завершает
  run до Worker. Failed attempt сохраняется в calendar coverage, предыдущее
  окно и `last_successful_at` остаются, а Calendar API возвращает `unavailable`
  и `checked_at` попытки отдельно от последнего успеха.
- [x] Успешный canonical import закрывает calendar stage; quality failure
  закрывает quality stage и оставляет publication закрытым; predictions,
  publication и archive stage отражают фактические outcomes.
- [x] До TASK-025-6 odds stage не объявляет независимую готовность линий на
  основании legacy refresh и делает Data Cycle итог как минимум
  `partial_success`.

Timeout/crash recovery, полный summary/history API, all-stage fault matrix,
executor ownership/fencing и PostgreSQL concurrency tests вынесены в
[TASK-025-7](TASK-025-7-data-cycle-recovery-summary.md).

## Реализация и проверки

1. Red: unit/integration checks для duplicate active run, безопасных stage
   transitions и failed calendar attempt на фоне старого успешного coverage.
2. Green: additive migration и runtime grants; lifecycle CLI вокруг
   `run-canonical-refresh.sh`; Calendar API хранит отдельные часы попытки и
   успеха.
3. Refactor: один набор allowlisted stage/failure names; production runner
   contract и migration checks.

## Затрагиваемые области

- `DataCycleRun`, `DataCycleStageResult`, `CalendarCoverage` и lifecycle
  repository/CLI.
- `run-canonical-refresh.sh`, canonical full refresh stage transitions,
  migration `0012` и grants `sf_refresh_writer`.
- Calendar coverage response, migration/runner/lifecycle tests и operating
  notes. Не затрагивает scheduler control API или Telegram UX.

## Handoff

- [Отчёт и проверки](../../changes/done/TASK-025-3-data-cycle-runs.md):
  независимый повторный Reviewer не нашёл блокирующих findings; 30 целевых
  тестов, синтаксис shell и diff-check прошли.
- Проверка реального shell/Compose runtime и production timer остаётся
  release gate Operations Agent; source config и runbook не подтверждают, что
  установленный VPS timer активен.
- TASK-025-6/7 остаются отдельными незавершёнными release зависимостями.
