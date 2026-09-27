# TASK-025-4 — Настраиваемый цикл и ручной запуск из Telegram

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

Control API хранит настройки NHL pipeline, включает/отключает автоматический
цикл и принимает ручной Data Cycle. Бот вызывает закрытый API с отдельным
service credential и allowlisted Telegram principal. Bot UI реализуется в
TASK-025-5. API и bot не получают host, Docker или прямые DB права; фиксированный
host dispatcher запускает только установленный pipeline с принятым UUID.

## Критерии приёмки

- [x] Настройки связаны с pipeline, переживают рестарт и содержат основное
  время, IANA zone, интервал повтора, enabled и revision. Интервал считается
  от основного времени; конфликтующее значение отвергается.
- [x] Только администратор с проверенным Telegram ID через внутренний
  authenticated API меняет schedule и запускает цикл; public ingress не
  маршрутизирует control routes, API DB роль ограничена control state.
- [x] Тот же authenticated control API безопасно отдаёт текущий и последние
  run из query/DTO TASK-025-7. Отдельный service credential из `*_FILE` и
  допустимый admin principal обязательны и для чтения; пустая конфигурация
  запрещает доступ. `sf_api_reader` не получает SELECT к control history.
- [x] Повтор того же update/callback идемпотентен; при active run новый цикл
  не возникает, возвращаются run ID/start/stage. Новый осознанный запуск
  после ошибки получает новый run ID.
- [x] Scheduled и manual используют один durable run/claim; systemd dispatcher
  не принимает команд, путей или Hydra overrides из Telegram. Остановка
  dispatcher видна как просрочка heartbeat.
- [x] Ручной запуск при auto off работает и не смещает расписание; missed
  slots/catch-up не создают неограниченную очередь.
- [x] Негативные auth/grants и PostgreSQL concurrency tests проходят.

## План реализации

1. **Red:** новые schedule unit tests падали при отсутствующей библиотеке; auth,
   API и race tests добавлены на границах handler, Postgres и DB grants.
2. **Green:** persistent schedule, закрытые routes, waiting-run reservation,
   due-slot coalescing и fixed systemd bridge реализованы.
3. **Refactor:** отдельная `sf_control_api` identity, column-level INSERT без
   lifecycle status, public ingress deny, rollback и timer handoff документированы.

## Затрагиваемые области и зависимости

- После TASK-025-3/7. Bot UI остаётся в TASK-025-5; recovery/fencing `running`
  run остаётся в TASK-025-8. Фактическое включение на VPS — release gate.
- Интервалы ограничены `4, 6, 8, 12, 24` часами и делят 24; production default
  `24h`. До выбора меньшего интервала Operations измеряет длительность цикла и
  квоты. Во время длинного цикла due slot пропускается с учётом `last_missed_slots`,
  поэтому очередь и параллельный run не появляются.

## Проверка

- `uv run pytest -q tests/test_data_cycle_schedule.py tests/test_admin_control_api.py`
- `SF_TEST_POSTGRES_URL=<disposable PostgreSQL URL> uv run pytest -q tests/test_data_cycle_schedule.py::test_postgresql_serializes_due_dispatch_and_manual_idempotency`
- `SF_TEST_CONTROL_DATABASE_URL` и `SF_TEST_API_READER_DATABASE_URL` на disposable
  runtime roles: `uv run pytest -q tests/test_runtime_db_role_privileges.py`
- Migration idempotency/SQLite, `systemd-analyze verify`, Compose topology и Ops preflight.

## Handoff и отчёт

- Отчёт выполнения: [TASK-025-4](../../changes/done/TASK-025-4-schedule-control.md).
- Follow-up / findings: замечания по Compose environment и terminal replay
  исправлены; recovery/fencing остаётся в TASK-025-8.
- Review: повторное независимое review пройдено без P0–P2.
- Commit/push: см. память EPIC-025.
