# TASK-025-8 — Восстановление Data Cycle без второго исполнителя

> **Статус:** done; фактическое production включение остаётся release gate TASK-025-9
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

- [x] Исполнитель получает уникальный generation/fencing token при claim;
  устаревший owner не может записать terminal result или продолжить
  publication после нового claim.
- [x] При timeout сначала подтверждается остановка прежнего process/service
  владельца, затем выполняется recovery/новый claim. При невозможности
  подтвердить остановку run остаётся явно stalled/требует вмешательства;
  автоматического второго запуска нет.
- [x] Одновременно активен максимум один run на pipeline/турнир при нескольких
  API и dispatcher процессах; PostgreSQL concurrency test проверяет race.
- [x] Незапущенные стадии после crash получают `skipped` с безопасной причиной,
  фактически прерванная стадия — `failed`; история сохраняет предыдущий run.
- [x] Dispatcher heartbeat/owner state видны в status API и Telegram без
  раскрытия host details, секретов или произвольных команд.
- [x] Fault injection покрывает crash до/после claim, потерю heartbeat,
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

- Recovery требует подтверждения systemd InvocationID и инвентаризации всех
  Compose one-off контейнеров с совпадающими run ID, owner ID и generation;
  если доказательство неполное, run остаётся stalled и требует ручного разбора.
- Длительные стадии обновляют generation-guarded heartbeat; любой abnormal exit
  после попытки claim не переводит run в terminal до host recovery.
- [Отчёт выполнения и проверок](../../changes/done/TASK-025-8-executor-fencing.md).
- Независимый повторный review: чистый; PostgreSQL 16 migration, grants и race
  tests подтверждены Reviewer.
- Runtime installation, backup/rollback evidence, включение scheduler timer и
  первый ежедневный NHL run остаются в [TASK-025-9](TASK-025-9-release-readiness.md).
