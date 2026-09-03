# TASK-014-3 — Полный каталог Smart Tables API

> **Статус:** in_progress
> **Владелец:** data-researcher
> **Эпик:** [EPIC-014](../EPIC-014-research-api-catalog.md)
> **Требование:** [REQ-014](../../product/requirements/REQ-014-research-api-catalog.md)
> **ADR:** [ADR-014](../../architecture/adr/ADR-014-versioned-api-catalog-contract.md)

## Результат и границы

Создать complete-card и Markdown data dictionary публично наблюдаемого футбольного backend
Smart Tables: методы, параметры, сущности, поля, ключи, temporal availability, coverage,
ограничения и доступ. Граница результата — методы, доказанные read-only наблюдением либо
локальной сохранённой разведкой; закрытые/недоступные методы не получают выдуманной схемы.
Ingest, массовый сбор и обход CAPTCHA/ACL не входят.

## Критерии приёмки

- [ ] Карточка `smart-tables-football-api` проходит `DataSourceRecord` validation как
  `complete`.
- [ ] Markdown dictionary включает все подтверждённые методы и field-level таблицы для
  матчей, match center, турниров, команд/H2H, метаданных и odds-подмодуля.
- [ ] Для каждого поля указан допустимый момент применения; finished/live значения явно
  отделены от предматчевых features.
- [ ] Дата, доказательство, ToS/access/rate-limit и неизвестные/ACL-методы помечены без
  raw payload, cookies, HAR и инструкций обхода ограничений.

## План реализации

1. Сверить локальную исходную разведку и безопасные public GET-наблюдения.
2. Составить endpoint/field records, проверить JSON-card контрактом.
3. Синхронизировать human-readable dictionary и каноническую Smart Tables-документацию.

## Затрагиваемые области и зависимости

- `docs/research/`, `docs/cursor/source_data/smart_tables.md`, Research workspace card.
- Внешний неофициальный API и ToS: проверка только законным read-only способом.

## Проверка

- Contract validation карточки.
- Read-only evidence на указанную дату либо явная фиксация недоступности.
- `make docs`.

## Текущее доказательство и продолжение

Карточка `docs/research/catalogs/smart-tables-football-api.json` имеет
`catalog_completeness=complete`, 7 endpoint'ов с безопасно наблюдённой схемой и 29
`unobserved`/`denied` endpoint'ов, перечисленных в `catalog_scope` как ограничения. В ней
367 field records, включая полный paths-only capture `match-center/{id}`; raw response после
извлечения путей и типов не сохранялся. Синхронный dictionary:
`docs/research/smart-tables-football-api-catalog.md`.

Следующий безопасный шаг — продолжать read-only schema capture только доступных методов,
переводя endpoint в `observed` лишь после полного field-level inventory. Перед закрытием
нужны done-отчёт, независимое review и отсутствие P0/P1/P2 findings.

## Handoff и отчёт

- Отчёт выполнения: создаётся в `docs/changes/done/` после зелёных проверок.
- Follow-up / findings: нет вне EPIC-014.
- Review: требуется независимый review после реализации.
- Commit/push: заполняет reviewer отдельным evidence-коммитом.
