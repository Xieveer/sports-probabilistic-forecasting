# Передача сервиса в эксплуатацию: v1.2.6 candidate

> Фактическое состояние на 2026-09-27: API и Telegram-бот v1.2.5 healthy,
> PostgreSQL healthy, NHL календарь содержит 187 матчей на 30 дней с
> coverage `complete`. Три Odds API ключа дали HTTP 401 `INVALID_KEY`;
> два ручных v1.2.5 run завершились ошибкой из-за старого systemd profile,
> который исправлен и проверен. Оба NHL timer выключены. Production
> acceptance открыт.

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting
- Canonical repository: Xieveer/sports-probabilistic-forecasting
- Инициатива: [EPIC-025](../backlog/EPIC-025-bot-schedule-readiness.md),
  [TASK-025-9](../backlog/tasks/TASK-025-9-release-readiness.md),
  [TASK-025-18](../backlog/tasks/TASK-025-18-optional-future-odds.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- source_tag: `v1.2.6`.
- source_commit: `f5697d388328ea0446fb4cd85cff0800aa0c6b4f`.
- evidence_tag: `v1.2.6-evidence.1`.
- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36327167297
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36327167332
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36327191554
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36327191554/job/108642959557

Проверенные runtime references для production manifest:

- postgres: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`.
- api: `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:776e53a504afb754e43333d3865ac21f6908a761a0b3d5b9b3f818f2c5cbe8ea` — published linux/amd64, scan, provenance.
- worker: `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:8c1db5a1e317c0dcb6ea816baa8d556be82d4922400791a09e68ff97616ff231` — published linux/amd64, scan, provenance.
- telegram_bot: `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:446bf9906989cc8700a4ee85307105753a71f3f45871a06b5df05b70ae43a83f` — published linux/amd64, scan, provenance.
- archive_sync: `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:98cdc570f38cdb2b11a30905f30f94dadca535188ab29432d1641f6ecf24c3bf` — published linux/amd64, scan, provenance.

По решению владельца v1.2.6 добавляет явный режим без future odds. Он
пропускает запрос к провайдеру, оставляет готовность коэффициентов `missing`
и публикует календарь/прогнозы с итогом `partial_success`, если остальные
обязательные стадии успешны. По умолчанию поведение odds остаётся включённым.
Схема БД не меняется. Теги v1.2.0–v1.2.5 неизменны.
Также v1.2.6 исправляет счётчики publication внутри транзакции с
`autoflush=False`: изолированный replay v1.2.5 записал 1 834
prediction rows, в том числе 187 matching eligible future events, но
сохранил нулевые counters до commit.
Повторный internal-only replay с полной копией source state завершил Worker
exit 0 и source archive export; все 187 eligible future events получили
committed predictions. Это подтверждает путь публикации, но не заменяет
production manual run и исправление in-transaction counters.

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

Перед v1.2.6 run Operations сверяет **фактический** systemd
`SF_COMPOSE_ENV_FILE` и `/etc/sports-forecast/refresh/nhl.env`:
`SF_APP_VERSION`, все пять image refs, tournament/market/spec/algorithm/
features selectors и `SF_DATA_ODDS_ENABLED=false`. Проверка должна
сопоставить их с exact manifest и promoted `deploy.yaml`, а затем пройти
Compose dry-run. Ошибка или неизвестное значение switch блокирует запуск.
Это закрывает preflight gap v1.2.5, где проверялся только
`production.env.candidate`, но executor читал другой файл.

Текущий v1.2.5 model bundle
`sha256:108eb6db273f284cb605d2800df1ccc8d1cd73da018b306c132c17926dafd69e`
содержит одобренные веса и 489 features. Operations уже staged новый
content-addressed wrapper `sha256:9d193525d816e55e40b4dd95fb875e39058e0154cebbc5f4668d87846f002123`
с `app_version=1.2.6`; manifest SHA-256
`ed748e385bcfc4c128c77c8e223413ba45a0b4fb7c859fa3ed2719e43f123d17`.
Три model file SHA и набор из 489 признаков совпали с текущим bundle;
`current`/`previous` pointers не менялись. Загрузка wrapper и feature
contract в exact v1.2.6 Worker остаются открытым gate. Для rollback
сохранить v1.2.5 pointer и serving digests.

## Healthcheck и smoke-проверка

После ограниченного rollout сверить running digests, healthy/restart counts,
`/health`, `/ready`, NHL calendar API 0/7/30, readiness и admin
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

Перед v1.2.6 rollout создать свежий root-only `pg_dump -Fc` после двух
failed v1.2.5 runs, проверить checksum/catalog, isolated restore на exact
PostgreSQL image, off-host upload/download hash и третью локальную копию.
Последний проверенный post-failure dump: 57 854 273 bytes,
SHA-256 `a77fbf3b911ddaec280c160df2e098fa32d6d1922c9f17c6a3804e3fccf2e6be`,
Alembic 0017, 22 496 canonical events, пять run records; off-host и
локальная копии совпали. Перед новым rollout проверить актуальность.
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

Annotated `v1.2.6` указывает на exact merged commit
`f5697d388328ea0446fb4cd85cff0800aa0c6b4f`. Merge CI/Security и
tag Docker pipeline завершились успешно; first-rollout contract,
linux/amd64 images, scan и provenance прошли. Отдельный immutable
evidence commit/tag `v1.2.6-evidence.1` проходит независимый review;
validator вызывается с `--handoff docs/operations/production-handoff.md`.
После terminal evidence CI Operations сверяет manifest и только затем
меняет VPS по runbook в `operations-agent`, сохранив root-only rollback копии.

## Нерешённые вопросы

Для GO остаются terminal evidence CI, загрузка staged wrapper в exact
v1.2.6 Worker, true OFF replay на изолированной копии данных,
актуальный backup/restore/off-host evidence, production rollout и полный
ручной цикл без odds, затем первый плановый NHL run. TASK-025-9 и EPIC-025
остаются `in_progress` до этих gates. Действующие Odds API ключи
отсутствуют; повторное включение odds требует отдельного provider preflight.
