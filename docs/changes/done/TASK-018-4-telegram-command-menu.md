# TASK-018-4 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-09-08
> **Задача:** [TASK-018-4](../../backlog/tasks/TASK-018-4-telegram-command-menu.md)

## Реализованный результат

Перед polling бот вызывает Telegram `setMyCommands`: общее меню содержит `/start`,
`/help`, `/predict`, `/upcoming`, `/edge`, а scope каждого configured администратора
дополняется `/status`, `/refresh`, `/models`. Existing handlers и middleware авторизации
не менялись.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/bot/dispatcher.py` | Наборы команд и их регистрация. |
| `sports_forecast/bot/__main__.py` | Регистрация before polling. |
| `tests/test_bot_commands.py` | Контракт public/admin Telegram scopes. |
| `docs/source/nhl_local_operations.rst` | Описание меню оператору. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_bot_commands.py -q` — collection error: отсутствовала
  функция регистрации команд.
- **Green:** `uv run pytest tests/test_bot_commands.py tests/test_bot_runtime_endpoint.py tests/test_bot.py -q` — 5 passed.
- **Refactor:** команды оформлены как неизменяемые наборы, чтобы public и admin scopes
  не расходились.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run ruff check sports_forecast/bot/dispatcher.py sports_forecast/bot/__main__.py tests/test_bot_commands.py` | passed |
| `uv run pre-commit run mypy --files sports_forecast/bot/dispatcher.py sports_forecast/bot/__main__.py tests/test_bot_commands.py` | passed |

## Документация, review и follow-up

- Документация: REQ-020, EPIC-018 и NHL local operations.
- Review / security: ожидается для общего diff.
- Commit/push: ожидает reviewer; не выполнялся.
- Follow-up: нет.

## Остаточные риски

- Вызов Bot API не выполнялся вне тестового double; startup остановится before polling при
  ошибке регистрации, что делает проблему наблюдаемой.
