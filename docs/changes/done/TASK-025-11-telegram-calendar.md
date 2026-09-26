# TASK-025-11 — Календарь NHL в Telegram

## Результат

`/upcoming` теперь обращается к `GET /calendar/{tournament}` и не зависит от
таблицы прогнозов. Пользователь выбирает «Сегодня», «Завтра», `3`, `7`, `14`
или `30` букмекерских суток. Карточка показывает время МСК, участников,
состояние календаря, готовность прогноза и коэффициентов и общий статус.

Пустое подтверждённое окно отдельно от неполного, устаревшего, неизвестного
или недоступного календаря. Ошибка API показывает недоступность расписания.
Telegram получает до 50 событий за страницу и сообщает общее число и усечение.
Размер каждого сообщения ограничивается по UTF-16 единицам Telegram, а разбиение
проходит по границам карточек. Имена ограничиваются до HTML-экранирования.
Существующие `/predict` и `/edge` сохраняют вызов прогнозного API. Меню и
справка описывают новые варианты горизонта; футбольные турниры не добавлены.

## Критерии

- Реализованы периоды `today`, `tomorrow`, `3`, `7`, `14`, `30`; точные окна
  08:00–08:00 вычисляются календарным API. При 03:00 МСК Today получает
  остаток текущих суток.
- События показываются независимо от прогнозов и коэффициентов, включая
  состояния переноса и отмены.
- Покрытие `confirmed_empty`, `incomplete`, `stale`, `unavailable` и `unknown`
  имеет отдельные пользовательские сообщения; сбой HTTP не отображается как
  пустое расписание.
- Выполнен локальный сценарий Telegram handler → ASGI API → SQLite calendar и
  readiness с fake Telegram transport, фиксированным временем, без токена,
  браузера и внешнего сетевого запроса.
- Регрессии проверяют длинные HTML-спецсимволы и emoji в сообщениях, лимит
  UTF-16, а также callback со старой inline-кнопки при `InaccessibleMessage`.
- Существующие команды проверены contract-тестами. Admin handlers и маршруты
  этим изменением не затрагивались.

## Доказательства

- Red: `uv run pytest -q tests/test_bot_calendar_integration.py` — падение на
  старом числовом handler-сценарии до вызова календарного API.
- Green и регрессии: `uv run pytest -q tests/test_bot_calendar_integration.py tests/test_bot_predict_format.py tests/test_bot_commands.py tests/test_bot_light_refresh_path.py tests/test_bot_status.py tests/test_calendar_api.py tests/test_event_readiness.py tests/test_data_cycle_lifecycle.py` — **78 passed**.
- `make lint` — прошло (`ruff check sports_forecast tests`).
- `uv run ruff format --check sports_forecast/bot/handlers/predict.py sports_forecast/bot/handlers/start.py sports_forecast/bot/dispatcher.py tests/test_bot_predict_format.py tests/test_bot_calendar_integration.py` — прошло.
- Целевой `uv run mypy sports_forecast/bot/handlers/predict.py sports_forecast/bot/handlers/start.py sports_forecast/bot/dispatcher.py` нашёл несвязанные ошибки в импортируемых модулях репозитория; их список передан в handoff Product Owner. Ошибка типов в новом callback была устранена.
- Независимый Reviewer повторно проверил TASK11 после исправления findings: P0/P1/P2 findings отсутствуют. Reviewer подтвердил bot tests, API E2E, Ruff и форматирование.

## Изменённые файлы

- `sports_forecast/bot/handlers/predict.py`
- `sports_forecast/bot/handlers/start.py`
- `sports_forecast/bot/dispatcher.py`
- `tests/test_bot_predict_format.py`
- `tests/test_bot_calendar_integration.py`
- `README.md`

## Остаточные риски и передача

- Сейчас Telegram показывает первую страницу из максимум 50 событий. Если
  API вернул больше, бот выводит точное общее число и сообщает, что список
  усечён; интерактивная навигация между страницами не добавлена.
- Commit/push остаётся за Product Owner после review; этот Developer изменений не фиксировал.
- Полные CI и release-проверки инициативы не входят в этот TASK.
