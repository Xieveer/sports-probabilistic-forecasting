# TASK-014-2 — Полный каталог NHL Web API

> **Статус:** in_progress
> **Владелец:** data-researcher
> **Эпик:** [EPIC-014](../EPIC-014-research-api-catalog.md)
> **Требование:** [REQ-014](../../product/requirements/REQ-014-research-api-catalog.md)
> **ADR:** [ADR-014](../../architecture/adr/ADR-014-versioned-api-catalog-contract.md)

## Результат и границы

Создать complete-card и Markdown data dictionary публично наблюдаемого NHL Web API
`api-web.nhle.com/v1`: методы, параметры, сущности, поля, ключи, temporal availability,
coverage и ограничения. Список ограничен методами, которые подтверждены read-only
наблюдением либо явно обозначены как недоступные; он не утверждает неизвестный закрытый
surface API. Ingest и массовый сбор не меняются.

## Критерии приёмки

- [ ] Карточка `nhl-web-api` проходит `DataSourceRecord` validation как `complete`.
- [ ] Markdown dictionary включает все подтверждённые методы и field-level таблицы для
  матчей, команд, составов, игроков, boxscore и play-by-play.
- [ ] Для каждого поля указан допустимый момент применения; post-event/live поля явно
  исключены из pre-match feature без timestamped snapshot.
- [ ] Дата, источник доказательства, access/rate-limit и неизвестные методы/поля помечены
  без raw payload и секретов.

## План реализации

1. Сверить локальную исходную разведку, public документацию и безопасные live GET-наблюдения.
2. Составить endpoint/field records, проверить JSON-card контрактом.
3. Синхронизировать human-readable dictionary и каноническую NHL-документацию.

## Затрагиваемые области и зависимости

- `docs/research/`, `docs/cursor/source_data/nhl_web_api.md`, Research workspace card.
- Внешний неофициальный API; доступ проверяется только законными GET без обхода ограничений.

## Проверка

- Contract validation карточки.
- Read-only evidence на указанную дату либо явная фиксация недоступности.
- `make docs`.

## Текущее доказательство и продолжение

Карточка `docs/research/catalogs/nhl-web-api.json` имеет `catalog_completeness=complete`,
18 observed endpoint patterns и 1 105 leaf-level field records. `catalog_scope` фиксирует
границу как все scalar-поля 18 перечисленных patterns, а не неизвестный внутренний NHL surface.
Для field records указаны JSON path, тип, units/domain, structured evidence, применение,
temporal availability и leakage-risk; 176 временно неоднозначных UI/media полей остаются
явно `unknown`, без разрешения использовать их как feature. Синхронный dictionary:
`docs/research/nhl-web-api-catalog.md`.

Перед закрытием: создать done-отчёт с фактически выполненными проверками и передать полный
diff независимому reviewer; не менять статус до его чистого результата.

## Handoff и отчёт

- Отчёт выполнения: создаётся в `docs/changes/done/` после зелёных проверок.
- Follow-up / findings: TASK-014-3 Smart Tables.
- Review: требуется независимый review после реализации.
- Commit/push: заполняет reviewer отдельным evidence-коммитом.
