# TASK-025-5 — Управление циклом в Telegram и уведомления

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

После публичного календаря TASK-025-11 администратор видит настройки,
состояние и историю Data Cycle через control API, меняет расписание и получает
итоги запусков. Публичный бот остаётся NHL-only в `1.2.0`.

## Критерии приёмки

- [x] Публичный календарь TASK-025-11 остаётся доступен при ошибке или
  отключении административного control API.
- [x] Администратор видит enabled, время/зону/интервал, следующий и прошлый
  запуск, текущий этап, историю и числовое покрытие; может изменить допустимые
  настройки и запросить новый цикл. Повтор callback идемпотентен, активный
  `run_id` показан без запуска дубля.
- [x] После ручного запуска бот сообщает принятие с `run_id`, затем итог;
  после планового отправляет один компактный итог. `partial_success` и `failed`
  обозначены явно. Обычный повтор запроса и retry не создают дублирующих
  сообщений. При аварии между Telegram send и записью ack возможна повторная
  доставка с тем же `run_id` согласно at-least-once контракту ADR-026.
- [x] Неадминистратор не видит административные действия и не может вызвать
  control API через подмену callback. Существующие команды прогнозов остаются
  работоспособными по своему контракту.
- [x] Кодовый сценарий admin Telegram handler → authenticated control API →
  persisted schedule/run/history и notification outbox проходит локально и в
  CI без браузера, production token и production-запросов.

## План реализации

1. [x] Red: тесты Telegram ID, дубля callback, истории и результата run;
   первый запуск нового E2E завершился ожидаемым отсутствием `/cycle` handler.
2. [x] Bot-only green: административные handlers и клиент ограниченного
   authenticated control API; callback и legacy `/refresh` запускают цикл
   идемпотентно. Кодовый E2E проверяет persisted schedule/run/history.
3. [x] Refactor: русские подписи состояний, admin-only help/menu и руководство
   локальной проверкой бота.
4. [x] Bot-only terminal notification formatter/poller и fake transport tests:
   lease claim → alias routing → Telegram send → ack/retry; неизвестный alias
   не подтверждается, при send→ack crash повтор узнаётся по `run_id`.
5. [x] Durable outbox producer, migration и authenticated claim/ack/retry API:
   terminal producer пишет по одной записи на safe alias в транзакции завершения;
   claim использует lease/attempt/backoff; bot mapping содержит ровно один chat ID
   на alias и монтируется только в bot. SQLite/ASGI→fake Telegram E2E и migration
   checks проходят. Disposable PostgreSQL 16 gate прошёл: Alembic upgrade до
   0017 выполнен ролью NOSUPERUSER `sf_migrator`, runtime grants применены;
   lease race и runtime-role suite — 33 passed.

## Зависимости и проверка

- Зависит от TASK-025-4/7/10/11. Доставка уведомлений использует результаты и
  outbox Data Cycle, без прямого управления службами из процесса бота.
- Целевые unit/ASGI/bot integration tests с fake clock и fake Telegram
  transport; регрессия старых команд; lint.
- Bot-only проверки и runtime alias file описаны в
  [руководстве локальной проверки](../../development/telegram-admin-testing.md).

## Handoff и отчёт

- Отчёт выполнения: [TASK-025-5 outbox](../../changes/done/TASK-025-5-telegram-admin-outbox.md).
- Review: независимый Reviewer подтвердил отсутствие findings P0–P2.
- Release evidence: `make test` — 1202 passed, 5 gated skips; `make lint`,
  `make docs` (24 warnings), `make production-check`, `make security` и
  `make ai-validate` прошли. Подробности и ограничения доставки — в отчёте done.
- Commit/push: TASK5-owned files коммитятся отдельно; production deployment
  требует выполнения alias mapping и остальных production gates из
  [TASK-025-9](TASK-025-9-release-readiness.md).
