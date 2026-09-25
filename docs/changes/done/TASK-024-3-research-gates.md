# TASK-024-3 — отчёт о финансовых gates Research

> **Статус задачи:** done
> **Дата:** 2026-09-25
> **Задача:** [TASK-024-3](../../backlog/tasks/TASK-024-3-research-gates.md)

## Реализованный результат

Новый контракт требует финансовые результаты и бюджет пяти циклов без
обязательных ранних ML-порогов. Harness различает отсутствующие метрики (`INVALID`)
и проваленные критерии (`FAIL`), запрещает неположительный ROI и сравнивает profit
с baseline и известной действующей моделью. Новый run со старым контрактом
отклоняется; ранее сохранённый run читается.

## Изменённые границы

`sports_forecast/research/{contracts,evaluation,orchestrator,adapters}.py`,
`tests/test_research_acceptance_gates.py`, `tests/test_research_orchestrator.py`.

## Доказательство TDD

- **Red:** `uv run pytest tests/test_research_acceptance_gates.py::test_new_research_goal_reserves_five_full_attempts -q` — budget 4 принимался.
- **Red:** `uv run pytest tests/test_research_acceptance_gates.py::test_new_contract_rejects_non_positive_observed_roi -q` — два случая получали PASS.
- **Red:** `uv run pytest tests/test_research_acceptance_gates.py::test_new_contract_rejects_known_current_model_profit_even_without_flag -q` — худший кандидат получал PASS.
- **Red:** `uv run pytest tests/test_research_acceptance_gates.py::test_new_run_cannot_start_with_legacy_goal -q` — старый контракт создавал новый run.
- **Green:** `uv run pytest tests/test_research_acceptance_gates.py tests/test_research_orchestrator.py tests/test_ai_layer_validation.py -q` — 37 passed.
- **Refactor:** per-iteration LLM evaluator убран; решение Harness детерминированно.

## Фактически выполненные проверки

- Фокусный набор — 37 passed; независимый Reviewer повторно выполнил research-набор — 26 passed.
- `make test-unit` — 1049 passed, 8 deselected; итоговый `make test` — 1058 passed.
- `uv run mypy sports_forecast/research/contracts.py sports_forecast/research/evaluation.py sports_forecast/research/orchestrator.py sports_forecast/research/adapters.py` — успешно.

## Документация, review и follow-up

- Документация: [Research Mode](../../research/research-mode.md).
- Review / security: три найденных обхода gates исправлены; повторный независимый review — блокирующих findings нет.
- Commit/push: ожидает reviewer/PR.
- Follow-up: нет.

## Остаточные риски

- Experiment runner должен рассчитать новые поля; без них Harness возвращает INVALID.
- Контракт сам не доказывает единство тестовой выборки для трёх profit;
  это проверяется по evidence конкретного исследования.
