# EPIC-014 — Проверяемый каталог спортивных API для Research Mode

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-014](../product/requirements/REQ-014-research-api-catalog.md)
> **ADR:** [ADR-014](../architecture/adr/ADR-014-versioned-api-catalog-contract.md)

## Цель и границы

Сделать Data Source Catalog пригодным для науки: structured endpoint/field contract и две
проверенные карточки полного публично наблюдаемого API — Smart Tables football и NHL Web API.
Ingest, production-интеграция и обход ограничений не входят.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-014-1](tasks/TASK-014-1-api-catalog-contract.md) | Typed endpoint/field contract, validation и документация формата | ADR-014 | unit tests + docs | done |
| [TASK-014-2](tasks/TASK-014-2-nhl-api-catalog.md) | Полная verified NHL Web API card и dictionary | TASK-014-1 | contract validation + source review | in_progress |
| [TASK-014-3](tasks/TASK-014-3-smart-tables-api-catalog.md) | Полная verified Smart Tables card и dictionary | TASK-014-1 | contract validation + source review | in_progress |

## Риски и rollout

Каталог не подключён к сервису, поэтому rollout не требуется. Внешние неофициальные API могут
менять схему; риск снижают `last_verified`, уровень evidence и повторная верификация, но не
исключают. Откат — удалить новые complete-card из workspace, сохранив legacy `partial` cards.

## Полное EPIC review

Заполняется независимым reviewer после terminal-статусов всех TASK.
