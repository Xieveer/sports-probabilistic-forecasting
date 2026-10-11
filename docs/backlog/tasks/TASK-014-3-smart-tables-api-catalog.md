# TASK-014-3 — Полный каталог Smart Tables API

> **Статус:** done
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

- [x] Карточка `smart-tables-football-api` проходит `DataSourceRecord` validation как
  `complete`.
- [x] Markdown dictionary включает все подтверждённые методы и field-level таблицы для
  матчей, match center, турниров, команд/H2H, метаданных и odds-подмодуля.
- [x] Для каждого поля указан допустимый момент применения либо `unknown`; finished/live
  значения отделены от предматчевых features, а неизвестные не разрешены к применению.
- [x] Дата, доказательство, ToS/access/rate-limit и неизвестные/ACL-методы помечены без
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

Сверка 2026-10-11 исправила расхождение `match-center-card`: наблюдены
261 path/type records, у которых nullability неизвестна. Для 238 из них
описана помеченная интерпретация по имени и локальной разведке; смысл 23
полей match-center остаётся непрозрачным. У всех 261 полей match-center и
одного поля `match-card` machine `usage=unknown` до подтверждения
назначения и времени доступности. Read-only GET завершился тайм-аутом без ответа.
Владелец 2026-10-11 принял исследовательский результат с явным `unknown`;
эти поля не допускаются к моделированию без отдельной проверки.

Подготовленный diff проходит 54 целевых теста и Ruff; `make docs` собрал
документацию с 1 предупреждением. Промежуточное независимое review после
исправления P1/P2 не нашло новых блокирующих findings; до передачи результата
в `main` нужен terminal CI. Финальные review и CI фиксируются в EPIC.

## Handoff и отчёт

- Отчёт выполнения: [TASK-014-3](../../changes/done/TASK-014-3-smart-tables-api-catalog.md).
- Follow-up / findings: нет вне EPIC-014.
- Review: независимое review исправлений без P0–P2; итоговый gate указан в EPIC.
- Commit/push: проверенный diff `f262145e8e2f558b56d88681b00e2b7b0e11bcfe`;
  итоговая фиксация решения владельца и CI — в EPIC.
