# Передача сервиса в эксплуатацию: v1.2.7 candidate

> Фактическое состояние на 2026-09-27: API и Telegram-бот v1.2.5 healthy,
> PostgreSQL healthy, NHL календарь содержит 187 матчей на 30 дней с
> coverage `complete`. Три Odds API ключа дали HTTP 401 `INVALID_KEY`;
> два ручных v1.2.5 run завершились ошибкой из-за старого systemd profile,
> который исправлен и проверен. Serving v1.2.6 откатили после calendar 500:
> у API role нет SELECT на `data_cycle_stage_results` и `data_cycle_runs`.
> Оба NHL timer
> выключены. Production acceptance открыт.

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting
- Canonical repository: Xieveer/sports-probabilistic-forecasting
- Инициатива: [EPIC-025](../backlog/EPIC-025-bot-schedule-readiness.md),
  [TASK-025-9](../backlog/tasks/TASK-025-9-release-readiness.md),
  [TASK-025-18](../backlog/tasks/TASK-025-18-optional-future-odds.md),
  [TASK-025-20](../backlog/tasks/TASK-025-20-calendar-stage-read-grant.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- source_tag: `v1.2.7`.
- source_commit: `455a7a52b78aacc8ab1bf716bcc7411e390799a5`.
- evidence_tag: `v1.2.7-evidence.1`.
- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36332668406
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36332668416
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36332705281
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36332705281/job/108658533821

Проверенные runtime references для production manifest:

- postgres: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`.
- api: `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:24ae057a28ec496336bba0d2f04e158a7b1474d47afefc6b49de752929d51226` — published linux/amd64, scan, provenance.
- worker: `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:0a20ab5d8545754dc04c5ae5559208c028690071ed75e6228f0ddc82cf95c98d` — published linux/amd64, scan, provenance.
- telegram_bot: `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:f49422fb88048f0a0f8baf5df05fcd58b67391433c0baef52f9a846ce5c09afd` — published linux/amd64, scan, provenance.
- archive_sync: `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:8520f90dc6b6972c0040b2420447e340d77f65b36ed183c6a58b2404aec375a0` — published linux/amd64, scan, provenance.

По решению владельца v1.2.6 добавил явный режим без future odds. Он
пропускает запрос к провайдеру, оставляет готовность коэффициентов `missing`
и публикует календарь/прогнозы с итогом `partial_success`, если остальные
обязательные стадии успешны. По умолчанию поведение odds остаётся включённым.
Схема БД не меняется. Теги v1.2.0–v1.2.6 неизменны.
Также v1.2.6 исправляет счётчики publication внутри транзакции с
`autoflush=False`: изолированный replay v1.2.5 записал 1 834
prediction rows, в том числе 187 matching eligible future events, но
сохранил нулевые counters до commit.
Повторный internal-only replay с полной копией source state завершил Worker
exit 0 и source archive export; все 187 eligible future events получили
committed predictions. Это подтверждает путь публикации, но не заменяет
production manual run. Exact v1.2.6 isolated OFF replay завершился Worker
exit 0: 1 834 prediction rows, `predictions_ready=187/187`, odds attempts 0.
Календарь production v1.2.6 после serving switch вернул 500 из-за
отсутствующего `SELECT` на `data_cycle_stage_results` у `sf_api_reader`;
запрос также соединяет её с `data_cycle_runs`, где права тоже нет.
v1.2.7 добавляет оба точечных grant и release smoke exact JOIN; serving
восстановлен на v1.2.5 без запуска manual Data Cycle.

## Идентификация и ответственность

Production serving v1.2.5 API/bot используют exact approved digests,
Alembic head `0017_data_cycle_notification_outbox`. Календарь today
`confirmed_empty`, 7d 34 `complete`, 30d 187 `complete`.
Ручной run `56c0ab25-b17d-496e-bb91-6b85bc6f6521` запустил Worker
v1.2.4 из старого `nhl.env` и завершился `prediction_failed`.
Ручной run `8d2f9806-3ffd-4441-9ba6-db653578a0e1` использовал Worker
v1.2.5, но `SF_ALGORITHM=catboost` не совпал с promoted
`catboost_reg`, поэтому publication не запускалась. Для обоих run host
stop proof, owner-fenced terminalization, один delivered outbox и active0
подтверждены. После второго run все три distinct tier keys проверены
ограниченными probes: HTTP 401 `INVALID_KEY`, quota headers отсутствуют.
Секреты не менялись. Старый и новый NHL timer disabled.

## Runtime и конфигурация

Compose получает только immutable `IMAGE@sha256:DIGEST` из release manifest
и защищённые `*_FILE` paths; значения секретов не попадают в Git, env
контейнера, handoff или логи. API/Worker/bot работают без host ports под
UID/GID `10001:10001`. Alias `nhl_admins` должен совпадать у API, Worker
и bot-only destination map.

Перед v1.2.7 run Operations сверяет **фактический** systemd
`SF_COMPOSE_ENV_FILE` и `/etc/sports-forecast/refresh/nhl.env`:
`SF_APP_VERSION`, все пять image refs, tournament/market/spec/algorithm/
features selectors и `SF_DATA_ODDS_ENABLED=false`. Проверка должна
сопоставить их с exact manifest и promoted `deploy.yaml`, а затем пройти
Compose dry-run. Ошибка или неизвестное значение switch блокирует запуск.
Это закрывает preflight gap v1.2.5, где проверялся только
`production.env.candidate`, но executor читал другой файл.

Текущий v1.2.5 model bundle
`sha256:108eb6db273f284cb605d2800df1ccc8d1cd73da018b306c132c17926dafd69e`
содержит одобренные веса и 489 features. Staged v1.2.6 wrapper
`sha256:9d193525d816e55e40b4dd95fb875e39058e0154cebbc5f4668d87846f002123`
загрузился в exact v1.2.6 Worker; `current`/`previous` pointers не
менялись. Operations staged новый content-addressed v1.2.7 wrapper
`sha256:a408b8b6cc6f7c8ce9ac5098846cfda8737370bd57a242bc9f45255fc7a2a42f`,
manifest SHA-256 `fbafb595b76da1767a36ff9d7abdf30b61e42513efa1736a0308b6ba07dcbc61`;
три file SHA и 489 ordered features совпали с текущим bundle.
`current`/`previous` pointers не переключались. Загрузка staged wrapper
в exact v1.2.7 Worker остаётся runtime gate. Для rollback сохранить
v1.2.5 pointer и serving digests.

## Healthcheck и smoke-проверка

До immutable tag полный локальный first-rollout на clean commit
`85a8a6ffd1f5d5617520f6f853aad9716e93ce5d` прошёл за 121.634 с:
роль API выполнила exact JOIN, HTTP-календарь today/7/30, Worker,
archive-sync и бот прошли; rollback тестовой БД, zero restarts и zero
host ports подтверждены. Redacted evidence SHA-256
`03a5f662664ac84316566615f28a27eefaf83832df96d60f7d51b8ffc8d29c8d`
проверено независимым Reviewer. Tag first-rollout повторно прошёл на
exact merge commit. Это локальное evidence, production acceptance открыт.

После ограниченного rollout **до ручного Data Cycle** сверить running digests,
healthy/restart counts, `/health`, `/ready`, NHL calendar API 0/7/30 под
реальной API role, readiness и admin
status/history/schedule. Кодовый Telegram smoke проверяет публичный
календарь и admin control без второго executor. Один ручной цикл с
`SF_DATA_ODDS_ENABLED=false` должен дать terminal `partial_success`,
нулевые HTTP-запросы к Odds API, 30-дневное coverage, ненулевую публикацию
прогнозов для eligible событий, odds `missing`, archive success и одно
итоговое уведомление с тем же run ID. Длительность и отсутствие overlap
сверяются до включения таймера.

Operations запускает `make acceptance-check` с утверждёнными runtime
inputs после health/smoke. Старый NHL timer остаётся выключенным. Новый
dispatcher timer включать только после успешного ручного цикла; затем
проверить next trigger, первый плановый run и сообщение администратору.
При ошибке timer остаётся выключенным; recovery требует host stop proof,
никаких слепых повторов.

## Данные и совместимость

Перед v1.2.7 rollout проверить актуальность свежего root-only `pg_dump -Fc`,
checksum/catalog, isolated restore на exact PostgreSQL image, off-host
upload/download hash и третью локальную копию. Перед v1.2.6 rollout
дамп 57 840 045 bytes, SHA-256 с префиксом `9e8327ef`, прошёл эти
проверки: Alembic 0017, 22 496 canonical events, шесть run records.
После calendar 500 manual cycle не запускался; Operations повторно сверяет
отсутствие новых writers и фиксирует полный hash в root-only change record.
Bucket retention/encryption текущему service account недоступны.

Схема остаётся на `0017_data_cycle_notification_outbox`; role-bootstrap/
migrator повторяются idempotently только из approved image. Serving rollback
на v1.2.5 возможен по сохранённым digest/env/model pointer. Destructive
downgrade БД запрещён.

## Наблюдаемость

В production change record сохранить UTC, source commit, manifest hash,
running image IDs, restart counts, DB revision, backup hash, bundle ID,
run/stage statuses, coverage, число опубликованных прогнозов, 0 provider
requests в OFF-режиме, notification delivery и timer last/next trigger.
Не публиковать ключи, полные Docker/DB логи или ответы провайдера.

## Артефакт и откат

Annotated `v1.2.7` указывает на exact merged commit
`455a7a52b78aacc8ab1bf716bcc7411e390799a5`. Merge CI/Security и
tag Docker pipeline завершились успешно; first-rollout contract,
linux/amd64 images, scan и provenance прошли. Release owner создаёт
отдельный immutable evidence commit/tag; validator
вызывается с `--handoff docs/operations/production-handoff.md`.
Operations сверяет manifest и только затем меняет VPS по runbook в
`operations-agent`, сохранив root-only rollback копии.

## Нерешённые вопросы

Для GO остаются terminal evidence CI, актуальный backup/restore/off-host
evidence, загрузка staged v1.2.7 model bundle в exact Worker, успешный
production calendar smoke под API role,
полный ручной цикл без odds, затем первый плановый NHL run. TASK-025-9 и
EPIC-025 остаются `in_progress` до этих gates. Действующие Odds API ключи
отсутствуют; повторное включение odds требует отдельного provider preflight.
