# TASK-040-3 — Локальная выдача 1X2 на реальном upcoming

> **Статус:** done
> **Инициатива:** [EPIC-040](../EPIC-040-club-football-platform-e2e.md)
> **Требование:** [REQ-040](../../product/requirements/REQ-040-club-football-platform-e2e.md)
> **Решение:** [ADR-040](../../architecture/adr/ADR-040-club-football-1x2-e2e.md)

## Результат

На свежем снимке реальных upcoming-событий Smart Tables обе shadow-стратегии
сохраняют полные вероятности 1X2 в отдельной локальной test DB. Локальные API и
бот возвращают тот же матч, три вероятности и имя стратегии. Production БД,
модельный pointer и получатели не затрагиваются.

## Контракт тестового входа

- `inference_long.parquet` и `inference_wide.parquet` создаются из одного
  снимка реального Smart Tables upcoming через текущие clean/feature stages.
- Рядом с каждым parquet находится `inference_{format}.snapshot.json` с
  `source: smart_tables`, `observed_at` в UTC и SHA-256 именно этого parquet.
- Вход имеет `status=upcoming`, пустой итоговый счёт и дату матча строго позже
  времени снимка и момента публикации. Снимок старше часа отклоняется.
- Файловая test DB разрешена только внутри `data/local_test/`; для изолированного
  теста допускается SQLite in-memory. Материализация вызывается с внешней
  сессией и `version=shadow`.

## Выполнено и проверено локально

- Две стратегии materialize используют разные артефакты, `model_version` и
  `source_namespace=local_test/{strategy}`; отрицательный остаток конкретного
  long-матча отправляется в карантин до публикации.
- Тест с реальной SQLite проверяет две записи одного матча, чтение `/predict/upcoming/football_top_leagues`
  и формат П1/Х/П2 для обеих моделей. Для клуба бот использует
  `market=winner`, `market_spec=winner_1x2`, без live Pinnacle. Команда
  `/club_test` отключена по умолчанию (`bot.club_test_enabled: false`), горизонт
  чтения равен 168 часам (`bot.club_test_hours`).
- Проверены отказ для SQLite вне `data/local_test`, старого upcoming и вызова
  общего `predict_single` для 1X2.
- Рабочий маршрут источника — `https://smart-tables.ru/api/v1`. Хост
  `backend.smart-tables.ru` из текущей сети не завершает TLS, но API на том же
  домене, что и сайт, отвечает. `match-center` имеет собственные ID; они
  сохраняются с префиксом `mc:`. ISO-время приводится к UTC-формату исторического
  CSV до clean.
- 2026-10-12 получены 89 реальных upcoming: ENG1 10, SPA1 10, GER1 10, ITA1 9,
  FRA1 10, RUS1 10, RUS2 10, UCL 10, UEL 10. Полный изолированный запуск
  `scripts/club_football_e2e.py --use-snapshot` построил 178 long и 89 wide
  inference-строк, сохранил по 89 прогнозов каждой модели, 0 отрицательных
  остатков. Повторный запуск оставил ровно 178 активных записей. API вернул
  168 записей в семидневном окне; обработчик `/club_test` вывел обе стратегии,
  П1/Х/П2 в локальный `data/local_test/bot_preview.txt`.
- Исторический source не изменён: SHA-256
  `799cd61405e8d9ffb7aee8ac078fcbce9abefda3c2c3450c26a2c22b21407975`.
- Одно тестовое сообщение с явной пометкой доставлено через Telegram Bot API
  единственному разрешённому пользователю из локального `.env`:
  HTTP 200, `ok=true`, `message_id=172`. Токен и chat ID не сохранялись в
  артефактах и логах. Это проверка транспорта, а не включение регулярной выдачи.

## Граница проверки

Локальный bot handler вызван с тестовым ASGI API и отдельной SQLite DB; затем
его готовый текст один раз доставлен через Telegram. Polling действующего бота,
production DB, расписание и модельный pointer не менялись.

Чтобы повторить со свежим источником: `uv run python scripts/club_football_e2e.py`.
Для повторного прогона уже полученного снимка в течение часа:
`uv run python scripts/club_football_e2e.py --use-snapshot`.
