# TASK-007-1 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-14
> **Задача:** [TASK-007-1](../../backlog/tasks/TASK-007-1-canonical-store-and-bootstrap.md)

## Реализованный результат

Добавлен additive canonical store: `canonical_events` хранит текущее
canonical-состояние события, `canonical_event_revisions` — immutable provider
revisions, `refresh_watermarks` — последний imported snapshot турнира,
`bootstrap_imports` — idempotent audit artifact. Migration `0005` не изменяет
prediction-витрину и запрещает destructive downgrade.

`sports_forecast.deploy.canonical_bootstrap` строит проверяемый initial NHL
bundle из документированного локального `source.csv` без provider API вызова и
импортирует его одной транзакцией. Checksum проверяется до DB mutation;
повторный immutable ID не дублирует event/revision. Добавлен runbook
[canonical-bootstrap.md](../../operations/canonical-bootstrap.md).

## Доказательство TDD и проверки

- **Red:** `uv run pytest tests/test_canonical_bootstrap.py -q` — collection
  failed: отсутствовал модуль `sports_forecast.deploy.canonical_bootstrap`.
- **Green:** `uv run pytest tests/test_canonical_bootstrap.py tests/test_readiness_and_migrations.py tests/test_serving_data_archive.py -q` — 13 passed.
- `uv run ruff check sports_forecast/deploy/canonical_bootstrap.py sports_forecast/service/db/models.py migrations/versions/0005_canonical_store_bootstrap.py tests/test_canonical_bootstrap.py tests/test_readiness_and_migrations.py` — passed.
- `uv run pre-commit run mypy --files sports_forecast/deploy/canonical_bootstrap.py sports_forecast/service/db/models.py tests/test_canonical_bootstrap.py tests/test_readiness_and_migrations.py` — passed.
- Одноразовый локальный PostgreSQL 16: `alembic upgrade head` применил
  `0001`…`0005`; проверены четыре новые canonical-таблицы. Контейнер после
  проверки остановлен и удалён.
- `make test-unit` — 851 passed, 8 deselected, 31 warnings.
- `make lint` — не прошёл на существующем несвязанном `I001` в
  `tests/test_optuna_optimizer.py`; файл не менялся в TASK-007-1. Targeted
  Ruff нового diff зелёный.

## Изменённое и неизменённое

- Изменены ORM models, Alembic migration, immutable bootstrap CLI, контрактные
  тесты и bootstrap runbook.
- Не изменены refresh worker, EWM/features, API visibility, Telegram,
  scheduler, Compose, Object Storage upload, DVC workflow и model delivery:
  они остаются задачами TASK-007-2…007-6.

## Остаточные риски и follow-up

- Реальный полный NHL dataset ещё не был импортирован: для него нужны backup,
  безопасная доставка artifact и явное разрешение на VPS operations.
- Full-history EWM refresh, source updates и export snapshots не реализованы
  этим срезом; canonical store пока является подготовленной базой для них.
- Full repository lint блокирует существующий порядок imports в
  `tests/test_optuna_optimizer.py`; исправление должно быть отдельной
  согласованной задачей либо частью следующей затрагивающей этот файл работы.
