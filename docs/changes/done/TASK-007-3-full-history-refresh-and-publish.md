# TASK-007-3 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-15
> **Задача:** [TASK-007-3](../../backlog/tasks/TASK-007-3-full-history-refresh-and-publish.md)

## Реализованный результат

NHL bounded job принимает provider snapshot, применяет его к canonical store,
проверяет freshness, пересобирает full-history features/EWM во временном
workspace, проверяет immutable model bundle и атомарно публикует витрину.
Failed/overlapping/duplicate runs блокируют affected public slice, не удаляя
audit predictions. Каждая prediction содержит run, canonical snapshot, feature
contract и immutable model provenance.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/orchestration/canonical_full_refresh.py` | Bounded runner, lock, gate и transactional publish. |
| `sports_forecast/orchestration/canonical_full_refresh_cli.py` | Scheduler entrypoint с явными environment inputs. |
| `sports_forecast/deploy/canonical_bootstrap.py` | Provider CSV → canonical revision adapter. |
| `sports_forecast/materialize.py` | Внешняя DB transaction и refresh provenance. |
| `migrations/versions/0008_*`, `0009_*` | Eligibility-state и prediction provenance. |
| `docs/operations/canonical-full-refresh.md` | Операционный runbook. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_canonical_full_refresh.py -q` — падение из-за отсутствующего runner.
- **Green:** targeted canonical refresh tests — успешно.
- **Refactor:** publication state и execution state объединены с materialization в одной session.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_canonical_bootstrap.py tests/test_canonical_freshness.py tests/test_canonical_full_refresh.py tests/test_canonical_full_refresh_cli.py tests/test_materialize.py tests/test_model_bundle.py tests/test_refresh_lock.py tests/test_worker_execution_state.py -q` | 23 passed |
| `uv run ruff check …` | успешно |
| `git diff --check` | успешно |
| `mypy` | не запущен: executable отсутствует в окружении |

## Документация, review и follow-up

- Документация: [canonical full refresh](../../operations/canonical-full-refresh.md).
- Review / security: не выполнялись.
- Follow-up: TASK-007-5 подключает scheduler topology, timeout/retry и deployment.

## Остаточные риски

- Полный NHL rebuild ещё не измерен на production объёме: это обязательное evidence TASK-007-6.
- Scheduler получает source CSV вне runner; его provider invocation и timeout policy принадлежат TASK-007-5.
