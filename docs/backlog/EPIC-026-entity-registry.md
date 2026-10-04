# EPIC-026 — Единые идентификаторы спортивных сущностей

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-026](../product/requirements/REQ-026-entity-registry.md) (`confirmed`)
> **ADR:** [ADR-027](../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md) (`accepted`)

## Память Product Owner

- Инициатива: `EPIC-026`.
- Ветка инициативы: `initiative/epic-026-entity-registry`.
- Workflow / этап: `engineering / TASK-026-3`; [REQ-026](../product/requirements/REQ-026-entity-registry.md) подтверждён, [ADR-027](../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md) принят после независимого review; TASK-026-1 и TASK-026-2 прошли независимое review.
- Исходная цель: проектные ID и имена сущностей отделены от названий и ID источников; процесс применим к сотням турниров, локальный registry обслуживает загрузку истории и обучение.
- Критерии и DoD: подтверждённые критерии 1–11 в [REQ-026](../product/requirements/REQ-026-entity-registry.md), затем TASK review, полное EPIC review и terminal CI.
- Релиз: production-развёртывание не запрошено.
- Выполнено: подтверждён REQ и создана ветка; TASK-026-1 реализовал локальный source-neutral registry (51 целевой тест), TASK-026-2 — локальную веб-очередь с аудитом и пакетными решениями (58 тестов); оба среза прошли независимое review.
- Решения: собственные ID и имена проекта; переименование сохраняет ID; неочевидные связи владелец подтверждает на локальной веб-странице с поиском и пакетными действиями; сервер читает опубликованный через существующий Object Storage снимок и передаёт новые кандидаты локально без собственного подтверждения. Registry применим к сотням турниров и будущим игрокам. Версионированная связь с `canonical_events.id` определена в ADR-027.
- Артефакты: [REQ-026](../product/requirements/REQ-026-entity-registry.md), [ADR-027](../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md), [TASK-026-1](tasks/TASK-026-1-source-neutral-entity-registry.md), [ADR-026 календаря](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md), [долгосрочный план](index.md#долгосрочные-инициативы-платформы), [EPIC-003](EPIC-003-scalable-multisport-platform.md), [EPIC-025](EPIC-025-bot-schedule-readiness.md).
- Предыдущая роль: Reviewer — TASK-026-2 без P0–P2, независимые проверки пройдены.
- Следующая роль: Developer — выполнить [TASK-026-3](tasks/TASK-026-3-event-identity-bridge.md) через red → green → refactor.
- Открытые вопросы: provider contract probe и параметры нагрузки остаются gates будущих TASK; первый локальный срез ими не блокируется.
- Research: не применяется.
- Обновлено: 2026-10-04.

## Цель и границы

Сопоставлять участников, турниры и события поддерживаемых источников с
собственными стабильными ID и редактируемыми именами проекта. Первый реальный
пример — NHL API и The Odds API, но механизм и процесс проверки не зависят от
конкретного турнира. Будущие игроки имеют независимую идентичность и внешние
обозначения; player-прогнозы и сбор составов остаются отдельной инициативой.

## Проверяемый результат

Точные критерии подтверждены в [REQ-026](../product/requirements/REQ-026-entity-registry.md).
Проверяемые сценарии:

1. Собственные ID и имена турнира, команды и события не меняются от переименования;
   `COL` и `Colorado Avalanche` указывают на одну проектную команду.
2. Неочевидная связь ждёт решения владельца в локальной веб-очереди с поиском
   и пакетными действиями; решение сохраняется и применяется повторно.
3. Та же процедура работает на контрольном втором турнире без Python-правок
   под его конкретные названия и ID.
4. Существующий NHL-календарь и прогнозная выдача остаются доступны на прежних
   входах; идентичность будущих игроков предусмотрена без запуска player-прогнозов.
5. Полный registry ведётся локально; версия фиксируется рядом с локальными
   данными и результатом обучения, сервер читает опубликованный снимок.

## Зависимости и следующий gate

Основа для [EPIC-027](EPIC-027-historical-odds.md), [EPIC-029](EPIC-029-configured-tournament-onboarding.md) и [EPIC-031](EPIC-031-real-bets-ledger.md). Подтверждённый REQ и принятое архитектурное решение задают границы следующих срезов.

## Декомпозиция и доказательства

| TASK | Результат и критерии REQ-026 | Проверка | Статус |
|---|---|---|---|
| [026-1](tasks/TASK-026-1-source-neutral-entity-registry.md) | Локальные ID, имена, обозначения и игроки; 1, 2, 7, 8 | SQLite/домен, NHL и второй турнир | done |
| [026-2](tasks/TASK-026-2-local-review-ui.md) | Локальная очередь и решения; 3 | HTTP/DB, пакет и security | done |
| [026-3](tasks/TASK-026-3-event-identity-bridge.md) | Проектные события, bridge, совместимость; 1, 4, 6 | повторные матчи, перенос и pinned mapping | backlog |
| [026-4](tasks/TASK-026-4-local-registry-snapshot.md) | Полный снимок и provenance; 8, 9 | проверка снимка и offline training | backlog |
| [026-5](tasks/TASK-026-5-registry-publication.md) | Object Storage и серверная версия; 9, 11 | fault tests, contract probe и DB activation | backlog |
| [026-6](tasks/TASK-026-6-registry-candidate-feedback.md) | Обратная очередь и полный цикл; 4, 5, 10 | end-to-end NHL и второй турнир | backlog |

Следующий gate — реализация и review [TASK-026-3](tasks/TASK-026-3-event-identity-bridge.md).

## Риски и rollout

Существующие строковые имена и source ID нельзя заменять без проверенного backfill; переход должен быть аддитивным. Production-переключение — отдельное решение.
