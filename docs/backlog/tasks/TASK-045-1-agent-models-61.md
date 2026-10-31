# TASK-045-1 — Карта моделей агентов

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-045](../EPIC-045-agent-models-61.md)
> **Требование:** [REQ-045](../../product/requirements/REQ-045-agent-models-61.md)
> **ADR:** не требуется

## Результат и границы

Активные Sol-профили и default используют `gpt-6.1-sol`; Luna и Astra сохраняются.
Валидатор и текущие карты моделей отражают то же назначение.

## Критерии приёмки

- [x] Активные профили соответствуют REQ-045.
- [x] Валидатор отвергает прежний Sol и принимает неизменённую Luna.
- [x] AI tests и `make ai-validate` проходят.

## План реализации

1. Обновить тесты и увидеть ожидаемый red.
2. Обновить профили и валидатор до green.
3. Синхронизировать документацию и выполнить проверки.

## Затрагиваемые области и зависимости

`.codex/`, `scripts/validate_ai_layer.py`, `tests/test_ai_layer_validation.py`,
`agents/README.md`, `docs/development/ai-agents-and-skills.md`.

## Проверка

`uv run pytest tests/test_ai_layer_validation.py -q`, `make ai-validate`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-045-1](../../changes/done/TASK-045-1-agent-models-61.md).
- Follow-up / findings: нет.
- Review: независимый Reviewer подтвердил REQ-045 без блокирующих findings;
  замечание форматирования устранено и проверено повторно.
- Commit/push: проверенный commit [`d29a40a3f952675bcc0733988f3af3f4b1054f58`](https://github.com/Xieveer/sports-probabilistic-forecasting/commit/d29a40a3f952675bcc0733988f3af3f4b1054f58);
  evidence фиксируется отдельным documentation-only коммитом и отправляется в той же ветке.
