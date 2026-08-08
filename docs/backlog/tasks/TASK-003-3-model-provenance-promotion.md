# TASK-003-3 — Provenance и ручное promotion модельного пула

> **Статус:** backlog
> **Владелец:** implementer
> **Эпик:** [EPIC-003](../EPIC-003-scalable-multisport-platform.md)
> **Требование:** [REQ-003](../../product/requirements/REQ-003-scalable-multisport-platform.md)
> **ADR:** [ADR-003](../../architecture/adr/ADR-003-configured-multisport-portfolio.md)

## Результат и границы

Ввести immutable model identity для `model_pool/market_spec`, ручной promotion
из candidate в production и legacy manifest действующих NHL-артефактов. Витрина
сохраняет tournament как границу выдачи и добавляет provenance модели. Не
меняются расписания refresh и fast path составов.

## Критерии приёмки

- [ ] Production pointer меняется только явной командой/действием с ссылкой на
  отчёт кандидата; обучение его не меняет.
- [ ] Витрина различает tournament, model pool и immutable model version.
- [ ] Legacy NHL manifest загружает прежний артефакт и метаданные без
  переобучения; rollback возвращает прежний pointer без удаления артефактов.

## План реализации

1. Написать падающие contract-тесты для pointer, migration и legacy manifest.
2. Внести аддитивную миграцию schema, model registry contract и promotion CLI.
3. Добавить read-only NHL legacy manifest и документацию rollback.
4. Запустить миграционные/репозиторные тесты и `make test-unit`.

## Затрагиваемые области и зависимости

- `sports_forecast/deploy/`, `sports_forecast/materialize.py`, service DB,
  Alembic/миграции, `models/` metadata и tests.
- Требует TASK-003-1 и TASK-003-2; не удалять существующие NHL directories.

## Проверка

- DB migration, repository, materialize и promotion contract tests.
- `make test-unit`.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-003-3-model-provenance-promotion.md`.
- Follow-up / findings: TASK-003-4 и TASK-003-5 используют только production pointer.
