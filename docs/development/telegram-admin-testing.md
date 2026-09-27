# Проверка администрирования Telegram-бота

Административный сценарий Data Cycle покрывается без браузера, Telegram token
и реальных HTTP-запросов. Тест вызывает bot handlers, направляет их запросы в
FastAPI через in-process ASGI transport и проверяет состояние в SQLite.

Запустить административный сценарий и регрессии старых команд:

```bash
uv run pytest -q tests/test_bot_admin_control.py tests/test_bot_notifications.py tests/test_bot_commands.py tests/test_bot_status.py tests/test_bot_light_refresh_path.py
```

Календарь и пользовательские команды проверяются отдельно:

```bash
uv run pytest -q tests/test_bot_calendar_integration.py tests/test_bot_predict_format.py
```

Для администратора меню содержит `/cycle`, `/cycle_time HH:MM`,
`/cycle_interval N`, `/cycle_history` и `/refresh`. `/refresh` — совместимая
команда ручного NHL Data Cycle; старый вызов Airflow больше не используется.
Публичный `/help` показывает административные команды только пользователю,
который указан в `bot.admin_user_ids`.

Control API credential задаётся путём `BOT_CONTROL_API_KEY_FILE`. Бот и API
читают отдельный secret file с одним значением; его содержимое не задаётся в
конфигурации, документации или логах. Production Compose передаёт этот секрет
боту только для внутренних `/admin` routes. Пустой или недоступный файл
отключает административные API-действия и не блокирует публичный календарь.

Тесты используют фиктивный файл credential и allowlist Telegram ID. Они
проверяют optimistic update расписания, отключение автоматического цикла,
историю, callback idempotency, alias `/refresh` и запрет control-вызова для
неадминистратора. Bot-side formatter и poller проверяются с fake API и Telegram
transport. Poller использует `POST /admin/notifications/claim`, затем отправляет
короткий HTML итог по alias и вызывает `/ack`; при ошибке отправки вызывает `/retry`.
Тест `test_asgi_outbox_response_reaches_fake_telegram_and_is_acked` проходит от
реального ASGI ответа и SQLite outbox до fake Telegram send и проверки доставленного
статуса. Repository tests покрывают транзакционный producer, lease expiry, fencing,
backoff и recovery.

PostgreSQL race/grants tests запускаются при заданных `SF_TEST_POSTGRES_URL`,
`SF_TEST_CONTROL_DATABASE_URL`, `SF_TEST_API_READER_DATABASE_URL` и
`SF_TEST_REFRESH_WRITER_DATABASE_URL`. Независимый PostgreSQL 16 gate применил
миграции до 0017 под NOSUPERUSER `sf_migrator` и прошёл runtime-role/race suite
(33 tests passed). Production Compose требует непустой
`SF_DATA_CYCLE_NOTIFICATION_ALIASES` и файл `BOT_NOTIFICATION_DESTINATIONS_FILE`;
ключи JSON должны совпадать с alias allowlist. Отсутствие mapping или точного
совпадения блокирует activation по [TASK-025-9](../backlog/tasks/TASK-025-9-release-readiness.md).

При включённом `BOT_CONTROL_API_KEY_FILE` poller требует непустую маршрутизацию.
`BOT_NOTIFICATION_DESTINATIONS_FILE` указывает на runtime JSON object вида
`{"nhl_admins":-1001234567890}`; один alias задаёт ровно один chat ID, несколько
получателей настраиваются разными aliases. Файл монтируется только в Telegram bot.
В БД передаётся alias, реальные Telegram chat IDs остаются только в bot config.
Пустой или неизвестный alias не подтверждается и не отправляется; lease должен
позволить повторную обработку после исправления конфигурации.
