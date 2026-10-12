# TASK-040-3 — Локальная выдача 1X2 на реальном upcoming

> **Статус:** in_progress
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

## Осталось

1. Получить реальный upcoming Smart Tables для всего клубного пула с временем
   получения и доказательством принадлежности к источнику. С текущей сети API
   Smart Tables не отвечает до TLS handshake.
2. Создать из него оба inference-файла и sidecar по контракту выше; выполнить
   обе модели на фактических будущих матчах.
3. Поднять API и тестового бота с одной отдельной файловой test DB и проверить
   фактическую выдачу `/club_test`, повторный запуск и идемпотентность.

До этих пунктов fixture-test не считается завершённым E2E.
