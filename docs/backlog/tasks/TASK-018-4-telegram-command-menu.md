# TASK-018-4 — Telegram command menu

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-018](../EPIC-018-post-rollout-runtime-corrections.md)
> **Требование:** [REQ-020](../../product/requirements/REQ-020-post-rollout-runtime-corrections.md)
> **ADR:** не требуется

## Результат и границы

До start polling bot registers public commands via `setMyCommands`; admin chat scopes
receive existing admin commands together with public commands. Handlers and authorization
middleware remain unchanged.

## Критерии приёмки

- [ ] Public menu включает start, help, predict, upcoming и edge.
- [ ] Каждый configured admin получает status, refresh и models only in their chat scope.
- [ ] Ошибка registration prevents polling, so missing command menu is observable at startup.

## План реализации

1. Добавить failing registration contract test с fake Telegram client.
2. Реализовать command registration и вызвать его before polling.

## Проверка

- `uv run pytest tests/test_bot_commands.py tests/test_bot_runtime_endpoint.py`

## Handoff и отчёт

- Отчёт выполнения: [TASK-018-4](../../changes/done/TASK-018-4-telegram-command-menu.md).
- Follow-up / findings: нет.
- Review: ожидает независимого reviewer.
- Commit/push: ожидает reviewer.
