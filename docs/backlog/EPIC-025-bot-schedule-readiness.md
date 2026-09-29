# EPIC-025 — Расписание бота и готовность NHL к сезону

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Память Product Owner

- Инициатива: `EPIC-025`.
- Текущий correction cycle: `initiative/epic-025-local-parity`,
  [TASK-025-22](tasks/TASK-025-22-local-quality-parity.md). Ручной Data Cycle
  v1.2.8 на production завершился `failed/canonical_freshness_failed`.
  Решение владельца от 2026-09-28: исправлять и проверять дефекты локально
  на контуре, сопоставимом с production, включая тестового Telegram-бота.
  Новый production rollout допускается только после подтверждённой локальной
  готовности; при повторении ошибок после выпуска остановить дальнейшие
  действия и запросить инструкции владельца.
- Конечная точка correction cycle по уточнению владельца: выпустить новую
  версию в production после локальных gates, проверить её на production;
  если она не работает, зафиксировать состояние и сделать промежуточную
  остановку до следующей команды владельца.
- Инцидент локального pytest с 14.3 GB RSS локализован в setup тестов:
  [TASK-025-23](tasks/TASK-025-23-pytest-memory-guard.md) исправил временные
  метки и добавил ранний отказ опасного mock; четыре адресных теста прошли под
  лимитом 4 GiB; независимое статическое review без P0–P2. Полный pytest
  suite намеренно не запускался после инцидента; bounded local parity ниже.
- Для TASK-025-22 изолированно восстановлен backup перед v1.2.8 в PostgreSQL
  16 без сети с лимитом 1 GiB. Агрегатный quality probe: 1 621 кандидат старого
  правила, 1 621 без `finished`, 0 настоящих предматчевых кандидатов. Это
  локально воспроизводит исходный отказ; исправленный validator в Worker
  контейнере с лимитом 1 GiB вернул `valid=True`, `expired=0`, `missing=0`.
- Локальный Worker на восстановленной истории под лимитом 3 GiB завершился
  без OOM и опубликовал 1 838 прогнозов; canonical archive синхронизирован
  с изолированным S3 fixture. Source-state archive (~181 MiB) подтвердил новый
  [TASK-025-24](tasks/TASK-025-24-archive-sync-bounded-memory.md):
  archive-sync завершился `OOMKilled=true` при production-лимите 512 MiB после
  upload и до remote verification. По запросу владельца работа остановлена,
  созданные локальные контейнеры корректно завершены; production не затронут.
- После возобновления TASK-025-24 прошёл red→green: девять адресных тестов
  archive-sync зелёные под лимитом 1 GiB, оба архива remote-verified на
  локальном S3 fixture при production-лимите archive-sync 512 MiB. Независимое
  review не нашло P0–P2 findings. Локальный API v1.2.8 под ролью
  `sf_api_reader` ответил `/ready` 200 (`db_connected=true`), календарь NHL
  на 30 дней — 200, 198 событий,
  `coverage=stale` для восстановленного снимка; лимит API 1.5 GiB, RSS около
  136 MiB. Связанный Data Cycle и тестовый Telegram-путь проверены ниже.
- Владелец подтвердил, что `@SSPredictBot` — тестовый бот. Контрольное
  сообщение в единственный разрешённый чат подтверждено Telegram (`ok=true`,
  message ID); адресные тесты bot calendar/notifications — 11 passed под
  лимитом 2 GiB. E2E команды `/upcoming` проверен ниже.
- Локальный бот v1.2.8 запущен под лимитом 384 MiB: heartbeat Telegram/API
  оба `true`; его API указывает на изолированный контур. Data Cycle
  runner contract/lifecycle — 41 passed под лимитом 2 GiB. Проверка команды
  `/upcoming` подтверждена владельцем: ответ с календарём NHL корректный,
  локальный контейнер обработал updates без polling conflict, API 5xx и OOM.
  Связанный локальный Data Cycle на полном фиксированном NHL snapshot завершился
  `partial_success` (odds выключены): 1 838 прогнозов, оба новых архива
  `verified`, Worker под 3 GiB и archive-sync под 512 MiB без OOM. Внешний
  source fetch и exact systemd/Compose wrapper не проверены. Отдельно после
  terminal status outbox producer поставил item, bot poller доставил его
  через Control API в тестовый Telegram и подтвердил (`delivered`, 1 попытка).
  Атомарный terminal+enqueue path в этом прогоне не проверен; он покрыт
  шестью repository tests (включая PostgreSQL lease race) под лимитом 2 GiB.
  Владелец подтвердил уведомление и корректный `/cycle_history` с локальным
  запуском. `make lint`, `make type-check`, `git diff --check` прошли под
  ограничениями памяти. Exact wrapper и внешний source fetch остаются gates.
- Exact Compose archive-sync выявил ещё один локальный дефект:
  [TASK-025-25](tasks/TASK-025-25-archive-sync-tmpfs.md). Production `/tmp`
  64 MiB не вмещал remote copy около 181 MiB (`exit=1`, без OOM). После
  переноса временной копии в sync-state volume 10 тестов зелёные под 1 GiB;
  actual Compose command remote-verified оба архива при `mem_limit=512m`
  и неизменном `/tmp=64m`. Независимое review не нашло P0–P2 findings.
- Внешний NHL source-acquirer на копии локального каталога завершился успешно
  под лимитом 1 GiB и обновил тестовый `current.csv` до 2026-10-29.
  Следующий связанный локальный run с этим source и весами production-модели
  остановлен cgroup при лимите Worker 3 GiB после валидации полных таблиц
  признаков. [TASK-025-26](tasks/TASK-025-26-refresh-inference-memory.md)
  устраняет построение и запись неиспользуемых train-таблиц в refresh.
  Run безопасно завершён `failed/prediction_failed`; бот доставил уведомление.
  Исправленный связанный run `876f0523-3f8c-44b6-95a8-0234b4258fbd`
  завершился `partial_success` лишь при явно выключенных odds: Worker под
  3 GiB опубликовал 1 847 прогнозов без OOM, оба archive-sync под 512 MiB
  с `/tmp=64m` remote-verified новые архивы; terminal outbox доставлен
  тестовому боту. Независимое review TASK-025-26 без P0–P2.
  Release/CI/production gates ещё открыты.
- Ветка инициативы: исходная `initiative/epic-025-bot-readiness` слита;
  correction cycle `initiative/epic-025-13-runtime-hotfix` слит;
  release candidate — `initiative/epic-025-release-1_2_2`; correction
  cycles — `initiative/epic-025-v1_2_3-calendar-snapshot`,
  `initiative/epic-025-v1_2_4-worker-logging`,
  `initiative/epic-025-v1_2_5-runtime-odds-publication` и
  `initiative/epic-025-v1_2_6-odds-optional` и
  `initiative/epic-025-v1_2_7-calendar-grant` и
  `initiative/epic-025-v1_2_8-archive-runner`; текущая correction branch
  `initiative/epic-025-v1_2_10-archive-stdin`.
- Workflow / этап: `v1.2.9 source PR #50 merged, source tag и CI/Security/
  Docker pipeline успешны; exact local wrapper завершил archive_sync с
  artifacts=0 из-за прав fixture, отдельный archive loop после исправления
  прав выявил stdin bug: 1 sync из 3 manifest. v1.2.9 NO GO;
  TASK-025-27 исправлен в draft PR #52 для v1.2.10, его CI зелёный и
  независимый review без P0–P2. Ограниченный local wrapper с новым shell,
  образами v1.2.9 и локальным UID override завершился partial_success:
  archive_sync artifacts=2, оба manifest remote-verified, прирост OOM=0;
  exact release images/UID, tag/evidence и production gates ещё открыты.
  Backup/restore/off-host проверены`.
- Исходная цель: календарь NHL независимо от прогноза, готовность событий,
  админ-управление Data Cycle и выпуск `1.2.1`;
  [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md).
- Критерии приёмки и DoD: подтверждены владельцем в REQ-025; независимый
  review, CI и production health/smoke входят в release gate.
- Релиз: пользователь запросил production `1.2.0`; после failure immutable tag
  gate согласовал `1.2.1` как первый production выпуск. После неуспешного
  первого цикла подготовлен `1.2.2` candidate; владелец подтвердил выпуск
  2026-09-27. Для v1.2.8 владелец установил границу: при новой проблеме
  после выпуска обеспечить безопасное состояние, зафиксировать факты и
  остановить дальнейшие доработки/релизы до его указаний.
- Выполнено: владелец дал полную постановку в Google Doc; REQ-025 приведён к
  ней и подтверждена трактовка «Сегодня» до 08:00 МСК; ограничение API
  прогнозами, 48-часовой минимум source и расхождение `/refresh` с systemd
  зафиксированы; 25 базовых тестов бота прошли. Read-only Operations audit
  не смог подтвердить runtime timer из-за SSH timeout. Read-only probe
  configured NHL API 2026-09-26 вернул HTTP 200 и 3 игры на 30 сентября,
  а октябрьский якорь вернул опубликованные дальние матчи; production store
  и его 30-дневное покрытие всё ещё не проверены. Первый diff TASK-025-1
  прошёл correction cycle после findings и повторное независимое review
  без блокирующих замечаний; Developer выполнил 61 тест/lint/Alembic head,
  Reviewer повторно выполнил 46 целевых тестов. Ошибки mypy из первого
  commit gate исправлены; повторный commit gate прошёл все hooks.
  Проверенный content commit: `b23e2ccc3b869667e95e0f46fbe472731a6f1c8e`.
  Срез readiness TASK-025-2 прошёл correction cycle по двум P1, повторное
  независимое review и 47 целевых тестов; pre-commit чистый. Content commit
  `9ef0e73` отправлен в origin. `odds.failed` и сбор будущих котировок
  остаются зависимостями TASK-025-6, поэтому TASK-025-2 помечен blocked.
  Read-only VPS preflight подтвердил, что NHL systemd timer установлен, но
  `disabled/inactive`, последнего и следующего запуска нет. Повторная проверка
  2026-09-26 через действующий SSH-доступ подтвердила checkout `v1.1.22` и
  тот же статус timer. Daily scheduler сейчас не работает; Docker/DB/run
  history недоступны текущему SSH-пользователю, а `sudo` требует интерактивной
  аутентификации. Для привилегированного preflight пользователю переданы точные
  read-only команды из operations runbook. Полученный привилегированный вывод
  подтвердил healthy API/bot/DB без рестартов, совпадение running digests с
  `v1.1.22` manifest и **0 будущих NHL матчей за 30 дней** в production DB.
  Текущего calendar coverage/Data Cycle ещё нет; backup/restore gate открыт.
  Исследование The Odds API выявило риск ложного `ready` у трёхисходного h2h,
  если старый OddsStore отбросил ничью. TASK-025-2 получил второй correction
  cycle: provenance и строгая семантика рынка исправлены, re-review чистое,
  82 целевых теста и pre-commit прошли; commit `8e85193` опубликован.
  TASK-025-3 создал durable run до source и сохранил failed calendar attempt;
  четыре findings Reviewer исправлены, повторное review чистое, 30 целевых
  тестов прошли. Content commit TASK-025-3 `705db65` опубликован, повторный
  commit gate прошёл 30 тестов и все hooks. TASK-025-7 добавил policy-driven
  terminal guard и безопасный summary/history query DTO; после correction cycle
  повторный Reviewer не нашёл блокирующих findings (22 целевых теста).
  Content commit TASK-025-7 `9dd511a` опубликован; 35 целевых тестов и
  pre-commit прошли. Полные счётчики в TASK-025-10, защищённый HTTP в
  TASK-025-4, recovery/fencing в TASK-025-8; будущие odds — в TASK-025-6.
  TASK-025-11 перевёл `/upcoming` на календарь и прошёл повторное review без
  findings после HTML/UTF-16 и callback исправлений; 78 целевых тестов прошли.
  Content commit TASK-025-11 `f958bbc` опубликован. TASK-025-6 добавил
  calendar-first future odds и persisted failed attempts; после трёх findings
  повторное review чистое, 81 целевой тест у Developer и 51 у Reviewer прошли.
  `odds.failed` завершает зависимость TASK-025-2.
  TASK-025-6 и TASK-025-2 закрыты после 81 целевого теста и полного
  pre-commit; content commit `442fc92` опубликован в ветке инициативы.
  TASK-025-4 и TASK-025-10 прошли correction cycle и повторное независимое
  review без P0–P2. PostgreSQL race/grants проверены на disposable PG16;
  51 целевой тест summary и 34 целевых теста control прошли. Проверенный
  content commit `9b77aab` опубликован в ветке инициативы; объединённый
  прогон дал 85 passed, 2 env-gated skips, pre-commit и `make lint` прошли,
  `make docs` собрался с 24 предупреждениями.
  TASK-025-8 прошёл три correction findings (abnormal Docker CLI exit,
  быстрый stage/heartbeat race, запрет снятия stalled fence ролью API);
  повторный Reviewer не нашёл блокирующих замечаний. На disposable PG16
  подтверждены migration 0016, grants и race; 74 целевых теста и pre-commit
  прошли. Content commit `784f41a` опубликован. Реальный host recovery и
  включение timer остаются release gate TASK-025-9.
  Закрыт ранее blocked TASK-025-7: его terminal/query срез и зависимости
  TASK-025-4/6/8/10 теперь завершены; production runtime подтверждается
  отдельно в TASK-025-9.
  TASK-025-5 добавил admin Telegram control и transactional terminal outbox;
  независимый review чистый, PostgreSQL 16 role/race gate дал 33 passed,
  локальный финальный срез 117 passed, 4 gated skips, pre-commit прошёл.
  Content commit `31a92b6` опубликован. Alias mapping и actual Telegram
  delivery остаются production release gates TASK-025-9.
  Полный EPIC review выявил P1 в first-rollout fixture: он не создавал новые
  control/notification inputs Compose. Red→green исправление прошло 43
  production contract теста; повторный Reviewer подтвердил real Compose
  render и не нашёл P0–P2. P2 о порядке role-bootstrap/migrator в handoff
  исправлен по фактическому Compose contract. Локальный полный набор до
  fixture correction: 1202 passed, 5 PostgreSQL-gated skips; отдельный PG16
  role/race gate: 33 passed. `make lint`, `make docs` (24 warnings),
  `make security`, `make production-check`, `make ai-validate` прошли.
  Evidence gate v1.2.1 и verified pre-migration backup, isolated restore и
  off-host read-back прошли. Production schema обновлена до 0017, API и бот
  v1.2.1 healthy. Первый run `5d9be516-13b6-4ea7-9709-0fbe26b1b649`
  завершился `failed/source_fetch_failed`; одно итоговое уведомление
  доставлено. Выявлены четыре runtime-дефекта TASK-025-13. Их исправление
  прошло 28 Developer и 52 Reviewer теста без P0–P2; PR #42 CI прошёл и
  слит в `main` commit `35f1c6a7e80188d94b750674d11a1f0f8fd08e79`.
  v1.2.2 tag/evidence gates прошли, serving API/bot healthy на VPS, но ручной
  run `b4e312c2-59c2-4917-8e06-8483cd06a3b3` failed: source snapshot
  ошибочно требовал closing line у 1 899 будущих событий. После host stop
  proof run закрыт, уведомление доставлено один раз, оба timer выключены.
  В TASK-025-14 red-тест воспроизвёл ValueError; исправление прошло 24
  целевых теста. Активный model bundle имеет app_version 1.1.14 и требует
  проверенной repackage перед v1.2.3 Worker.
  v1.2.3 PR/tag/evidence прошли, проверенный backup и совместимый model bundle
  установлены. Serving API/bot healthy. Ручной run
  `e96868fa-04cd-4c3a-bff8-c5b34f51b709` опубликовал source snapshot
  181 826 590 bytes, затем read-only Worker отказал при создании Hydra log
  в `/app`. После host stop proof run закрыт как `failed/source_fetch_failed`,
  outbox доставлен один раз; календарь пока пуст, оба timer выключены.
  TASK-025-15 исправляет потерю console-only Hydra overrides при `compose run`;
  новый release candidate — v1.2.4. Веса модели не меняются, но Worker
  требует новый совместимый wrapper `app_version=1.2.4`.
  v1.2.4 PR/tag/evidence и ограниченный serving rollout прошли. Ручной run
  `dcd54406-7b88-4061-85b0-c60d76aef127` импортировал календарь:
  34 матча за 7 дней, 187 за 30 дней, coverage `complete`; календарь API
  отвечает 200. Стадия odds завершилась `provider_not_configured`, поскольку
  клиент не читал `*_FILE` и Worker не монтировал ключи. Publication вернула
  `materialization_failed`; изолированный replay выявил mismatch: runtime
  `SF_FEATURES=basic` построил 139 колонок, promoted bundle ожидает 489
  `advanced` признаков. TASK-025-17 закрепляет выбор признаков по контракту
  модели, а не независимому runtime override.
  После host stop proof run закрыт, уведомление доставлено один раз, оба
  timer выключены. TASK-025-16 исправляет контракт secret files и
  stdout-логи; TASK-025-17 исправляет publication; следующий кандидат —
  v1.2.5.
  v1.2.5 PR/tag/evidence и serving rollout прошли; API/bot healthy,
  календарь 187/30d complete. Два ручных run выявили старый systemd
  `nhl.env`: Worker/version v1.2.4, затем algorithm `catboost` вместо
  promoted `catboost_reg`. Оба run закрыты после host stop proof, outbox
  доставлен по одному разу, timers disabled. Runtime profile исправлен и
  проверен fail-closed по actual systemd EnvironmentFiles и model contract.
  Три distinct Odds API tier keys дали HTTP 401 `INVALID_KEY`; владелец
  выбрал продолжение без odds. TASK-025-18 делает явный OFF-режим future
  odds, чтобы публиковать календарь/прогнозы без запросов к провайдеру;
  следующий кандидат v1.2.6. Изолированный replay publication обнаружил
  TASK-025-19: прогнозы записаны, но counters внутри transaction нулевые
  из-за `autoflush=False`; после commit 187 из 187 eligible готовы.
  v1.2.6 PR/tag/evidence CI и exact-image isolated OFF replay прошли:
  1 834 прогнозов, `predictions_ready=187/187`, odds attempts 0.
  Перед rollout подтверждены backup/restore/off-host copy и model contract.
  После serving switch API/bot healthy, но calendar smoke дал 500 из-за
  отсутствующего `SELECT` на `data_cycle_stage_results` у `sf_api_reader`.
  Operations откатил serving на v1.2.5; health/readiness и calendar 0/7/30
  восстановлены, active run 0, NHL timers disabled. Новый bug fix —
  [TASK-025-20](tasks/TASK-025-20-calendar-stage-read-grant.md), релиз v1.2.7.
  v1.2.7 прошёл full first-rollout под production DB roles, PR/tag/evidence
  gates и serving smoke. Ручной OFF Data Cycle сохранил 1 834 прогнозов,
  готовность 187/187 будущих матчей и ноль odds attempts, но завершился
  `failed/archive_sync_failed`: Compose заменил CMD образом на системный
  `sync`. После host stop proof active0, одно итоговое уведомление доставлено;
  оба timer disabled. Исправление и проверка реальной команды до tag —
  [TASK-025-21](tasks/TASK-025-21-archive-sync-runner-command.md), v1.2.8.
  v1.2.8 correction прошёл независимое review без P0–P2, полный локальный
  first-rollout на clean SHA `61e201e` с двумя архивами через Compose/MinIO,
  затем PR и tag CI/Security/Docker с first-rollout на merged source commit
  `ab1626e`. Перед production rollout свежий backup прошёл isolated restore,
  off-host hash и третью копию; точечная очистка неиспользуемых v1.1.14
  образов освободила 7 188 197 376 bytes, v1.2.7 rollback сохранён.
- Решения: [ADR-026](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)
  принят после независимого review: календарь независим от прогноза, control
  state в PostgreSQL, ограниченный control API и systemd dispatcher;
  для NHL один связанный цикл;
  ручная команда повторяет data job без перезапуска служб; футбол проверяется
  по общему контракту без включения в `1.2.1`.
- Артефакты: [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md).
- Предыдущая роль: Developer — TASK-025-22/23/24 и bounded local parity;
  Reviewer — код без P0–P2, finding по устаревшим статусам исправлен.
- Следующая роль: Product Owner — terminal PR/CI и source tag v1.2.10;
  Operations Agent — release evidence, свежий backup и ограниченный
  production rollout после release gates. Production rollout ещё не начат.
- Открытые вопросы / блокеры: 30-дневное coverage подтверждено (187 матчей),
  три provider keys недействительны, isolated publication подтверждена,
  production manual run v1.2.7 завершился ошибкой archive_sync. Оба NHL
  timer выключены. Свежий pre-v1.2.9 backup `bd5dc06e…` прошёл
  restore/off-host read-back/third-copy; перед новым rollout проверить
  актуальность.
  Bucket retention/encryption не удалось прочитать текущим service account.
  Daily NHL scheduler NO-GO до успешного ручного OFF-цикла новой версии.
  Source fetch, bounded Worker и tag CI v1.2.9 проверены. Exact wrapper
  ошибочно завершил archive_sync с 0 artifacts из-за прав fixture; отдельный
  archive loop после исправления прав выявил поглощение stdin и 1 sync из 3.
  TASK-025-27 исправлен: bounded hybrid wrapper завершился с двумя
  remote-verified архивами без OOM. Source tag, evidence, fresh backup и
  production gates v1.2.10 ещё открыты. Полный pytest на ноутбуке не запускать.
- Обновлено: 2026-09-29.

## Цель и границы

Реализовать [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md):
календарь и готовность событий, Data Cycle с управлением из Telegram,
операционную готовность NHL и выпуск `1.2.1` в production. Футбол проверяется
контрольным сценарием без включения в пользовательское меню.

## Декомпозиция

| Задача | Результат | Проверка | Статус |
|---|---|---|---|
| [TASK-025-1](tasks/TASK-025-1-calendar-api.md) | Calendar acquisition → canonical store → API | 08:00, 30 суток, coverage, revision, футбол fixture | done |
| [TASK-025-2](tasks/TASK-025-2-event-readiness.md) | Readiness прогноза и коэффициентов поверх календаря | missing/stale/deadline, футбол fixture | done |
| [TASK-025-3](tasks/TASK-025-3-data-cycle-runs.md) | Durable ingress, failed acquisition, stage wiring | source failure, shell path, migration | done; runtime gate остаётся |
| [TASK-025-6](tasks/TASK-025-6-future-odds.md) | Calendar-first future NHL odds | semantic evidence, quota, identity, freshness | done |
| [TASK-025-7](tasks/TASK-025-7-data-cycle-recovery-summary.md) | Terminal stages, summary и run history query contract | stage faults, coverage, safe DTO | done; production runtime в TASK-025-9 |
| [TASK-025-8](tasks/TASK-025-8-executor-fencing.md) | Executor recovery/fencing after crash | PostgreSQL race, no duplicate executor | done; production activation в TASK-025-9 |
| [TASK-025-9](tasks/TASK-025-9-release-readiness.md) | Production release and NHL daily scheduler | terminal CI, migration, health/smoke, timer run | in_progress; v1.2.7 serving, timer disabled |
| [TASK-025-13](tasks/TASK-025-13-production-runtime-hotfixes.md) | Исправить четыре runtime-дефекта первого цикла | grants, source DB, runner, heartbeat | done; PR #42 merged |
| [TASK-025-14](tasks/TASK-025-14-future-close-odds-snapshot.md) | Публиковать source snapshot без closing line будущего матча | red/green, source/canonical tests, production snapshot | done; опубликован v1.2.3 snapshot |
| [TASK-025-15](tasks/TASK-025-15-readonly-worker-hydra-logging.md) | Безопасный Hydra CLI в read-only Worker | red/green, stdout, no filesystem write | done; runtime gate в TASK-025-9 |
| [TASK-025-16](tasks/TASK-025-16-odds-secret-files-and-stdout-logging.md) | File-backed Odds API keys и stdout-логи | red/green, secret mounts, review | in_progress; код и review готовы, runtime gate открыт |
| [TASK-025-17](tasks/TASK-025-17-promoted-feature-contract.md) | Feature config из promoted bundle | basic→advanced, invalid contract, review | in_progress; код и review готовы, runtime gate открыт |
| [TASK-025-18](tasks/TASK-025-18-optional-future-odds.md) | Явный режим без будущих odds | zero HTTP, partial_success, публикация прогнозов | in_progress; isolated OFF replay v1.2.6 прошёл, production gate открыт |
| [TASK-025-19](tasks/TASK-025-19-publication-count-flush.md) | Корректные counters publication | no-autoflush, 187 eligible, atomicity | in_progress; isolated counters 187/187, production gate открыт |
| [TASK-025-20](tasks/TASK-025-20-calendar-stage-read-grant.md) | Точечное право чтения odds-стадии для календаря | role grant, first-rollout и production calendar smoke | in_progress; v1.2.7 calendar smoke 0/34/187, archive gate открыт |
| [TASK-025-21](tasks/TASK-025-21-archive-sync-runner-command.md) | Исправить вызов archive-sync в production runner | exact Compose CLI, local S3 fixture, manual OFF run | in_progress; v1.2.8 candidate |
| [TASK-025-27](tasks/TASK-025-27-archive-manifest-loop.md) | Обработать все archive manifest без потери stdin | red/green, 3-manifest regression, bounded wrapper | done; v1.2.10 release gate открыт |
| [TASK-025-12](tasks/TASK-025-12-release-compose-gate.md) | Исправить Compose release gate | новый API/dispatcher contract и память | done; PR CI в TASK-025-9 |
| [TASK-025-10](tasks/TASK-025-10-run-summary-producers.md) | Full run summary producers and coverage | same-run counters, n/a denominator, football fixture | done |
| [TASK-025-11](tasks/TASK-025-11-telegram-calendar.md) | Public NHL calendar in Telegram | 08:00, all horizons, no prediction, bot→API test | done |
| [TASK-025-4](tasks/TASK-025-4-schedule-control.md) | Persisted schedule, manual control, dispatcher | admin auth, races, restart, catch-up | done; production activation в TASK-025-9 |
| [TASK-025-5](tasks/TASK-025-5-telegram-experience.md) | Telegram calendar, admin controls, notifications, code-based E2E | 08:00, auth, idempotency, bot→API | done; delivery activation в TASK-025-9 |

Operations release gate зафиксирован в TASK-025-9. После calendar 500 в
v1.2.6 serving откатили на v1.2.5: API/bot healthy, календарь 30 суток
содержит 187 матчей с coverage `complete`, схема 0017, timers disabled.
v1.2.6 source/evidence и isolated OFF replay прошли; production manual
не начинался. Для v1.2.7 нужны точечный role grant, reviewed release
evidence, повторный calendar smoke и полный ручной цикл без odds.

## Риски и rollout

Бот может быть исправен при пустой витрине прогнозов; источник, materialization
и scheduler требуют отдельной проверки. До rollout необходимы фактические
runtime evidence, rollback target и terminal CI для exact commit.

## Полное EPIC review

Независимый Reviewer проверил REQ-025/ADR-026, завершённые функциональные
TASK, API/бот, календарь, готовность, расписание, recovery, transactional
outbox, миграции/DB роли, football fixture, Compose и release workflow.
Первое review выявило P1 fixture для новых required control/notification
inputs и P2 противоречие порядка миграции в handoff. Исправления прошли
повторное review; P0–P2 findings не осталось. Для локального candidate
допустим commit и PR. Merge/tag возможны только после terminal PR CI.
Проверенный content commit: `13aa7b399d9ca700f806b69c38ce34e0ee913776`;
его commit gate прошёл Ruff, форматирование, mypy, AI validation и остальные
применимые pre-commit hooks. Reviewer отдельно запустил два fixture tests:
`2 passed`, включая реальный `docker compose config --quiet`, и
`git diff --check`.
Production Data Cycle остаётся NO-GO до свежего verified backup/restore,
совместимого rollback, runtime smoke, публикации прогнозов, измерения
future odds/quota и первого планового запуска нового dispatcher; эти
результаты принимает TASK-025-9. Календарное покрытие уже подтверждено.
