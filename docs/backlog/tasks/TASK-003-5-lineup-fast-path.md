# TASK-003-5 — Быстрый контур подтверждённых составов

> **Статус:** backlog
> **Владелец:** implementer
> **Эпик:** [EPIC-003](../EPIC-003-scalable-multisport-platform.md)
> **Требование:** [REQ-003](../../product/requirements/REQ-003-scalable-multisport-platform.md)
> **ADR:** [ADR-003](../../architecture/adr/ADR-003-configured-multisport-portfolio.md)

## Результат и границы

Реализовать версионирование прогнозов по состоянию состава и отдельный fast
path для подтверждённого стартового состава: DB-first inference одного матча,
затем идемпотентная Telegram-доставка. Не выбирать реального поставщика
составов и не выполнять тяжёлое переобучение.

## Критерии приёмки

- [ ] Версия хранит состояние состава, источник, время получения, model pool и
  model version.
- [ ] Повтор того же confirmed-lineup event не создаёт новую версию или
  дублирующее уведомление.
- [ ] Отсутствие/неполнота confirmed состава не инициирует fast path; после
  успешной DB записи сбой Telegram приводит к повтору доставки без пересчёта.
- [ ] Интеграционная проверка с локальным адаптером подтверждает путь в пределах
  одной минуты.

## План реализации

1. Написать падающие DB/idempotency/delivery contract-тесты.
2. Добавить аддитивные модели данных, event contract и single-match inference.
3. Реализовать outbox/retry семантику Telegram и observability без секретов.
4. Запустить целевые integration tests и `make test-unit`.

## Затрагиваемые области и зависимости

- service DB/repository, materialize/inference, orchestration, Telegram adapter,
  migrations, tests и docs.
- Требует TASK-003-3 и TASK-003-4; внешний lineup provider — отдельная задача.

## Проверка

- DB, single-match inference, outbox и latency integration tests.
- `make test-unit`.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-003-5-lineup-fast-path.md`.
- Follow-up / findings: выбрать поставщика составов отдельным REQ/TASK.
