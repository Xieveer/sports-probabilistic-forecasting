# TASK-018-2 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-09-08
> **Задача:** [TASK-018-2](../../backlog/tasks/TASK-018-2-bootstrap-database-url-file.md)

## Реализованный результат

DB boundary теперь читает `DATABASE_URL_FILE` before `DATABASE_URL`. Поэтому direct
`canonical_bootstrap import-nhl` uses the same file-backed credential contract as
container API/Worker/Migrator; empty or unreadable file fails rather than falling back
to SQLite.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/service/db/engine.py` | Единый file-backed DB URL resolver. |
| `tests/test_database_url_file.py` | Priority и safe file-failure tests. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_database_url_file.py -q` — 2 failed: resolver
  игнорировал file и не отклонял пустой secret.
- **Green:** `uv run pytest tests/test_database_url_file.py tests/test_canonical_bootstrap.py tests/test_readiness_and_migrations.py -q` — 12 passed.
- **Refactor:** не требовался.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run ruff check sports_forecast/service/db/engine.py tests/test_database_url_file.py` | passed |
| `uv run pre-commit run mypy --files sports_forecast/service/db/engine.py tests/test_database_url_file.py` | passed |

## Документация, review и follow-up

- Документация: REQ-020 и EPIC-018.
- Review / security: ожидается для общего diff.
- Commit/push: ожидает reviewer; не выполнялся.
- Follow-up: нет.

## Остаточные риски

- Runtime entrypoint сохраняет собственное чтение file; resolver даёт тот же результат
  для direct CLI и не меняет Compose.
