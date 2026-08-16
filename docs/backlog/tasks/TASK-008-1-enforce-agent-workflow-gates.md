# TASK-008-1 — Зафиксировать проверяемые gates workflow агентов

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-008](../EPIC-008-agent-workflow-gates.md)
> **Требование:** [REQ-009](../../product/requirements/REQ-009-agent-workflow-gates.md)
> **ADR:** [ADR-009](../../architecture/adr/ADR-009-enforce-agent-workflow-gates.md)

## Результат и границы

Rules, profiles, templates и `ai-validate` согласованно требуют пользовательский процесс.
Не изменяются production-код и удалённый Git.

## Критерии приёмки

- [x] Правила фиксируют ownership этапов и документационные handoff.
- [x] Validator блокирует read-only reviewer и потерю обязательных gates.
- [x] Templates содержат evidence review и commit/push.

## План реализации

1. Добавить падающий тест, выявляющий read-only reviewer.
2. Согласовать профиль, rules, skills, templates и валидатор.
3. Запустить целевые проверки и оформить report.

## Затрагиваемые области и зависимости

- `.codex/agents/`, `agents/`, `skills/`, `docs/`, `scripts/validate_ai_layer.py`, `tests/`.

## Проверка

- `uv run pytest tests/test_ai_layer_validation.py -q` — тесты workflow зелёные.
- `make ai-validate` — AI layer valid.

## Handoff и отчёт

- Отчёт выполнения: [TASK-008-1](../../changes/done/TASK-008-1-enforce-agent-workflow-gates.md)
- Follow-up / findings: нет
- Review: ожидает независимого reviewer
- Commit/push: ожидает reviewer после чистого review
