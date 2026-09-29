# TASK-025-31 — Отмечать stalled executor без UPDATE grant у Control API

> **Статус:** reviewed_pending_release
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)

## Наблюдаемый дефект

Production dispatcher использует `sf_control_api`, которому разрешён `SELECT`
из `data_cycle_runs` и вызов узкой `SECURITY DEFINER` функции
`mark_data_cycle_executor_stalled`. PostgreSQL требует право `UPDATE` для
`SELECT ... FOR UPDATE`, поэтому `DataCycleRunRepository.mark_executor_stalled`
падал до вызова разрешённой функции. Это останавливало recovery polling при
просроченном heartbeat.

## Критерии исправления

- [x] PostgreSQL path читает текущий run без row lock и вызывает только узкую
  `SECURITY DEFINER` функцию, которая атомарно повторно проверяет условия и
  выставляет `executor_stalled_at`.
- [x] SQLite сохраняет существующий guarded UPDATE и его rowcount semantics.
- [x] Regression test имитирует Control роль без UPDATE privilege: попытка
  `FOR UPDATE` запрещена, функция при этом вызывается и метод завершается.
- [x] Полный адресный recovery module и Ruff проходят с ограничениями ресурсов;
  полный pytest не запускается.
- [x] `make type-check` проходит; аргумент SQLAlchemy statement в fake-session
  аннотирован типом `ClauseElement`.
- [x] Независимое review кода, теста и документации без блокирующих findings.

## Граница

Не меняются функция/миграции, grants, схема БД, host evidence и terminal
recovery. Control API не получает широкое UPDATE право. PostgreSQL concurrency и
SQL-функция остаются атомарными границами fencing.

Результат — в [отчёте](../../changes/done/TASK-025-31-control-stall-mark.md).
