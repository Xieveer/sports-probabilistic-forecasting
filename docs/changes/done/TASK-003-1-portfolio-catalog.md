# TASK-003-1 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-003-1](../../backlog/tasks/TASK-003-1-portfolio-catalog.md)

## Подтверждённый результат

Каталог `conf/portfolio/default.yaml` и typed API
`load_portfolio_catalog()` связывают legacy NHL и футбольный candidate через
`sport`, `tournament`, `model_pool`, `market_spec` и lifecycle. Валидатор
останавливает отсутствующие ссылки, несовместимый sport, повторные membership и
production profile без immutable model reference.

Каталог декларативен: Hydra consumers, DVC, Airflow, пути моделей и БД не
изменены. Границы и подключение турнира описаны в README, ADR-003 и
`HOW_TO_ADD_NEW_TOURNAMENT.md`.

## Доказательства

- Добавлен test отсутствующей ссылки tournament → model pool; он прошёл сразу,
  поскольку соответствующая fail-fast ветка уже существовала. Поэтому red не
  заявляется как доказательство этого изменения.
- `uv run pytest tests/test_portfolio_catalog.py -q` — 7 passed.
- `make test-unit` — 804 passed, 8 deselected.
- `make lint` и targeted mypy hook — успешно.

## Follow-up

TASK-003-2 может использовать public typed catalog contract для builder-а
football model pool; TASK-003-3 остаётся зависимой от TASK-003-2.
