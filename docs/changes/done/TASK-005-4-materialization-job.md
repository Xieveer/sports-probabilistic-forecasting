# TASK-005-4 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-005-4](../../backlog/tasks/TASK-005-4-materialization-job.md)

## Реализованный результат

Worker стал одноразовым idempotent entrypoint. Он проверяет immutable active
bundle до inference, исключает повтор завершённого `run_id`, materializes NHL
`winner_withOT` и сохраняет только безопасный execution state. Stale+upsert
одного serving-среза происходят в одной DB-транзакции; файловый parquet
готовится до смены API-витрины.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/worker.py` | Bounded Worker, bundle fail-fast и safe outcome. |
| `models.py`, `repository.py`, migration `0004` | Execution state, idempotency и atomic showcase publish. |
| `materialize.py` | Verified bundle path и transaction-safe публикация. |
| `Dockerfile`, `docker-compose.prod.yml`, `.env.example` | Фиксированная NHL-команда, env и resource limits. |
| `docs/operations/materialization-worker.md` | Scheduler/runbook и partial failure semantics. |

## Доказательство TDD и измерение

- **Red:** отсутствовали `WorkerExecutionRepository`, atomic publish и Worker
  module; тесты завершались ImportError/AttributeError.
- **Green:** 6 target tests подтверждают state, rollback витрины, bundle
  fail-fast, repeat run и фактический success count.
- **Development-like measurement:** legacy NHL artifact, 3 248 inference rows,
  1 624 predictions, 4.48 сек., max RSS ≈399.6 MiB, exit 0. Полное evidence:
  [worker-measurement-evidence.md](../../operations/worker-measurement-evidence.md).

## Фактически выполненные проверки

| Команда | Результат |
|---|---|
| Связанные Worker tests | Успешно: 6 passed. |
| `make lint` | Успешно. |
| `make test-unit` | Успешно: 836 passed, 8 deselected. |
| `uv run pre-commit run mypy --all-files` | Успешно. |
| Alembic SQL dry-run | Успешно: migration `0004`. |
| Production Compose config с тестовыми env | Успешно. |

## Остаточные риски

Измерение не является production deployment, проверкой published image или
Object Storage mount. Эти evidence остаются в TASK-005-6 и требуют отдельного
разрешения владельца.
