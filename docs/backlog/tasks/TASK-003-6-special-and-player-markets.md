# TASK-003-6 — Контракт статистических и player-рынков

> **Статус:** cancelled
> **Владелец:** implementer
> **Эпик:** [EPIC-003](../EPIC-003-scalable-multisport-platform.md)
> **Требование:** [REQ-003](../../product/requirements/REQ-003-scalable-multisport-platform.md)
> **ADR:** [ADR-003](../../architecture/adr/ADR-003-configured-multisport-portfolio.md)

## Результат и границы

Создать расширяемый контракт для NHL командного тотала бросков в створ,
командного тотала двухминутных удалений и player total набранных очков.
Точные линии и prematch odds mapping остаются отдельным dataset-specific
контрактом; задача не обещает запуск candidate без них.

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

## Причина отмены

Пользователь подтвердил список NHL-рынков 2026-08-09, но отложил их до
появления приоритета. Это отдельный будущий scope, поэтому задача не блокирует
закрытие EPIC-003. Для новой задачи остаются обязательными согласованные линии,
prematch odds mapping и нормализованный source contract для бросков в створ и
player points; реализация без них привела бы к неподтверждённым target и
leakage-правилам.

## Проверка

- Target/validation/training contract tests для выбранного рынка.
- `make test-unit`.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-003-6-special-and-player-markets.md`.
- Follow-up / findings: новые источники или признаки оформляются отдельной задачей.
