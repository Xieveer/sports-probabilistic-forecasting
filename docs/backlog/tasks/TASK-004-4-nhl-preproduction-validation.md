# TASK-004-4 — Предпроизводственная проверка NHL и handoff 1.0.0

> **Статус:** done
> **Владелец:** devops-reviewer
> **Эпик:** [EPIC-004](../EPIC-004-nhl-release-readiness.md)
> **Требование:** [REQ-004](../../product/requirements/REQ-004-nhl-readiness-and-release-versioning.md)
> **ADR:** [ADR-004](../../architecture/adr/ADR-004-release-version-and-odds-api-key-failover.md)

## Результат и границы

После готовности кода выполнить разрешённый владельцем NHL pre-production run
с secret environment, сохранить обезличенный отчёт и заполнить production
handoff для `1.0.0`. Не создавать Git-тег, не публиковать образы и не выполнять
deployment без нового явного разрешения.

## Критерии приёмки

- [x] Отчёт перечисляет фактически полученные завершённые NHL-матчи, статус
  historical odds и наличие/отсутствие будущего расписания без секретов.
- [x] При опубликованном и валидном расписании доказана materialization
  прогнозов; при его отсутствии зафиксирован штатный статус.
- [x] `docs/operations/production-handoff.md` заполнен со статусом `candidate`,
  а `make production-check` фактически выполнен.
- [x] В отчёте указано, что Git-tag, image push и deployment не выполнялись,
  либо на них дано отдельное разрешение владельца.

## План реализации

1. Перед run проверить доступность секретов и лимиты без их вывода; при их
   отсутствии зафиксировать blocker, не подставлять тестовые ключи.
2. Выполнить readiness-команду, собрать только безопасное доказательство и
   проверить version/tag/image plan.
3. Заполнить handoff, запустить production-check и передать результат владельцу
   для решения о фактическом release/deploy.

## Затрагиваемые области и зависимости

- Secret runtime environment, NHL/ODDS API, `docs/operations/production-handoff.md`,
  release/deploy documentation.
- Зависит от [TASK-004-1](TASK-004-1-release-version-contract.md) и
  [TASK-004-3](TASK-004-3-nhl-readiness-command.md).

## Проверка

- Фактическая readiness-команда и `make production-check`; результаты указаны
  буквально в done-отчёте.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-004-4-nhl-preproduction-validation.md`.
- Follow-up / findings: решение владельца о release-tag/image push/deployment.
