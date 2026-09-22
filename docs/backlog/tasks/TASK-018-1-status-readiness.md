# TASK-018-1 — Readiness в Telegram status

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-018](../EPIC-018-post-rollout-runtime-corrections.md)
> **Требование:** [REQ-020](../../product/requirements/REQ-020-post-rollout-runtime-corrections.md)
> **ADR:** не требуется

## Результат и границы

`/status` запрашивает `/ready` вместо `/health` и показывает оператору только результат
readiness либо безопасный общий отказ. `/health` и остальные handlers не меняются.

## Критерии приёмки

- [ ] Handler вызывает `${api_base_url}/ready`.
- [ ] Non-2xx, transport и JSON error не раскрывают исключение, URL или response body.

## План реализации

1. Добавить падающие handler tests для ready и safe failure.
2. Внести минимальное изменение в admin handler и выполнить targeted suite.

## Проверка

- `uv run pytest tests/test_bot_status.py`

## Handoff и отчёт

- Отчёт выполнения: [TASK-018-1](../../changes/done/TASK-018-1-status-readiness.md).
- Follow-up / findings: нет.
- Review: ожидает независимого reviewer после всего diff.
- Commit/push: ожидает reviewer.
