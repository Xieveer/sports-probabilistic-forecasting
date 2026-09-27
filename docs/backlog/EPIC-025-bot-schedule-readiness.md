# EPIC-025 — Расписание бота и готовность NHL к сезону

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Память Product Owner

- Инициатива: `EPIC-025`.
- Ветка инициативы: исходная `initiative/epic-025-bot-readiness` слита;
  correction cycle `initiative/epic-025-13-runtime-hotfix` слит;
  release candidate — `initiative/epic-025-release-1_2_2`; correction
  cycles — `initiative/epic-025-v1_2_3-calendar-snapshot`,
  `initiative/epic-025-v1_2_4-worker-logging` и
  `initiative/epic-025-v1_2_5-runtime-odds-publication`.
- Workflow / этап: `release correction / v1.2.4 serving healthy; 30-day calendar complete; odds and publication failed; v1.2.5 candidate`.
- Исходная цель: календарь NHL независимо от прогноза, готовность событий,
  админ-управление Data Cycle и выпуск `1.2.1`;
  [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md).
- Критерии приёмки и DoD: подтверждены владельцем в REQ-025; независимый
  review, CI и production health/smoke входят в release gate.
- Релиз: пользователь запросил production `1.2.0`; после failure immutable tag
  gate согласовал `1.2.1` как первый production выпуск. После неуспешного
  первого цикла подготовлен `1.2.2` candidate; владелец подтвердил выпуск
  2026-09-27.
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
- Решения: [ADR-026](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)
  принят после независимого review: календарь независим от прогноза, control
  state в PostgreSQL, ограниченный control API и systemd dispatcher;
  для NHL один связанный цикл;
  ручная команда повторяет data job без перезапуска служб; футбол проверяется
  по общему контракту без включения в `1.2.1`.
- Артефакты: [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md).
- Предыдущая роль: Reviewer — TASK-025-16/17 code diff без P0–P2;
  документация синхронизирована после review.
- Следующая роль: Product Owner — v1.2.5 PR/tag/evidence; Operations — свежий
  backup, совместимый bundle, повторный ручной и первый плановый NHL run.
- Открытые вопросы / блокеры: 30-дневное coverage подтверждено (187 матчей),
  odds quota и публикация прогнозов не подтверждены. Оба NHL timer выключены.
  Проверенный pre-v1.2.4 backup устарел после календарной записи; нужен
  свежий backup/restore/off-host hash перед v1.2.5 rollout. Bucket
  retention/encryption не удалось прочитать текущим service account.
  Production release NO-GO до исправленного v1.2.5 artifact, совместимого
  model bundle и успешных runtime gates.
- Обновлено: 2026-09-27.

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
| [TASK-025-9](tasks/TASK-025-9-release-readiness.md) | Production release and NHL daily scheduler | terminal CI, migration, health/smoke, timer run | in_progress; v1.2.4 calendar complete, odds/publication failed |
| [TASK-025-13](tasks/TASK-025-13-production-runtime-hotfixes.md) | Исправить четыре runtime-дефекта первого цикла | grants, source DB, runner, heartbeat | done; PR #42 merged |
| [TASK-025-14](tasks/TASK-025-14-future-close-odds-snapshot.md) | Публиковать source snapshot без closing line будущего матча | red/green, source/canonical tests, production snapshot | done; опубликован v1.2.3 snapshot |
| [TASK-025-15](tasks/TASK-025-15-readonly-worker-hydra-logging.md) | Безопасный Hydra CLI в read-only Worker | red/green, stdout, no filesystem write | done; runtime gate в TASK-025-9 |
| [TASK-025-16](tasks/TASK-025-16-odds-secret-files-and-stdout-logging.md) | File-backed Odds API keys и stdout-логи | red/green, secret mounts, review | in_progress; код и review готовы, runtime gate открыт |
| [TASK-025-17](tasks/TASK-025-17-promoted-feature-contract.md) | Feature config из promoted bundle | basic→advanced, invalid contract, review | in_progress; код и review готовы, runtime gate открыт |
| [TASK-025-12](tasks/TASK-025-12-release-compose-gate.md) | Исправить Compose release gate | новый API/dispatcher contract и память | done; PR CI в TASK-025-9 |
| [TASK-025-10](tasks/TASK-025-10-run-summary-producers.md) | Full run summary producers and coverage | same-run counters, n/a denominator, football fixture | done |
| [TASK-025-11](tasks/TASK-025-11-telegram-calendar.md) | Public NHL calendar in Telegram | 08:00, all horizons, no prediction, bot→API test | done |
| [TASK-025-4](tasks/TASK-025-4-schedule-control.md) | Persisted schedule, manual control, dispatcher | admin auth, races, restart, catch-up | done; production activation в TASK-025-9 |
| [TASK-025-5](tasks/TASK-025-5-telegram-experience.md) | Telegram calendar, admin controls, notifications, code-based E2E | 08:00, auth, idempotency, bot→API | done; delivery activation в TASK-025-9 |

Operations release gate зафиксирован в TASK-025-9. Running v1.2.4 API/bot
healthy, календарь 30 суток содержит 187 матчей с coverage `complete`;
схема 0017. Serving rollback на v1.2.4 совместим, но его Data Cycle не
является работающим rollback target. Для исправленного v1.2.5 кандидата
нужны tag/evidence, свежий backup, compatible model bundle и успешный цикл.

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
