# TASK-005-2 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-005-2](../../backlog/tasks/TASK-005-2-readiness-and-migrations.md)

## Реализованный результат

`/health` стал liveness probe и возвращает HTTP 200 без SQL-подключения.
`/ready` выполняет обязательный `SELECT 1` и отвечает HTTP 503 с безопасным
`not_ready`, если БД недоступна. Alembic получил baseline revision
`0001_prediction_store_baseline`; API и materialization Worker больше не
создают и не изменяют schema при старте.

Точная локальная команда migration — `make db-migrate`; production-команда и
порядок `backup → migrate → ready → Worker` записаны в runbook.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/service/app.py`, `routers/health.py` | Разделение liveness/readiness без изменения prediction API. |
| `sports_forecast/materialize.py` | Worker больше не выполняет startup DDL. |
| `alembic.ini`, `migrations/` | Versioned additive baseline schema. |
| `Dockerfile`, `Makefile` | Migration files входят в runtime image; добавлена команда `db-migrate`. |
| `docs/operations/database-migrations.md`, `production-handoff.md` | Backup, recovery, forward-fix и rollout runbook. |
| `tests/test_readiness_and_migrations.py`, `tests/test_materialize.py` | Контракты readiness, отсутствия startup DDL и повторяемости migration. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_readiness_and_migrations.py -q` — 4 expected failures: `/health` имел статус `degraded`, `/ready` отсутствовал, startup вызывал `create_all`, Alembic не был настроен.
- **Green:** тот же набор после реализации — 4 passed; после проверки положительного readiness-сценария — 6 passed.
- **Refactor:** liveness не содержит SQL-пинга; общий migration protocol вынесен из runtime-кода в Alembic и runbook.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_readiness_and_migrations.py tests/test_materialize.py tests/test_production_topology.py -q` | Успешно: 15 passed. |
| `make test-unit` | Успешно: 798 passed, 8 deselected. |
| `make lint` | Успешно. |
| `uv run pre-commit run mypy --all-files` | Успешно. |
| `uv run alembic -c alembic.ini upgrade head --sql` | Успешный SQLite dry-run baseline revision. |
| `make db-migrate DATABASE_URL=sqlite:////tmp/sf-make-migrate.db` | Успешное применение migration. |
| Disposable PostgreSQL 16: два `alembic upgrade head` | Успешно; второй запуск идемпотентен, `alembic_version=0001_prediction_store_baseline`. |
| `docker build --target api --tag sports-forecast-task0052-api-check .` | Успешно; временный image удалён. |

## Документация, review и follow-up

- Runbook: [database-migrations.md](../../operations/database-migrations.md); handoff:
  [production-handoff.md](../../operations/production-handoff.md).
- Independent reviewer, security-reviewer и documentation-writer в этой сессии не запускались; их handoff — этот отчёт и TASK.
- Follow-up: TASK-005-4 и TASK-005-5 могут использовать `/ready` и отдельный migration gate.

## Остаточные риски

- Legacy schema, созданная до Alembic через `init_db()`, требует сравнения на disposable PostgreSQL перед ручным `alembic stamp`; автоматический stamping намеренно отсутствует.
- Production backup, restore и запуск scheduler остаются задачей Operations Agent и не выполнялись на VPS.
