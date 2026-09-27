# TASK-025-8 — Восстановление Data Cycle без второго исполнителя

## Результат

Добавлен generation-based owner fencing для Data Cycle. Worker проверяет owner
generation непосредственно перед изменяющими данными операциями и публикацией;
долгие стадии поддерживают owner heartbeat. Stale heartbeat помечает run как
`stalled`, но не освобождает active slot.

Host recovery связывает run с systemd InvocationID и метками каждого Compose
one-off контейнера. `recover-data-cycle.sh` останавливает unit и контейнеры,
заново проверяет полную инвентаризацию и отправляет структурированное evidence.
При неполном доказательстве recovery останавливается, а run остаётся stalled.
Любой abnormal exit после попытки claim откладывает terminal failure до этой
host проверки. PostgreSQL monotonic function позволяет `sf_control_api` отметить
просроченный owner stalled без прямого права снять этот fence.

## Проверки

- Целевой цикл Data Cycle: **74 passed, 3 skipped**; skips требуют disposable
  PostgreSQL URLs и в этом локальном запуске были gated.
- Независимый Reviewer отдельно подтвердил PostgreSQL 16 migration, grants и
  race tests; повторный TASK-025-8 review чистый.
- `bash -n` для dispatcher, runner, owner guard и recovery scripts — passed.
- Ruff по затронутым Python/test файлам — passed.
- `git diff --check` — passed.

Fault tests покрывают claim/heartbeat/recovery, stale publication fencing,
TERM/abnormal exit с живым one-off контейнером и быструю успешную/ошибочную
стадию. Реальный production timer не включался и остаётся release gate
TASK-025-9 вместе с backup, rollback и первым ежедневным NHL run.

## Изменённые границы

Изменены orchestration lifecycle/repository fencing, recovery CLI/host scripts,
PostgreSQL migration/grants, Compose owner labels, тесты recovery/topology и
runbook [production runtime topology](../../operations/production-runtime-topology.md).
TASK-025-5 Telegram outbox остаётся незавершённым и этим отчётом не закрывается.
