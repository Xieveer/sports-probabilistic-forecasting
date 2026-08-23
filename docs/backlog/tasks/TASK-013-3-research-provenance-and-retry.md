# TASK-013-3 — Добавить provenance и retry structured contracts

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-013](../EPIC-013-research-mode.md)
> **Требование:** [REQ-013](../../product/requirements/REQ-013-research-mode.md)
> **ADR:** [ADR-013](../../architecture/adr/ADR-013-research-mode-state-machine.md)

## Результат и границы

Устранить findings pilot TASK-013-2: каждый ContextPackage и finding получает schema/as-of/
provenance metadata, а raw role adapter повторяет один запрос после Pydantic validation failure.
Не реализуются API client, сеть, настоящий LLM/Codex process или concurrent storage.

## Критерии приёмки

- [x] `ContextPackage`, `ResearchState` и data findings содержат schema version, UTC `as_of` и provenance.
- [x] Raw JSON role response валидируется до перехода; один невалидный ответ получает retry feedback.
- [x] После исчерпания retry adapter возвращает validation error и orchestrator не делает переход.
- [x] Unit tests доказывают metadata persistence и invalid-then-valid retry.

## План реализации

1. Добавить падающие tests для retry и metadata.
2. Расширить Pydantic contracts и реализовать standalone validated raw gateway.
3. Обновить docs/evidence и выполнить целевые проверки.

## Проверка

- `uv run pytest tests/test_research_orchestrator.py -q`.
- `make ai-validate`, `make lint`, `make docs`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-013-3](../../changes/done/TASK-013-3-research-provenance-and-retry.md).
- Follow-up / findings: TASK-013-4 `cancelled` пользователем 2026-08-24; programmatic Codex
  runner и durable multi-process storage не планируются.
- Review: независимый финальный review завершён без P0/P1/P2 findings после исправлений.
- Commit/push: хеш проверенного коммита фиксируется reviewer в отчёте отдельным evidence-коммитом.
