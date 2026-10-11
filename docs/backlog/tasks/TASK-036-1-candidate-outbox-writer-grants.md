# TASK-036-1 — Права Worker на запись кандидата registry

> **Статус:** done — код и изолированный PostgreSQL проверены; production gate ожидается
> **Владелец:** Developer
> **Эпик:** [EPIC-036](../EPIC-036-v1-3-3-registry-rollout.md)

## Дефект

Реальная ORM-запись `RegistryCandidateOutbox` под `sf_refresh_writer` в
репетиции выпуска завершилась `InsufficientPrivilege`. SQLAlchemy выполняет
`INSERT ... RETURNING id, attempts, created_at`; выданных INSERT и USAGE
sequence недостаточно для чтения возвращаемых колонок. Транзакция откатилась,
поэтому непустой feedback gate не прошёл.

## Критерии

1. Повторяемые runtime grants дают Worker только нужный `SELECT` на три
   возвращаемых колонки и сохраняют запрет на чтение остальных данных очереди.
2. Production preflight выполняет реальный эквивалент `INSERT ... RETURNING`
   внутри откатываемой транзакции, а не проверяет один INSERT без строк.
3. Интеграционный тест на отдельном PostgreSQL выполняет ORM `flush()` под
   ролью `sf_refresh_writer` и откатывает транзакцию.
Локальные доказательства — в
[отчёте](../../changes/done/TASK-036-1-candidate-outbox-writer-grants.md).

Production проверка настоящего неизвестного alias до локального решения и
повторной publication/sync остаётся release gate EPIC-036; локальный bug fix
её не закрывает.

## Границы

Исправление только прав и соответствующего release probe; оно не меняет
правила сопоставления матчей. Production grant применяется только как часть
проверенного выпуска, а не ручным расширением привилегий в обход миграции.
