# EPIC-026 — Единые идентификаторы спортивных сущностей

> **Статус:** in_progress — strict registry работает на v1.3.7; непустой owner candidate cycle перенесён на подключение нового турнира
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-026](../product/requirements/REQ-026-entity-registry.md) (`confirmed`)
> **ADR:** [ADR-029](../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md) (`accepted`, действующий/rollback); [ADR-035](../architecture/adr/ADR-035-registry-dictionaries-and-derived-event-matching.md) (`accepted`, целевой контракт)

## Память Product Owner

- Решение владельца 2026-10-12: все актуальные NHL команды известны, текущий outbox 0; непустой owner candidate → review → publication/sync/ack проверить при подключении нового турнира, сохранив открытый статус соответствующих критериев. Strict reader остаётся включён. Ежедневный odds вызов устранён в [EPIC-039](EPIC-039-v1-3-7-daily-cycle.md); три таймера включены и расписание проверено. Это уточнение заменяет прежний блокер текущего релиза по отсутствующему NHL кандидату.
- Инициатива: `EPIC-026`.
- Ветка инициативы: `initiative/epic-026-entity-registry`.
- Workflow / этап: TASK-026-12/13 прошли review и вошли в main через PR #89; runtime strict override и кандидаты исправлены в релизах до v1.3.6. Сейчас production strict=true на v1.3.7; TASK-026-9 ждёт итогового подтверждения вывода YAML из рабочего пути, TASK-026-10 — настоящего неизвестного обозначения с owner review/ack при новом турнире. Проверка 20 ticks выполнена в EPIC-039.
- Исходная цель: проектные ID и имена турниров, команд, рынков и исходов отделены от названий и ID источников; процесс применим к сотням турниров, локальный registry обслуживает загрузку истории и обучение.
- Критерии и DoD: подтверждённые критерии 1–15 в [REQ-026](../product/requirements/REQ-026-entity-registry.md), затем TASK review, полное EPIC review и terminal CI.
- Релиз: production работает на exact v1.3.7 source `e08452bc17b6d6bfab8fd97fd860f6df15fd56cd` и verified registry snapshot v2 sequence 3 `ir1:71897173e0ee72bb60f9038cc8570770b351d866a3f994e63ba26bf5bcfe03e2`. Strict reader включён; API/бот здоровы, dispatcher, registry-sync и registry-feedback timers активны. v1.3.6/v1.3.5/v1.3.4/v1.3.1 остаются rollback refs; предыдущие NO-GO описаны в EPIC-035/036/037.
- Выполнено: TASK-026-1…8 реализовали локальный registry, веб-каталог, snapshot/publication, feedback и security; TASK-026-12/13 добавили словари рынков/исходов и вычисляемое NHL сопоставление. v1.3.6 прошла review, CI/Security, Docker/evidence gates, полный strict NHL цикл и zero-work feedback. Исторические 22 656 ошибочных кандидатов v1.3.5 адресно удалены после backup/restore; outbox не разрастается. Непустой production owner цикл пока не наблюдался.
- Решения: собственные ID и имена проекта; переименование сохраняет ID; владелец просматривает и редактирует текущие словари через локальный веб-интерфейс. Сервер читает опубликованный через Object Storage снимок и передаёт кандидатов локально. `conf/bookmaker/team_name_registry/nhl.yaml` остаётся legacy seed; код старого пути сохраняется для отката. ADR-029 описывает действующий event bridge и rollback, принятый ADR-035 — целевые словари и вычисляемое сопоставление без owner event links. `canonical_events.id` и source event IDs сохраняются.
- Артефакты: [REQ-026](../product/requirements/REQ-026-entity-registry.md), [ADR-029](../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md), [TASK-026-5](tasks/TASK-026-5-registry-publication.md), [локальный отчёт TASK-026-5](../changes/done/TASK-026-5-registry-publication.md), [runbook публикации](../operations/entity-registry-publication.md), [TASK-026-6](tasks/TASK-026-6-registry-candidate-feedback.md), [отчёт TASK-026-6](../changes/done/TASK-026-6-registry-candidate-feedback.md), [TASK-026-7](tasks/TASK-026-7-security-dependency-remediation.md), [отчёт TASK-026-7](../changes/done/TASK-026-7-security-dependency-remediation.md), [PR #61](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/61), [ADR-026 календаря](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md), [долгосрочный план](index.md#долгосрочные-инициативы-платформы), [EPIC-003](EPIC-003-scalable-multisport-platform.md), [EPIC-025](EPIC-025-bot-schedule-readiness.md). Эксплуатационные evidence и схема доступов: `operations-agent/docs/changes/2026-10-09-epic026-object-storage-access.md` и `operations-agent/docs/runbooks/sports-forecast-epic026-object-storage.md` в отдельном репозитории.
- Текущие артефакты: [TASK-026-12](tasks/TASK-026-12-market-outcome-dictionaries.md), [отчёт TASK-026-12](../changes/done/TASK-026-12-market-outcome-dictionaries.md), [TASK-026-13](tasks/TASK-026-13-derived-nhl-event-matching.md), [отчёт TASK-026-13](../changes/done/TASK-026-13-derived-nhl-event-matching.md), [локальный runbook](../operations/identity-registry-local.md), обновлённый [runbook публикации](../operations/entity-registry-publication.md).
- Предыдущая роль: Developer завершил TASK-026-12/13; независимые Reviewer закрыли P1/P2 findings. Полный unit: 1706 passed; Ruff и проектный mypy gate passed. На копии master schema 11 миграция 11→12, идемпотентный NHL/Pinnacle seed и snapshot v2 прошли проверку целостности.
- Предыдущая роль: Reviewer завершил полное EPIC review и commit gate; проверенный diff — `3686ddd11e12ba7e93867b63d36b21ae8e36ede2`.
- Следующая роль: Product Owner — при подключении нового турнира проверить непустой owner candidate → review → publication/sync/ack и завершить TASK-026-10; затем отдельно решить вывод legacy пути TASK-026-9.
- Открытые вопросы: текущие NHL данные не содержат неизвестного обозначения, поэтому непустой feedback/owner review/ack остаётся непроверенным на production. Zero-work feedback, writer grant и три активных таймера проверены; legacy YAML и старые event relations сохраняются для rollback, их удаление — отдельная будущая задача.
- Production v1.3.7: strict reader включён; controlled цикл `4202cb11-9b72-4874-8503-75668c931e06` и scheduled цикл `514cee55-1905-4d0d-a131-3da0e49a605e` завершились успешно, последний опубликовал 216 прогнозов без стадии odds. Outbox 0, registry sync/zero-work feedback успешны, dispatcher выдержал 20 минутных ticks. Непустой owner цикл остаётся открытым по решению владельца; подробности — в [production handoff](../operations/production-handoff.md).
- Research: не применяется.
- Production v1.3.6: strict reader включён, полный NHL цикл `98a75688-50c3-4f07-822d-9fdbdcead0e2` опубликовал 218 прогнозов и три реальных Pinnacle observations без отказов; outbox 0 и zero-work feedback прошёл. Массовая очередь v1.3.5 исправлена. Реального неизвестного обозначения в текущих данных нет, поэтому TASK-026-10/REQ-026 #10 остаётся открытым до решения владельца; timers пока остановлены. Подробности — в [production handoff](../operations/production-handoff.md).
- Обновлено: 2026-10-12.

### Итоговое review кода EPIC-026

Проверенный commit: `3686ddd11e12ba7e93867b63d36b21ae8e36ede2`.
Проверены требования REQ-026 и ADR-035, migration schema 11→12, market/outcome
словарь, v1/v2 snapshot и публикация, локальный UI с CSRF/revision,
вычисляемое сопоставление live/future/OddsStore, границы уникальности,
кандидатная очередь, provenance, rollback runbook и тесты. Первичные P2 по
live outcome aliases и отсутствующей очереди неизвестных рынков исправлены
автором; повторная проверка не выявила P0–P2.

После исправлений выполнены полный unit (`1706 passed`, 17 deselected),
`UV_OFFLINE=1 make lint`, `UV_OFFLINE=1 make type-check`, targeted tests
(`58 passed`) и полный `pre-commit run --all-files`; все завершились успешно.
Форматирование после полного unit было проверено отдельно targeted tests,
mypy и hooks. Остаточный gate — terminal CI и реальный production NHL
forecast/odds + непустой candidate цикл EPIC-036. Historical OddsStore V3
не содержит provider event ID; проекция не синтезирует его.

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

Словари рынков/исходов и вычисляемое сопоставление NHL готовы к полному EPIC
review и вошли в `main` через PR #89. Права кандидатной очереди исправлены в
[EPIC-036](EPIC-036-registry-rollout.md). После нового выпуска остаются
реальный NHL forecast/odds cycle, контролируемое включение strict reader,
непустой кандидатный цикл и проверка rollback (REQ-026 #10, #13).
Legacy YAML и код старого пути сохраняются для явного отката; удаление кода
владелец отложил на отдельную будущую задачу.

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
| [026-12](tasks/TASK-026-12-market-outcome-dictionaries.md) | Словари рынков и исходов, audited market rule, snapshot v2; 1, 12, 15 | schema 11→12, seed, UI, v1/v2 publication | done: TASK review чистое; EPIC review ожидается |
| [026-13](tasks/TASK-026-13-derived-nhl-event-matching.md) | Общий matcher NHL ±15 минут и market gate; 4, 10, 15 | live/future/OddsStore, uniqueness, unknown aliases | done: TASK review чистое; EPIC review ожидается |

Object Storage endpoint, IAM и retention проверены на рабочем bucket.
Релиз v1.3.1 подтвердил PostgreSQL grants, первую публикацию, server sync,
zero-work feedback и первые плановые ticks. [TASK-026-5](tasks/TASK-026-5-registry-publication.md)
закрыт; весь EPIC остаётся незавершённым до строгого production reader и
непустого кандидатного цикла REQ-026 #10 и проверенного вывода legacy YAML
из рабочего пути #13. Веб-каталог #12 выполнен локально. Подробности — в
[ops evidence](https://github.com/Xieveer/operations-agent/pull/33).

## Риски и rollout

Существующие строковые имена и source ID нельзя заменять без проверенного backfill; переход должен быть аддитивным. Production-переключение — отдельное решение.
