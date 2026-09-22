# TASK-021-1 — Контракт данных клубного футбольного пула

> **Статус:** in_progress
> **Владелец:** implementer
> **Эпик:** [EPIC-021](../EPIC-021-football-1x2-research.md)
> **Требование:** [REQ-021](../../product/requirements/REQ-021-top-football-winner-baseline.md)
> **ADR:** [ADR-021](../../architecture/adr/ADR-021-football-1x2-research-pool.md)

## Результат и границы

Добавить минимальный изолированный ingest/clean contract `football_top_leagues` для девяти
competition codes. Данная задача не запускает полный network backfill, не строит features,
не обучает модель и не меняет betting policy.

## Критерии приёмки

- [ ] Конфигурация содержит только ENG1, SPA1, GER1, ITA1, FRA1, RUS1, RUS2, UCL и UEL,
  с `national_teams_only=false` и отдельными путями артефактов.
- [ ] Fixture-based ingest → clean создаёт валидный interim без затрагивания
  `football_nationals`.
- [ ] Документация перечисляет raw/interim поля, temporal class, clean rule и caveat odds.
- [ ] Поведение покрыто red/green тестом; выполнены релевантные unit, lint и mypy checks.

## План реализации

1. Добавить сначала падающий тест загрузки pool-конфига и fixture ingest/clean smoke.
2. Добавить source/tournament config и минимальное расширение provider только если test
   докажет необходимость.
3. Запустить тесты и задокументировать field contract.

## Риски и rollback

Источник неофициальный, а полная история будет загружаться позднее. Откат — удалить только
новые configs/tests; никаких существующих data artefacts эта задача не меняет.
