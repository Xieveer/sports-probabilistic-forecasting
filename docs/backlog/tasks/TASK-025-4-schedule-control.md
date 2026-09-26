# TASK-025-4 — Настраиваемый цикл и ручной запуск из Telegram

> **Статус:** backlog
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

Администратор Telegram видит и меняет персистентное расписание NHL pipeline,
включает/отключает автоматический цикл и запрашивает ручной Data Cycle. Один
закрытый control API и dispatcher исполняют запросы без выдачи боту прав на
Docker, systemctl, БД или произвольные команды. Результаты каждого запуска
пишет TASK-025-3; это зависимость.

## Критерии приёмки

- [ ] Настройки связаны с pipeline, переживают рестарт и содержат основное
  время, IANA zone, интервал повтора, enabled и revision. Интервал считается
  от основного времени; конфликтующее значение отвергается.
- [ ] Только администратор с проверенным Telegram ID через внутренний
  authenticated API меняет schedule и запускает цикл; public ingress не
  маршрутизирует control routes, API DB роль ограничена control state.
- [ ] Повтор того же update/callback идемпотентен; при active run новый цикл
  не возникает, возвращаются run ID/start/stage. Новый осознанный запуск
  после ошибки получает новый run ID.
- [ ] Scheduled и manual используют один durable run/claim; systemd dispatcher
  не принимает команд, путей или Hydra overrides из Telegram. Остановка
  dispatcher видна как просрочка heartbeat.
- [ ] Ручной запуск при auto off работает и не смещает расписание; missed
  slots/catch-up не создают неограниченную очередь.
- [ ] Негативные auth/grants и PostgreSQL concurrency tests проходят.

## План реализации

1. Red: тесты persisted schedule, idempotency, concurrent claim и auth.
2. Green: control schema/API, bot handlers и bounded dispatcher adapter.
3. Refactor: согласовать status/ошибки, документировать rollout и rollback.

## Затрагиваемые области и зависимости

- После TASK-025-3. Сервисные роли и systemd template меняются совместно с
  Operations Agent; фактическое включение на VPS — release gate, не локальный тест.
- Allowlist интервалов выбирается по измеренной длительности цикла и квотам
  источников; нельзя позволять произвольный cron/shell из Telegram.

## Проверка

- Unit/ASGI/bot tests с fake clock и не-админом; disposable PostgreSQL race
  tests, migration/grants test; systemd dry-run и финальный Ops preflight.

## Handoff и отчёт

- Отчёт выполнения: ожидается в `docs/changes/done/`.
- Follow-up / findings: нет.
- Review: ожидается независимый Reviewer.
- Commit/push: ожидается после review.
