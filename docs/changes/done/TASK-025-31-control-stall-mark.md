# TASK-025-31 — Исправление отметки stalled executor

> **Статус:** review завершён, выпуск ожидается.

## Причина

`sf_control_api` имеет `SELECT` на `data_cycle_runs`, но не имеет `UPDATE`.
Вызов `SELECT FOR UPDATE` требует `UPDATE` permission в PostgreSQL и завершался
ошибкой до вызова разрешённой функции
`public.mark_data_cycle_executor_stalled(text)`. Поэтому dispatcher не мог
отметить истёкший executor как stalled.

## Изменение

`mark_executor_stalled` теперь читает run обычным `SELECT`, выполняет быстрые
предварительные проверки и затем в PostgreSQL вызывает только существующую
`SECURITY DEFINER` функцию. Она повторно проверяет статус, ownership, heartbeat,
таймаут и отсутствие предыдущей отметки внутри одного атомарного `UPDATE`.
На SQLite остаётся guarded conditional `UPDATE` с проверкой `rowcount`. Ни один
grant не менялся.

## Проверки

- Red: `test_postgresql_stall_mark_uses_security_definer_without_row_update_grant`
  упал с `PermissionError` при обнаружении `FOR UPDATE`, до вызова функции.
- Green/refactor: тот же regression test прошёл после удаления row lock;
  PostgreSQL route вызвал definer function и обновил state через refresh.
- Дополнительный type-check red: `make type-check` сначала выявил
  "`object` has no attribute `compile`" в fake-session. Аннотация statement
  уточнена до SQLAlchemy `ClauseElement`; повторный type-check прошёл.
- `tests/test_data_cycle_recovery.py`: `9 passed, 1 skipped`; пропущен только
  отмеченный `integration` test конкурентного claim, потому что
  `SF_TEST_POSTGRES_URL` не задан.
- Ruff для repository и focused recovery tests: `All checks passed!`.
- Повторный focused PostgreSQL contract test: `1 passed`.
- `make type-check`: успешно, mypy проверил 382 source files.
- Команды выполнены через `systemd-run` с `MemoryMax=768M`,
  `MemorySwapMax=0` и timeout 30/45 секунд. Полный pytest не запускался.
- `make type-check` выполнен с `MemoryMax=1536M`, `MemorySwapMax=0`, timeout
  120 секунд.
- PostgreSQL grant behavior воспроизведён изолированным focused fake-session
  test; отдельный disposable PostgreSQL не был подключён.

Production не изменялся. Узкая SQL-функция остаётся источником атомарного
fencing; runtime privilege не расширялись.
Независимый Reviewer проверил права Control API, атомарность функции,
SQLite-путь и regression test; блокирующих findings нет.
