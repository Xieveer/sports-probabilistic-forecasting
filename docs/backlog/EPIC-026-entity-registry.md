# EPIC-026 — Единые идентификаторы спортивных сущностей

> **Статус:** blocked — актуальный owner master и NHL event-cycle; production gate #10 ждёт релизного окна
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-026](../product/requirements/REQ-026-entity-registry.md) (`confirmed`)
> **ADR:** [ADR-029](../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md) (`accepted`)

## Память Product Owner

- Инициатива: `EPIC-026`.
- Ветка инициативы: `initiative/epic-026-entity-registry`.
- Workflow / этап: инженерная ветка обновлена от `main` после PR #78; server installation gate [TASK-026-5](tasks/TASK-026-5-registry-publication.md) завершён. [TASK-026-8](tasks/TASK-026-8-local-registry-catalog.md) выполнен, локальная подготовка [TASK-026-9](tasks/TASK-026-9-legacy-yaml-cutover.md) прошла review и заблокирована до проверки актуального owner master и реального NHL цикла. [TASK-026-10](tasks/TASK-026-10-strict-reader-rollout.md) ожидает релизного окна.
- Исходная цель: проектные ID и имена сущностей отделены от названий и ID источников; процесс применим к сотням турниров, локальный registry обслуживает загрузку истории и обучение.
- Критерии и DoD: подтверждённые критерии 1–13 в [REQ-026](../product/requirements/REQ-026-entity-registry.md), затем TASK review, полное EPIC review и terminal CI.
- Релиз: v1.3.1 развернут 2026-10-11; PostgreSQL grants, server credentials, publication/sync и расписание подтверждены. Критерий 11 проверен, критерий 12 реализован локально. Strict reader выключен; реальный кандидат и решение владельца ещё не прошли production цикл (#10). Критерий 13 ожидает проверки на актуальном owner master и NHL event/forecast cycle; до этого legacy путь остаётся доступен при выключенном strict режиме.
- Выполнено: TASK-026-1…7 реализовали базовый registry, resolver, snapshot/publication, обратную очередь и security remediation; v1.3.1 закрыл server installation gate. TASK-026-8 добавил веб-каталог и правки с audit/revision; независимое review чистое. TASK-026-9 подготовил строгий путь без чтения YAML, проверку паритета и synthetic NHL feedback цикл; staging master/snapshot v1.3.1 содержит 33 команды, 100 командных обозначений и ноль событий, сверка обозначений прошла без расхождений. Локально: 1652 unit-теста passed, `make lint`, `make docs` и `make ai-validate` passed. Строгий runtime reader не включён.
- Решения: собственные ID и имена проекта; переименование сохраняет ID; владелец просматривает и редактирует текущие сущности/обозначения через локальный веб-интерфейс, там же подтверждает новых кандидатов. Сервер читает опубликованный через Object Storage снимок и передаёт новые кандидаты локально без собственного подтверждения. `conf/bookmaker/team_name_registry/nhl.yaml` — legacy seed, не будущий источник решений; после проверенного переноса и обратимого переключения его runtime путь удалить. Registry применим к сотням турниров и будущим игрокам. Версионированная связь с `canonical_events.id` определена в ADR-029.
- Артефакты: [REQ-026](../product/requirements/REQ-026-entity-registry.md), [ADR-029](../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md), [TASK-026-5](tasks/TASK-026-5-registry-publication.md), [локальный отчёт TASK-026-5](../changes/done/TASK-026-5-registry-publication.md), [runbook публикации](../operations/entity-registry-publication.md), [TASK-026-6](tasks/TASK-026-6-registry-candidate-feedback.md), [отчёт TASK-026-6](../changes/done/TASK-026-6-registry-candidate-feedback.md), [TASK-026-7](tasks/TASK-026-7-security-dependency-remediation.md), [отчёт TASK-026-7](../changes/done/TASK-026-7-security-dependency-remediation.md), [PR #61](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/61), [ADR-026 календаря](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md), [долгосрочный план](index.md#долгосрочные-инициативы-платформы), [EPIC-003](EPIC-003-scalable-multisport-platform.md), [EPIC-025](EPIC-025-bot-schedule-readiness.md). Эксплуатационные evidence и схема доступов: `operations-agent/docs/changes/2026-10-09-epic026-object-storage-access.md` и `operations-agent/docs/runbooks/sports-forecast-epic026-object-storage.md` в отдельном репозитории.
- Предыдущая роль: Reviewer — TASK-026-8 и локальный срез TASK-026-9 проверены без оставшихся P0–P2; [ops evidence](https://github.com/Xieveer/operations-agent/pull/33) ранее подтвердило server installation gate.
- Следующая роль: Product Owner — сохранить проверенный локальный commit; при доступности актуального owner master проверить NHL event/forecast cycle. В релизное окно Operations Agent защитит master backup и проверит strict reader с непустым feedback циклом по TASK-026-10.
- Открытые вопросы: staging master v1.3.1 не содержит событий; актуальный изменяемый owner master не найден в worktree. Непустая обратная очередь, локальное решение владельца и новая publication в production ещё не наблюдались. Strict reader выключен, runtime использует compatibility путь; удалить его после реального паритета и обратимого переключения. В строгом режиме legacy merge historical odds в `source.csv` отключён до проверенного локального materialization по подтверждённым связям.
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
6. Локальный веб-интерфейс показывает и позволяет исправлять уже подтверждённые
   сущности и обозначения, даже когда новых кандидатов нет; изменение проходит
   audit/revision и попадает в новый snapshot только после проверки владельцем.
7. Проверенный перенос всех NHL-связей из legacy YAML завершается отключением
   его runtime чтения. Контрольный NHL цикл сохраняет ожидаемые связи и прогнозы;
   возвращение прежнего режима остаётся описанным до завершения переключения.

## Зависимости и следующий gate

Основа для [EPIC-027](EPIC-027-historical-odds.md), [EPIC-029](EPIC-029-configured-tournament-onboarding.md) и [EPIC-031](EPIC-031-real-bets-ledger.md). Подтверждённый REQ и принятое архитектурное решение задают границы следующих срезов.

Оставшаяся работа EPIC-026: проверить актуальный owner master и реальный NHL
event/forecast cycle, затем окончательно вывести legacy YAML из runtime
(REQ-026 #13). В релизное окно выполнить preflight горизонта, контролируемое
включение strict reader и полный кандидатный цикл (REQ-026 #10). Веб-каталог
и редактор подтверждённых записей (REQ-026 #12) реализованы локально.

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
| [026-8](tasks/TASK-026-8-local-registry-catalog.md) | Веб-каталог и исправление подтверждённых записей; 12 | HTTP/DB, audit/revision, snapshot | done: независимое review чистое |
| [026-9](tasks/TASK-026-9-legacy-yaml-cutover.md) | Паритет NHL и вывод YAML из runtime; 13 | seed/master parity и NHL цикл | blocked: актуальный owner master и цикл |
| [026-10](tasks/TASK-026-10-strict-reader-rollout.md) | Строгий production reader и непустой feedback цикл; 10 | preflight, real candidate, publication/sync, rollback | blocked: релизное окно |

Object Storage endpoint, IAM и retention проверены на рабочем bucket.
Релиз v1.3.1 подтвердил PostgreSQL grants, первую публикацию, server sync,
zero-work feedback и первые плановые ticks. [TASK-026-5](tasks/TASK-026-5-registry-publication.md)
закрыт; весь EPIC остаётся `blocked` до строгого production reader и
непустого кандидатного цикла REQ-026 #10 и проверенного вывода legacy YAML
из рабочего пути #13. Веб-каталог #12 выполнен локально. Подробности — в
[ops evidence](https://github.com/Xieveer/operations-agent/pull/33).

## Риски и rollout

Существующие строковые имена и source ID нельзя заменять без проверенного backfill; переход должен быть аддитивным. Production-переключение — отдельное решение.
