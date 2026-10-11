# EPIC-026 — Единые идентификаторы спортивных сущностей

> **Статус:** blocked — REQ-026 #10 ждёт строгий server resolver и полный feedback цикл
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-026](../product/requirements/REQ-026-entity-registry.md) (`confirmed`)
> **ADR:** [ADR-029](../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md) (`accepted`)

## Память Product Owner

- Инициатива: `EPIC-026`.
- Ветка инициативы: `initiative/epic-026-entity-registry`.
- Workflow / этап: engineering и server installation gate [TASK-026-5](tasks/TASK-026-5-registry-publication.md) завершены; [REQ-026](../product/requirements/REQ-026-entity-registry.md) подтверждён, [ADR-029](../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md) принят. Остался production gate REQ-026 #10.
- Исходная цель: проектные ID и имена сущностей отделены от названий и ID источников; процесс применим к сотням турниров, локальный registry обслуживает загрузку истории и обучение.
- Критерии и DoD: подтверждённые критерии 1–11 в [REQ-026](../product/requirements/REQ-026-entity-registry.md), затем TASK review, полное EPIC review и terminal CI.
- Релиз: v1.3.1 развернут 2026-10-11; PostgreSQL grants, server credentials, publication/sync и расписание подтверждены. Критерий 11 проверен, но критерий 10 не завершён: строгий reader выключен, реальный кандидат и решение владельца ещё не прошли production цикл. EPIC остаётся `blocked` до отдельного решения о включении строгого режима.
- Выполнено: TASK-026-1…7 реализовали локальный registry/UI, resolver, snapshot/provenance, Object Storage publication, server projection/sync, обратную очередь и security remediation. Локальные NHL/EPL циклы и независимое review прошли; `make test` после интеграции — 1475 passed, 2 skipped. 2026-10-09 четыре отдельные Object Storage identities, CAS, IAM и lifecycle проверены на рабочем bucket. В v1.3.1 server gate TASK-026-5 прошёл: отдельные роли/grants, credentials, verified initial NHL snapshot, publication sequence 1, sync/zero-work feedback и первые плановые ticks. Строгий runtime reader не включён.
- Решения: собственные ID и имена проекта; переименование сохраняет ID; неочевидные связи владелец подтверждает на локальной веб-странице с поиском и пакетными действиями; сервер читает опубликованный через существующий Object Storage снимок и передаёт новые кандидаты локально без собственного подтверждения. Registry применим к сотням турниров и будущим игрокам. Версионированная связь с `canonical_events.id` определена в ADR-029.
- Артефакты: [REQ-026](../product/requirements/REQ-026-entity-registry.md), [ADR-029](../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md), [TASK-026-5](tasks/TASK-026-5-registry-publication.md), [локальный отчёт TASK-026-5](../changes/done/TASK-026-5-registry-publication.md), [runbook публикации](../operations/entity-registry-publication.md), [TASK-026-6](tasks/TASK-026-6-registry-candidate-feedback.md), [отчёт TASK-026-6](../changes/done/TASK-026-6-registry-candidate-feedback.md), [TASK-026-7](tasks/TASK-026-7-security-dependency-remediation.md), [отчёт TASK-026-7](../changes/done/TASK-026-7-security-dependency-remediation.md), [PR #61](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/61), [ADR-026 календаря](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md), [долгосрочный план](index.md#долгосрочные-инициативы-платформы), [EPIC-003](EPIC-003-scalable-multisport-platform.md), [EPIC-025](EPIC-025-bot-schedule-readiness.md). Эксплуатационные evidence и схема доступов: `operations-agent/docs/changes/2026-10-09-epic026-object-storage-access.md` и `operations-agent/docs/runbooks/sports-forecast-epic026-object-storage.md` в отдельном репозитории.
- Предыдущая роль: Operations Agent — server gate TASK-026-5 проверен при rollout v1.3.1; [ops evidence](https://github.com/Xieveer/operations-agent/pull/33) прошло независимое review без P0–P2 и слито.
- Следующая роль: Product Owner — принять отдельное решение о включении строгого server reader после проверки реального кандидатного цикла и защищённой копии локального master; Operations Agent — наблюдение и backup master.
- Открытые вопросы: непустая обратная очередь, локальное решение владельца и новая publication в production ещё не наблюдались. Strict reader остаётся выключенным, так что runtime продолжает legacy resolution. Локальный master из trusted NHL seed требует защищённой копии. В строгом режиме legacy merge historical odds в `source.csv` отключён до проверенного локального materialization по подтверждённым связям.
- Research: не применяется.
- Обновлено: 2026-10-11.

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
| [026-3](tasks/TASK-026-3-event-identity-bridge.md) | Проектные события, bridge, совместимость; 1, 4, 6 | повторные матчи, перенос и pinned mapping | done |
| [026-4](tasks/TASK-026-4-local-registry-snapshot.md) | Полный снимок и provenance; 8, 9 | проверка снимка и offline training | done |
| [026-5](tasks/TASK-026-5-registry-publication.md) | Object Storage и серверная версия; 9, 11 | fault tests, live contract probe и DB activation | done: v1.3.1 server gate |
| [026-6](tasks/TASK-026-6-registry-candidate-feedback.md) | Обратная очередь и полный цикл; 4, 5, 10 | end-to-end NHL и второй турнир | done |
| [026-7](tasks/TASK-026-7-security-dependency-remediation.md) | Исправленные версии Hydra и multidict для зелёного security gate | lock, аудит, unit-тесты, lint и review | done |

Object Storage endpoint, IAM и retention проверены на рабочем bucket.
Релиз v1.3.1 подтвердил PostgreSQL grants, первую публикацию, server sync,
zero-work feedback и первые плановые ticks. [TASK-026-5](tasks/TASK-026-5-registry-publication.md)
закрыт; весь EPIC остаётся `blocked` до строгого production reader и
непустого кандидатного цикла REQ-026 #10. Подробности — в
[ops evidence](https://github.com/Xieveer/operations-agent/pull/33).

## Риски и rollout

Существующие строковые имена и source ID нельзя заменять без проверенного backfill; переход должен быть аддитивным. Production-переключение — отдельное решение.
