# TASK-026-6 — Обратная очередь и полный цикл registry

> **Статус:** in_progress
> **Владелец:** Developer
> **Эпик:** [EPIC-026](../EPIC-026-entity-registry.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **ADR:** [ADR-027](../../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md)

## Результат и границы

Сервер отправляет впервые увиденные обозначения в локальную очередь через
durable outbox и Object Storage. Владелец решает их локально и публикует
новую версию; сервер сам не подтверждает связи.

## Критерии приёмки

- [x] Повторная или прерванная доставка не теряет и не дублирует кандидата;
      ack означает получение локально, а не подтверждение связи.
- [x] До нового снимка неизвестная букмекерская связь не прикрепляет odds,
      но спортивный календарь и допустимый прогноз остаются доступны.
- [x] После локального решения и публикации сервер разрешает связь по новому
      snapshot без ручной правки серверной БД.
- [x] NHL и контрольный второй турнир проходят один и тот же сквозной процесс;
      имя/ID турнира не зашиты в Python-ветвление.
- [ ] Совместимость, наблюдаемость, recovery/runbook и независимый EPIC review
      подтверждены; будущий player contract не требует player-прогнозов.

## План реализации

1. Написать падающие тесты lost ack, retry, duplicate и unresolved runtime.
2. Реализовать outbox/batches/import/ack и строгий reader mode.
3. Проверить полный путь, документацию и release handoff без развёртывания.

## Зависимости и проверка

- После [TASK-026-2](TASK-026-2-local-review-ui.md) и
  [TASK-026-5](TASK-026-5-registry-publication.md).
- Затрагивает server outbox, Object Storage feedback, local queue, runtime
  odds/calendar и тесты; команды записать в отдельном отчёте `done`.
- Следующий gate: независимый TASK review и полный EPIC review/CI.
