# EPIC-026 — Единые идентификаторы спортивных сущностей

> **Статус:** in_progress — strict rollout заблокирован до исправления контракта словарей и сопоставления котировок
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-026](../product/requirements/REQ-026-entity-registry.md) (`confirmed`)
> **ADR:** [ADR-029](../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md) (`accepted`, действующий/rollback); [ADR-035](../architecture/adr/ADR-035-registry-dictionaries-and-derived-event-matching.md) (`proposed`, целевой контракт)

## Память Product Owner

- Инициатива: `EPIC-026`.
- Ветка инициативы: `initiative/epic-026-entity-registry`.
- Workflow / этап: реализованные по прежнему контракту локальный каталог и strict path находятся в `main`; v1.3.2 получил NO-GO на реальном preflight. [TASK-026-9](tasks/TASK-026-9-legacy-yaml-cutover.md) и [TASK-026-10](tasks/TASK-026-10-strict-reader-rollout.md) ждут исправленного runtime и повторных gates. [TASK-026-11](tasks/TASK-026-11-nhl-event-bootstrap.md) остаётся историческим результатом.
- Исходная цель: проектные ID и имена турниров, команд, рынков и исходов отделены от названий и ID источников; процесс применим к сотням турниров, локальный registry обслуживает загрузку истории и обучение.
- Критерии и DoD: подтверждённые критерии 1–15 в [REQ-026](../product/requirements/REQ-026-entity-registry.md), затем TASK review, полное EPIC review и terminal CI.
- Релиз: production работает на v1.3.1; snapshot `ir1:e0070e397775a9227300d3edb061b20a15744f5317ccd7e56752e6ab67e196ce` опубликован и установлен, 51/51 NHL events разрешены при preflight. v1.3.2 получил NO-GO в [EPIC-035](EPIC-035-v1-3-2-registry-rollout.md): strict reader теряет шесть живых котировок, ORM запись кандидата не имеет SELECT для `RETURNING`. Strict reader выключен; legacy путь работает. После исправления контракта нужны review, CI и повторный полный gate.
- Выполнено: TASK-026-1…7 реализовали базовый registry, resolver, snapshot/publication, обратную очередь и security remediation; v1.3.1 закрыл server installation gate. TASK-026-8 добавил веб-каталог и правки с audit/revision; независимое review чистое. TASK-026-9 подготовил строгий путь без чтения YAML, проверку паритета и synthetic NHL feedback цикл; staging master/snapshot v1.3.1 содержит 33 команды, 100 командных обозначений и ноль событий, сверка обозначений прошла без расхождений. Локально: 1652 unit-теста passed, `make lint`, `make docs` и `make ai-validate` passed. Строгий runtime reader не включён.
- Решения: собственные ID и имена проекта; переименование сохраняет ID; владелец просматривает и редактирует текущие словари через локальный веб-интерфейс. Сервер читает опубликованный через Object Storage снимок и передаёт кандидатов локально. `conf/bookmaker/team_name_registry/nhl.yaml` остаётся legacy seed; код старого пути сохраняется для отката. ADR-029 описывает действующий event bridge и rollback, предлагаемый ADR-035 — целевые словари и вычисляемое сопоставление без owner event links. `canonical_events.id` и source event IDs сохраняются.
- Артефакты: [REQ-026](../product/requirements/REQ-026-entity-registry.md), [ADR-029](../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md), [TASK-026-5](tasks/TASK-026-5-registry-publication.md), [локальный отчёт TASK-026-5](../changes/done/TASK-026-5-registry-publication.md), [runbook публикации](../operations/entity-registry-publication.md), [TASK-026-6](tasks/TASK-026-6-registry-candidate-feedback.md), [отчёт TASK-026-6](../changes/done/TASK-026-6-registry-candidate-feedback.md), [TASK-026-7](tasks/TASK-026-7-security-dependency-remediation.md), [отчёт TASK-026-7](../changes/done/TASK-026-7-security-dependency-remediation.md), [PR #61](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/61), [ADR-026 календаря](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md), [долгосрочный план](index.md#долгосрочные-инициативы-платформы), [EPIC-003](EPIC-003-scalable-multisport-platform.md), [EPIC-025](EPIC-025-bot-schedule-readiness.md). Эксплуатационные evidence и схема доступов: `operations-agent/docs/changes/2026-10-09-epic026-object-storage-access.md` и `operations-agent/docs/runbooks/sports-forecast-epic026-object-storage.md` в отдельном репозитории.
- Предыдущая роль: независимый Reviewer подтвердил TASK-026-11 без новых P0–P2, 23 целевых теста passed; полный unit — 1679 passed.
- Следующая роль: Product Owner — принять ADR-035 после review и декомпозировать исправление; Developer — реализовать минимальный срез и grants очереди; Reviewer — проверить перед CI и повторными production gates.
- Открытые вопросы: owner master и опубликованный snapshot содержат 51 событие по прежнему контракту; паритет 100 legacy team aliases сохранён. Publication/sync прошли, но реальный forecast cycle в strict режиме и непустой цикл кандидата с решением владельца не прошли. Новые словари рынков/исходов и общий matcher ещё не реализованы. В строгом режиме legacy merge historical odds в `source.csv` отключён до проверенного локального materialization по подтверждённым связям.
- Research: не применяется.
- Обновлено: 2026-10-11.

### Уточнение владельца от 2026-10-11

Независимое review уточнения контракта: первоначальные P2 по устаревшему
release evidence и статусам ADR устранены; повторная проверка четырёх документов
не выявила P0–P2. Проверенный коммит: `681c226`. `make docs` прошёл
с ранее существовавшим предупреждением `_static`; `git diff --check` чистый.
Это review документационного уточнения, не итоговое review EPIC-026.

Registry должен хранить соответствия турниров, команд, рынков и исходов между
источниками. Будущие игроки имеют собственные обозначения по источникам и
интервальную связь с командой. Постоянные пары ID отдельных матчей не являются
целевым справочником: котировка сопоставляется по подтверждённым турниру,
командам, сторонам, правилам рынка и времени с допуском NHL до 15 минут UTC.
Требуется взаимная уникальность; неоднозначный случай ждёт решения владельца.
Source event ID остаются в исходных записях и provenance. Шесть ранее
подтверждённых пар The Odds API → NHL game ID остаются диагностическим
evidence и пока не добавлены как owner designations.

Репетиция v1.3.2 выявила потерю шести живых Pinnacle котировок из-за разницы
времени +10 минут и недостаточные права записи в кандидатную очередь.
Production остаётся на v1.3.1 со strict reader off; rollout и удаление legacy
пути остановлены до исправления, review, CI и повторных gates. Уже созданные
event entities и snapshot сохраняются до проверенной миграции, но не должны
диктовать целевое повседневное сопоставление котировок.

## Цель и границы

Сопоставлять участников, турниры, рынки и исходы поддерживаемых источников с
собственными стабильными ID и редактируемыми именами проекта. Первый реальный
пример — NHL API и The Odds API, но механизм и процесс проверки не зависят от
конкретного турнира. Матчи сопоставляются при обработке без накопления пар
event ID. Будущие игроки имеют независимую идентичность, внешние обозначения
и интервальную связь с командой; player-прогнозы и сбор составов остаются
отдельной инициативой.

## Проверяемый результат

Точные критерии подтверждены в [REQ-026](../product/requirements/REQ-026-entity-registry.md).
Проверяемые сценарии:

1. Собственные ID и имена турнира, команды, рынка и исхода не меняются от переименования;
   `COL` и `Colorado Avalanche` указывают на одну проектную команду.
2. Неочевидная связь ждёт решения владельца в локальной веб-очереди с поиском
   и пакетными действиями; решение сохраняется и применяется повторно.
3. Та же процедура работает на контрольном втором турнире без Python-правок
   под его конкретные названия и ID.
4. Существующий NHL-календарь и прогнозная выдача остаются доступны на прежних
   входах; идентичность будущих игроков предусмотрена без запуска player-прогнозов.
   Котировка присоединяется лишь при подтверждённых командах и правилах рынка,
   допуске NHL до 15 минут UTC и единственном взаимном соответствии матчей.
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

Оставшаяся работа EPIC-026: добавить словари рынков и исходов, исправить
вычисляемое сопоставление NHL матчей и права кандидатной очереди; проверить
реальный NHL forecast cycle, затем вывести legacy YAML из runtime (REQ-026 #13).
После review и CI повторить preflight горизонта, контролируемое включение
strict reader и полный кандидатный цикл (REQ-026 #10). Веб-каталог и редактор
подтверждённых записей (REQ-026 #12) реализованы локально для существующих
видов сущностей; рынки и исходы должны пройти тот же путь.

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
| [026-9](tasks/TASK-026-9-legacy-yaml-cutover.md) | Паритет NHL и вывод YAML из runtime; 13 | seed/master parity и NHL цикл | blocked: реальный forecast cycle |
| [026-10](tasks/TASK-026-10-strict-reader-rollout.md) | Строгий production reader и непустой feedback цикл; 10 | preflight, real candidate, publication/sync, rollback | blocked: пересмотренный контракт и реальный gate |
| [026-11](tasks/TASK-026-11-nhl-event-bootstrap.md) | Доверенное наполнение NHL events по прежнему контракту | 51 официальный матч, verified snapshot и строгий resolver | done: исторический результат; целевой контракт изменён |

Object Storage endpoint, IAM и retention проверены на рабочем bucket.
Релиз v1.3.1 подтвердил PostgreSQL grants, первую публикацию, server sync,
zero-work feedback и первые плановые ticks. [TASK-026-5](tasks/TASK-026-5-registry-publication.md)
закрыт; весь EPIC остаётся незавершённым до строгого production reader и
непустого кандидатного цикла REQ-026 #10 и проверенного вывода legacy YAML
из рабочего пути #13. Веб-каталог #12 выполнен локально. Подробности — в
[ops evidence](https://github.com/Xieveer/operations-agent/pull/33).

## Риски и rollout

Существующие строковые имена и source ID нельзя заменять без проверенного backfill; переход должен быть аддитивным. Production-переключение — отдельное решение.
