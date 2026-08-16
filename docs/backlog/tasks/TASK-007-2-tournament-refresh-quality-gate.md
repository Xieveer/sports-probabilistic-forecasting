# TASK-007-2 — Tournament refresh и quality gate

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-007](../EPIC-007-autonomous-production-data-runtime.md)
> **Требование:** [REQ-007](../../product/requirements/REQ-007-production-data-runtime.md)
> **ADR:** [ADR-007](../../architecture/adr/ADR-007-autonomous-production-data-runtime.md)

## Результат и границы

Ввести tournament profile с cadence, максимальной длительностью матча и provider
grace period, а также gate, который требует финальные результаты всех ранее
спрогнозированных матчей с истёкшим deadline. Не реализовывать generic
high-frequency scheduler или stateful EWM.

## Критерии приёмки

- [x] Deadline выводится только из конфигурации tournament profile и времени
  матча; future/ещё не истёкшие матчи не блокируют run.
- [x] Отсутствующий, противоречивый или невалидный финальный результат делает
  run failed до feature/inference publish и создаёт безопасный admin signal.
- [x] Перезапуск имеет per-tournament idempotent run ID и DB lock; timeout/retry
  contract и не дублирует alert/outbox.

## План реализации

1. Добавить failing tests для deadline, missing result, duplicate run и late
   correction.
2. Реализовать configuration model, watermark/quality evaluation и failure
   state без payload/secrets.
3. Связать gate с refresh runner, не меняя пока full-history feature engine.

## Проверка

Unit tests profile/gate, PostgreSQL integration tests lifecycle и negative paths.

## Handoff и отчёт

Отчёт: [TASK-007-2](../../changes/done/TASK-007-2-tournament-refresh-quality-gate.md).
