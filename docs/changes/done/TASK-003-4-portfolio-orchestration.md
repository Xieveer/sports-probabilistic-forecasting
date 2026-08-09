# TASK-003-4 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-003-4](../../backlog/tasks/TASK-003-4-portfolio-orchestration.md)

## Подтверждённый результат

`portfolio_refresh` строит heavy targets из проверенного portfolio catalog:
каждый deployment profile даёт изолированную пару tournament/source, model pool
и market/spec. Новый `dag_portfolio_refresh` раскрывает эти targets без
статического списка `SF_REFRESH_TOURNAMENTS`. Добавление profile в каталог
обнаруживается planner-ом без правки Python/DAG списка.

Для одного target строится отдельная heavy-цепочка с lock, вычисленным из
tournament/source. Повтор того же ключа сериализуется, а независимые задачи
ограничивает существующий Airflow pool. Валидатор каталога заранее отвергает
дублирующий profile для tournament/market_spec.

`dvc.yaml`, legacy `data_refresh` и их dev/CI multirun не изменены. Граница и
переходное правило scheduler описаны в
[portfolio-orchestration.md](../../operations/portfolio-orchestration.md).

## Доказательства

- Red: planner и per-target command отсутствовали; DAG contract первоначально не находил `dag_portfolio_refresh.py`.
- Дубликат profile оказался уже fail-fast контрактом `PortfolioConfigError`; новый тест фиксирует этот факт без ложного red-утверждения.
- `uv run pytest tests/test_portfolio_orchestration.py tests/test_portfolio_catalog.py tests/test_refresh_command.py tests/integration/test_portfolio_refresh_dag.py tests/integration/test_orchestration_contour.py -q` — 23 passed.
- `uv run pre-commit run mypy --all-files` — успешно.
- `make lint` — успешно.
- `make test-unit` — 820 passed, 8 deselected.

## Остаточные риски и handoff

Новый DAG не включался в production scheduler; одновременное включение с legacy
`data_refresh` для одного турнира создаст дублирующую работу, хотя per-key lock
её сериализует. Настройка Airflow pool требует измерения нагрузки источников.
Следующий этап — [TASK-003-5](../../backlog/tasks/TASK-003-5-lineup-fast-path.md):
отдельный fast path, не использующий heavy refresh.
