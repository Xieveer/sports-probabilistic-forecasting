# TASK-025-20 — Доступ календаря к состоянию odds-стадии

> **Статус:** код и независимое review завершены; CI/runtime gate открыт
> **Задача:** [TASK-025-20](../../backlog/tasks/TASK-025-20-calendar-stage-read-grant.md)

## Граница

Точечное право `SELECT` для API role на две таблицы, которые календарь
соединяет для определения режима odds. Остальные привилегии и HTTP-контракт
календаря не расширяются.

## Доказательство

Production v1.2.6: `/health` и `/ready` 200, `/calendar/nhl?period=today`
500 из-за `psycopg.errors.InsufficientPrivilege` на
`data_cycle_stage_results`. Сохранён root-only raw log; в Git и отчёте
нет секретов или полного внешнего ответа. Rollback v1.2.5 подтверждён:
API/bot/DB healthy, calendar 0/7/30 = 0/34/187, активных run 0,
оба таймера выключены. Developer выполнил red→green: точечный grant на
stage table и две колонки run table, first-rollout проверяет exact JOIN
до старта API. Developer: 53 целевых теста прошли, 2 PostgreSQL integration
теста пропущены без disposable URLs. Reviewer: 41 целевой тест прошёл,
2 integration пропущены; P0–P2 после correction нет. Независимый probe
на временном PostgreSQL с exact pinned image подтвердил JOIN и отсутствие
table-wide SELECT и доступа к `failure_code`. Полный unit suite:
1227 passed, 13 deselected; `make lint`, `make production-check` и
`make docs` (155 warnings) прошли. Полный локальный first-rollout из
clean commit, PR CI и production gate пока открыты.
