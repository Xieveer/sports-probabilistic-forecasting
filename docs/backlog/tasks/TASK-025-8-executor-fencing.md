# TASK-025-8 — Восстановление Data Cycle без второго исполнителя

> **Статус:** backlog
> **Владелец:** Developer и Operations Agent
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

После crash/timeout Data Cycle не остаётся бессрочно `running`, но новый
executor не запускается одновременно со старым. Подтверждение остановки
производственного systemd/Compose владельца и DB fencing образуют один
контракт; истёкший heartbeat сам по себе не разрешает takeover.

## Критерии приёмки

- [ ] Исполнитель получает уникальный generation/fencing token при claim;
  устаревший owner не может записать terminal result или продолжить
  publication после нового claim.
- [ ] При timeout сначала подтверждается остановка прежнего process/service
  владельца, затем выполняется recovery/новый claim. При невозможности
  подтвердить остановку run остаётся явно stalled/требует вмешательства;
  автоматического второго запуска нет.
- [ ] Одновременно активен максимум один run на pipeline/турнир при нескольких
  API и dispatcher процессах; PostgreSQL concurrency test проверяет race.
- [ ] Незапущенные стадии после crash получают `skipped` с безопасной причиной,
  фактически прерванная стадия — `failed`; история сохраняет предыдущий run.
- [ ] Dispatcher heartbeat/owner state видны в status API и Telegram без
  раскрытия host details, секретов или произвольных команд.
- [ ] Fault injection покрывает crash до/после claim, потерю heartbeat,
  зависший Worker, повторный callback и failover на ограниченном тестовом
  runtime. Реальный production timer включается только в release gate.

## Зависимости и проверка

- Зависит от TASK-025-3/7 и TASK-025-4. Согласуется с Operations Agent по
  конкретному systemd/Compose stop/health контракту.
- Нельзя вводить CLI `owner_stopped` без проверяемого подтверждения или
  освобождать lock только по TTL.
- PostgreSQL integration/race tests, fake executor fault matrix, systemd
  dry-run и review security/operations boundaries.

## Handoff и отчёт

- Отчёт выполнения: ожидается в `docs/changes/done/`.
- Review: ожидается независимый Reviewer.
- Commit/push: ожидается после review.
