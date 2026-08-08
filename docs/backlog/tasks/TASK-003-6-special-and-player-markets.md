# TASK-003-6 — Контракт статистических и player-рынков

> **Статус:** backlog
> **Владелец:** implementer
> **Эпик:** [EPIC-003](../EPIC-003-scalable-multisport-platform.md)
> **Требование:** [REQ-003](../../product/requirements/REQ-003-scalable-multisport-platform.md)
> **ADR:** [ADR-003](../../architecture/adr/ADR-003-configured-multisport-portfolio.md)

## Результат и границы

После одобрения футбольских winner и total создать расширяемый контракт для
статистических рынков и player-пропов. Первая реализация выбирается отдельным
подтверждённым dataset-specific scope; данная задача не обещает все рынки сразу.

## Критерии приёмки

- [ ] Новый market/spec описывается без турнирной ветви в платформенном коде и
  проходит общий validation, training-report и ручной promotion контур.
- [ ] Контракт разделяет team statistic и player statistic, их участника,
  единицу измерения, сторону, линию и доступность данных до матча.
- [ ] Невалидная статистика, leakage или отсутствие требуемого источника
  завершают конфигурационный запуск fail-fast.

## План реализации

1. После подтверждения конкретного первого рынка написать REQ и падающие
   contract-тесты его target/data schema.
2. Расширить market contract минимально для выбранного рынка и добавить
   sport-specific config/profile.
3. Проверить training/report/promotion на фикстуре и обновить руководство.

## Затрагиваемые области и зависимости

- market configs, targets, validation, feature/data contracts, training и tests.
- Блокер: одобрены football winner и total, определён источник исторических и
  prematch-данных конкретного рынка.

## Проверка

- Target/validation/training contract tests для выбранного рынка.
- `make test-unit`.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-003-6-special-and-player-markets.md`.
- Follow-up / findings: новые источники или признаки оформляются отдельной задачей.
