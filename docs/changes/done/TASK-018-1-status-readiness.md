# TASK-018-1 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-09-08
> **Задача:** [TASK-018-1](../../backlog/tasks/TASK-018-1-status-readiness.md)

## Реализованный результат

Админский `/status` запрашивает `/ready`, возвращает короткий сигнал готовности и при
HTTP/transport/JSON error отвечает без URL, response body или текста исключения.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/bot/handlers/admin.py` | Безопасный readiness handler. |
| `tests/test_bot_status.py` | Регрессии ready и redaction ошибки. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_bot_status.py -q` — 2 failed: handler вызывал
  `/health` и выводил `postgresql://user:secret@db`.
- **Green:** `uv run pytest tests/test_bot_status.py tests/test_bot.py tests/test_bot_light_refresh_path.py -q` — 9 passed.
- **Refactor:** raw readiness body заменён на стабильный короткий операторский сигнал.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run ruff check sports_forecast/bot/handlers/admin.py tests/test_bot_status.py` | passed |
| `uv run pre-commit run mypy --files sports_forecast/bot/handlers/admin.py tests/test_bot_status.py` | passed |

## Документация, review и follow-up

- Документация: REQ-020 и EPIC-018.
- Review / security: ожидается для общего diff.
- Commit/push: ожидает reviewer; не выполнялся.
- Follow-up: нет.

## Остаточные риски

- Live Telegram/API не вызывались; покрыта контролируемая HTTP-граница.
