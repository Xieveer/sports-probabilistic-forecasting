# TASK-025-3 — Сквозная история Data Cycle и стадий

> **Статус:** backlog
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

Каждый запуск получает durable `run_id` до обращения к NHL source; этапы
calendar, data/odds, quality, predictions, publication и archive имеют
наблюдаемые результаты. Этот срез закрывает failure-attempt gap TASK-025-1:
ошибка acquisition до canonical refresh видна в состоянии календаря/API и
не маскируется предыдущим успешным покрытием.

## Критерии приёмки

- [ ] `waiting/running/success/partial_success/failed` и результаты стадий
  сохраняются с timestamps, safe reason codes и счётчиками.
- [ ] Ошибка NHL acquisition, включая malformed weekly anchor, фиксируется
  до Worker; API перестаёт утверждать подтверждённую актуальность старого
  coverage после failed попытки и показывает время последнего успеха отдельно.
- [ ] Quality failure запрещает publication, но не удаляет уже сохранённый
  календарь. Ошибки отдельных optional событий допускают partial_success.
- [ ] Сбой/timeout executor не оставляет вечный running и не разрешает
  параллельный запуск без подтверждения остановки прежнего владельца.
- [ ] Summary и история отражают число событий, покрытие и длительность с
  явным denominator; при нуле eligible событий доля `n/a`.

## План реализации

1. Red: тесты отказа каждой стадии, partial_success, crash/timeout и
   старого coverage после failed fetch.
2. Green: аддитивные run/stage/attempt таблицы и единый lifecycle wrapper
   вокруг существующего source → Worker → archive path.
3. Refactor: один источник статусов и безопасных reason codes; документация.

## Затрагиваемые области и зависимости

- После TASK-025-1 и TASK-025-2; точные файлы уточняются по текущему diff.
- `worker_executions` остаётся нижележащим журналом, не итогом всего цикла.

## Проверка

- Целевые integration tests с fault injection и PostgreSQL concurrency
  там, где проверяется claim/lock; регрессии canonical refresh и alerts.

## Handoff и отчёт

- Отчёт выполнения: ожидается в `docs/changes/done/`.
- Follow-up / findings: failure-attempt gap TASK-025-1.
- Review: ожидается независимый Reviewer.
- Commit/push: ожидается после review.
