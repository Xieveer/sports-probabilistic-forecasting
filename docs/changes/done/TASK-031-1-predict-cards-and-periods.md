# TASK-031-1 — Отчёт: карточки прогнозов и периоды

> **Статус задачи:** done
> **Дата:** 2026-10-11
> **Задача:** [TASK-031-1](../../backlog/tasks/TASK-031-1-predict-cards-and-periods.md)

## Реализованный результат

`/predict` предлагает букмекерские периоды с границей 08:00 МСК и отправляет
отдельную карточку на прогноз. В карточке есть время МСК, вероятность, Pinnacle,
Edge, EV и рекомендация; отсутствие линии показано явно. Формат принимает
несколько рекомендаций по разным рынкам. `/edge` и `/models` удалены из меню и
обработчиков. Бот получает поддерживаемые Data Cycle из control API; сейчас
сервер поддерживает NHL. Публичный API сохранил прежний параметр `hours`.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/service/db/repository.py`, `sports_forecast/service/routers/predictions.py` | Букмекерское окно прогнозов |
| `sports_forecast/bot/handlers/`, `sports_forecast/bot/dispatcher.py` | Карточки, периоды, меню и цикл |
| `tests/test_prediction_repository_upcoming.py`, `tests/test_bot_*.py` | Контрактные проверки |

## Доказательство TDD

- **Red:** адресные новые тесты окна, карточек, меню, выбора цикла и нескольких рекомендаций падали до реализации.
- **Green:** `uv run pytest -q tests/test_bot_admin_control.py tests/test_bot_predict_format.py` — 41 passed.
- **Refactor:** ограничены длины callback и полей карточки по замечаниям review.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `make test-unit` | 1615 passed, 16 deselected |
| `uv run pytest -q tests/test_bot_admin_control.py tests/test_bot_predict_format.py` | 41 passed |
| `make lint` | passed |
| `uv run pre-commit run mypy --files sports_forecast/bot/handlers/admin.py sports_forecast/bot/handlers/predict.py sports_forecast/bot/dispatcher.py sports_forecast/service/routers/predictions.py sports_forecast/service/db/repository.py` | passed |

## Документация, review и follow-up

- Документация: [REQ-031](../../product/requirements/REQ-031-real-bets-ledger.md), [EPIC-031](../../backlog/EPIC-031-real-bets-ledger.md), README.
- Review / security: независимый Reviewer; найденные P2 и P3 исправлены, повторное review без блокирующих findings.
- Проверенный commit инициативы: `db0e4cb`.
- Follow-up: TASK-031-2 — журнал и закрытый API; кнопка записи ставки войдёт в TASK-031-3.

## Остаточные риски

- Аномально большое значение revision Data Cycle может превысить 64 байта Telegram callback. Runtime DB ограничивает его целым числом; на итоговом gate проверить ввод API.
