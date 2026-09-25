# TASK-024-2 — Фиксированная карта моделей GPT-6

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-024](../EPIC-024-initiative-agent-workflow.md)
> **Требование:** [REQ-024](../../product/requirements/REQ-024-initiative-agent-workflow.md)
> **ADR:** не требуется

## Результат и границы

Профили используют Luna для BA/Developer/тестов, Astra только для Architect, Sol для
остальных ролей и default. Валидатор отклоняет старые модели и неверное назначение Astra.

## Критерии приёмки

- [x] Все активные профили и default соответствуют фиксированной карте REQ-024.
- [x] `make ai-validate` отклоняет Astra у любой роли кроме Architect и любую GPT-5.6.
- [x] Существующая пользовательская правка профиля product-analyst сохранена при переносе роли в Business Analyst.

## План реализации

1. Падающие тесты валидатора модели и роли.
2. Обновление профилей и валидатора.
3. Фокусные тесты и `make ai-validate`.

## Затрагиваемые области и зависимости

`.codex/`, `scripts/validate_ai_layer.py`, `tests/test_ai_layer_validation.py`.

## Проверка

`uv run pytest tests/test_ai_layer_validation.py -q` и `make ai-validate`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-024-2](../../changes/done/TASK-024-2-gpt-6-profiles.md).
- Follow-up / findings: нет.
- Review: независимая проверка REQ-024 без блокирующих findings.
- Commit/push: ожидает Reviewer.
