# TASK-026-12 — Словари рынков и исходов

> **Статус:** done
> **Эпик:** [EPIC-026](../EPIC-026-entity-registry.md)
> **Требование:** [REQ-026 #1, #4, #12](../../product/requirements/REQ-026-entity-registry.md)
> **Решение:** [ADR-035](../../architecture/adr/ADR-035-registry-dictionaries-and-derived-event-matching.md)

## Результат

Добавить к локальному registry generic ID рынков и исходов, scoped aliases источника,
явные правила NHL/Pinnacle h2h → winner_withOT и редактирование правил из локального
веб-каталога. Выпуск snapshot формата v2 должен читать уже установленный формат v1;
rollback сохраняет старый verified snapshot и выполняется публикацией его новых sequence.

## Критерии

1. Схема registry 11→12 добавляет market/outcome и typed market rules, сохраняя все
   ранее существовавшие сущности, обозначения и foreign keys.
2. Однозначный `the_odds_api:h2h` при `sport=ice_hockey`, подтверждённом NHL tournament ID
   и `bookmaker=pinnacle` разрешается в проектный market `winner_withOT`; другой bookmaker
   остаётся unresolved.
3. Правило хранит период, overtime, shootout, draw, UUID допустимых outcome и их
   неизменяемые семантические ключи `home_win`/`away_win`/`draw`. Для первого среза
   NHL/Pinnacle допустимы только `home_win` и `away_win`, ничья исключена.
4. Правки правил требуют основания, пишут immutable audit и используют revision CAS.
   Повтор NHL seed идемпотентен и не затирает решение владельца.
5. Локальная веб-страница показывает scoped market aliases и активные правила; владелец
   может изменить набор исходов и правила с CSRF, loopback, audit и stale-revision защитой.
6. Новый code читает format v1/schema 11 без новых правил и format v2/schema 12 с ними;
   публикация, download, cache verification и установка поддерживают оба формата.
   Rollback на v1 snapshot проходит через новую publication sequence до старого бинарника.
7. Нет удаления или переписывания старых event rows и immutable snapshot packages.

## План

1. Зафиксировать red тесты для правил рынка, revision/audit, UI, migration и snapshot v1/v2.
2. Добавить schema 12, seed NHL/Pinnacle и snapshot v2 совместимый с v1.
3. Добавить просмотр и аудитную правку рынка в локальном каталоге.
4. Проверить v1/v2 publication, download, installation и targeted suites; передать на review.

## Состояние

- Ветка: `initiative/epic-026-entity-registry`.
- Реализация и прямые тесты завершены; evidence и фактические команды приведены в
  [отчёте done](../../changes/done/TASK-026-12-market-outcome-dictionaries.md).
- Следующий gate: независимый review; затем matcher integration и release gates
  EPIC-026 выполняются владельцами соответствующих модулей.
