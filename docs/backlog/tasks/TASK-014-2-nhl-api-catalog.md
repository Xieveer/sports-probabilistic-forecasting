# TASK-014-2 — Полный каталог NHL Web API

> **Статус:** done
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

- [x] Карточка `nhl-web-api` проходит `DataSourceRecord` validation как `complete`.
- [x] Markdown dictionary включает все подтверждённые методы и field-level таблицы для
  матчей, команд, составов, игроков, boxscore и play-by-play.
- [x] Для каждого поля указан допустимый момент применения либо `unknown`; post-event/live
  поля исключены из pre-match feature без timestamped snapshot, а неизвестные не разрешены.
- [x] Дата, источник доказательства, access/rate-limit и неизвестные методы/поля помечены
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
temporal availability и leakage-risk; у 183 полей момент доступности остаётся
`unknown`, без разрешения использовать их как предматчевую feature. Синхронный dictionary:
`docs/research/nhl-web-api-catalog.md`.

Проверка 2026-10-11 исправила temporal-метки счёта, итогов и gamecenter; пять
read-only NHL GET вернули HTTP 200 без сохранения payload. Поля
`specialEvent.parentId`, `waiversSequence` и два `goalInGame` остались без
подтверждённого смысла. Владелец 2026-10-11 принял исследовательский результат
с явным `unknown`; эти поля не допускаются к моделированию без отдельной проверки.

Подготовленный diff проходит 54 целевых теста и Ruff; `make docs` собрал
документацию с 1 предупреждением. Промежуточное независимое review
исправлений не нашло P0–P2. Финальные review и CI фиксируются в EPIC.

## Handoff и отчёт

- Отчёт выполнения: [TASK-014-2](../../changes/done/TASK-014-2-nhl-api-catalog.md).
- Follow-up / findings: TASK-014-3 Smart Tables.
- Review: независимое review исправлений без P0–P2; итоговый gate указан в EPIC.
- Commit/push: проверенный diff `f262145e8e2f558b56d88681b00e2b7b0e11bcfe`;
  итоговая фиксация решения владельца и CI — в EPIC.
