# TASK-013-1 — Реализовать вертикальный срез Research Loop

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-013](../EPIC-013-research-mode.md)
> **Требование:** [REQ-013](../../product/requirements/REQ-013-research-mode.md)
> **ADR:** [ADR-013](../../architecture/adr/ADR-013-research-mode-state-machine.md)

## Результат и границы

Добавить не подключённый к service/API research-модуль с persistent state machine и
тестовым доказательством двух изолированных итераций. Вне границ — LLM provider, сетевой
data discovery, изменение DVC/Airflow/MLflow и реализация engineering-задач.

## Критерии приёмки

- [x] Goal Contract, state, context packages, role responses и findings валидируются typed contracts.
- [x] State machine проходит Scientist → Data Researcher → EngineeringRequest → Experiment →
  Evaluator → Memory → следующая Scientist и сохраняется между экземплярами orchestrator.
- [x] Только gateway существующего Engineering Workflow допускает experiment после verified TASK.
- [x] Data Source Catalog и holdout exposure сохраняются вне LLM context.
- [x] Добавлены требуемые roles/profiles и каноническая документация.

## План реализации

1. Добавить failing unit-test двух итераций и отказа неverified engineering boundary.
2. Реализовать чистые contracts, JSON repository, harness и deterministic orchestrator.
3. Добавить роли, profiles, архитектурную документацию и проверки.

## Затрагиваемые области и зависимости

- `sports_forecast/research/`, `tests/test_research_orchestrator.py`.
- `agents/`, `.codex/agents/`, `docs/research/`, `docs/development/`, `references/`.
- Зависимость: Pydantic уже является прямой зависимостью FastAPI и используется в service schemas.

## Проверка

- `uv run pytest tests/test_research_orchestrator.py -q`.
- `make ai-validate`, `make lint`, `make docs`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-013-1](../../changes/done/TASK-013-1-research-loop-vertical-slice.md).
- Follow-up / findings: TASK-013-2 и TASK-013-3 завершены; TASK-013-4 отменён пользователем.
- Review: независимый финальный review завершён без P0/P1/P2 findings после исправлений.
- Commit/push: хеш проверенного коммита фиксируется reviewer в отчёте отдельным evidence-коммитом.
