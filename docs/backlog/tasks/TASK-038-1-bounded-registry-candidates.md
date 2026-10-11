# TASK-038-1 — Ограничить календарную очередь кандидатов

> **Статус:** done — ожидает независимый review и terminal CI
> **Эпик:** [EPIC-038](../EPIC-038-v1-3-6-candidate-scope.md)
> **Тип:** дефект production gate
> **Ветка:** `initiative/epic-038-v1-3-6-candidate-scope`

## Проблема

Strict Data Cycle v1.3.5 создал 22 656 pending candidates при календарном проходе 22 581 исторического события: 21 963 event ID и 693 команды, в основном исторические. Это блокирует feedback и делает ежедневный owner review непригодным.

## Критерии

- NHL календарь проверяет неизвестные словарные обозначения только в UTC окне от суток назад до 30 дней вперёд, совпадающем с текущим provider и odds batch horizon.
- Отсутствие постоянной owner-связи события само по себе не создаёт кандидата. Конфликт уже подтверждённой связи остаётся проверяемым.
- Тест red→green проверяет исторические и актуальные строки, конфликт и стабильный idempotency key при повторном наблюдении. Никаких миграций, изменений matcher/market/model/snapshot.
- Независимый review, CI/Security, новый immutable tag и полный production feedback/forecast gate обязательны.

## Передача

Developer фиксирует [отчёт done](../../changes/done/TASK-038-1-bounded-registry-candidates.md); Product Owner после review и CI ведёт релиз до серверного GO.

## Результат Developer

Код и red/green тесты готовы; локальные результаты и границы приведены в [отчёте done](../../changes/done/TASK-038-1-bounded-registry-candidates.md). Серверные gates остаются открытыми.
