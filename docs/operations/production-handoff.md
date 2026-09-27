# Передача сервиса в эксплуатацию: v1.2.2 candidate

> Фактическое состояние на 2026-09-27: v1.2.1 частично развёрнут на VPS,
> первый NHL Data Cycle завершился `failed/source_fetch_failed`, оба NHL timer
> выключены. Исправления в TASK-025-13 / PR #42 слиты в `main`; tag v1.2.2
> указывает на проверенный commit. Этот handoff не подтверждает
> production acceptance.

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting
- Canonical repository: Xieveer/sports-probabilistic-forecasting
- Инициатива: EPIC-025, TASK-025-9.
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- source_tag: `v1.2.2` (выпуск подтверждён владельцем).
- source_commit: `3f2b4bb94421bdc00aa1d5185bdfaaf30a94acee`.
- evidence_tag: `v1.2.2-evidence.2` (candidate до повторного evidence gate).

Первый immutable `v1.2.2-evidence.1` завершился ошибкой валидации handoff:
отсутствовали ссылки и exact image evidence. Он остаётся неизменным;
исправления записаны только в `v1.2.2-evidence.2`.

## Подтверждённые release artifacts

- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36312049914
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36312049906
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36312177063
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36312177063/job/108600952503
- postgres: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`
- api: published linux/amd64 scan provenance `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:2f6ec243050f0b3511fa6c44d78cd721589a1eca59dfb6e924af7762bdc9e90c`
- worker: published linux/amd64 scan provenance `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:806f67832dfeaeb6eeef24d2b401ead8f8e81283c48d9c145fa857ce12a26546`
- telegram_bot: published linux/amd64 scan provenance `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:fb1afdb415a842282276a298dfa30448eadffefff2c9fa4f4f0ee6d72326fb4b`
- archive_sync: published linux/amd64 scan provenance `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:85516f66f9da6b70b257ce23b066878f78b4131dd36a39f7d9259240dda956d0`

Этот handoff готовит исправленный patch release после неуспешного первого
цикла v1.2.1. Теги v1.2.0 и v1.2.1 неизменны. CI/evidence v1.2.1,
production backup и ограниченный rollout выполнены; первый Data Cycle failed.
Tag pipeline `36312177063` завершился успешно, включая security, isolated
first-rollout, публикацию и проверку exact image digests. Для v1.2.2 ещё
нужны проверенный immutable evidence manifest и runtime acceptance.

## Идентификация и ответственность

Релиз добавляет календарь NHL на 0–30 суток независимо от прогнозов,
готовность событий, future odds, историю и управление единым Data Cycle через
Telegram, защиту от второго исполнителя и итоговые уведомления. Футбольный
контракт проверяется на fixture; футбольный production pipeline не включается.
Ручная команда запускает новый цикл, не перезапуская службы.

Production VPS сейчас на v1.2.1 commit
`0c56bf10d52e9802d75627988605f455714cef96`: API, bot и PostgreSQL
healthy, Alembic head `0017_data_cycle_notification_outbox`, оба NHL timer
disabled. Первый run `5d9be516-13b6-4ea7-9709-0fbe26b1b649` terminal
`failed/source_fetch_failed`; уведомление доставлено. Перед v1.2.2 rollout
повторить привилегированный preflight и убедиться, что второго executor нет.

## Runtime и конфигурация

Compose получает только immutable IMAGE@sha256:DIGEST из verified manifest и
server-side secrets через `*_FILE` paths. DB URL, token, service key, Telegram
IDs и пароли не передаются в Git, handoff, логи или чат. Контур остаётся
private, без host ports; application runtime UID/GID 10001:10001.

Operations проверяет метаданные secret files и конфигурацию
SF_CONTROL_DATABASE_URL_FILE, SF_CONTROL_API_KEY_FILE,
BOT_CONTROL_API_KEY_FILE, BOT_NOTIFICATION_DESTINATIONS_FILE и
SF_DATA_CYCLE_NOTIFICATION_ALIASES без чтения значений. Каждый безопасный
destination alias должен соответствовать ровно одному Telegram chat ID в
защищённом bot-only JSON file. Outbox хранит alias и run ID, но не chat ID.
Пустой или несогласованный alias map блокирует включение уведомлений.

Новая topology описана в docs/operations/production-runtime-topology.md:
отдельные DB роли для API reader, control API и Worker; dispatcher опрашивает
сохранённое расписание и запускает UUID unit. По умолчанию NHL 10:00
Europe/Moscow с интервалом 24 часа; уменьшение интервала возможно только
после измерения полного цикла и source quota. Перед activation проверить
docker compose config, bash syntax и systemd-analyze verify.

## Healthcheck и smoke-проверка

После ограниченного rollout проверить /health и /ready, NHL calendar API на
0/7/30 суток, coverage freshness и event readiness. Кодовый smoke Telegram
проверяет публичный календарь без прогнозов, административные status/history,
schedule и manual run без второго активного run. Сверить terminal run/stages,
summary, future odds и одно итоговое сообщение с тем же run ID. Первый полный
цикл должен подтвердить фактическое 30-дневное покрытие; успешный job без
свежего календаря не считается готовностью NHL.

Operations запускает make acceptance-check только с утверждёнными runtime
inputs после health/smoke. Production bot token и chat ID не выводятся.
Старый sports-forecast-canonical-refresh@nhl.timer остаётся выключенным.
После initial smoke включить только
sports-forecast-data-cycle-dispatcher.timer, проверить следующий trigger,
затем подтвердить первый плановый NHL run и уведомление администратору.

Stop criteria: crash loop, ошибка БД или миграции, отсутствующий verified
backup, неверный image/manifest, не-200 health/readiness, второй executor,
неполное 30-дневное coverage, несогласованные aliases либо превышение quota.

## Данные и совместимость

Перед v1.2.2 rollout повторить privileged preflight по operations runbook.
Fresh root-only PostgreSQL `pg_dump -Fc` от 2026-09-27 10:17 UTC
(29 312 570 bytes, SHA-256
`996527c5880e468cdf24cd94861dd5c429a96a19ca6e6718f6512095e59d5c19`)
прошёл catalog check, изолированное восстановление на exact PostgreSQL image
и off-host download/hash. Дополнительная копия на машине владельца сверена
по SHA-256. Bucket retention/encryption текущий
service account не может прочитать. Это открытый operational risk.

Фактический Alembic head перед и после v1.2.2 должен остаться
`0017_data_cycle_notification_outbox`: hotfix не добавляет миграций.
Повторно применить idempotent `database_roles` grant bootstrap из нового API
image и подтвердить `sf_control_api` INSERT на `executor_generation`.
Сохранить точные running v1.2.1 digests и конфигурацию для возврата serving
API/bot при ошибке; v1.2.1 Data Cycle не является работающим rollback target.

## Наблюдаемость

В production change record зафиксировать UTC-время, source commit, running
image IDs/digests, restart counts, безопасные failure codes, migration head,
backup checksum, последний/первый Data Cycle run ID, 30-дневное coverage,
timer last/next trigger и результат notification. Не публиковать полные
Docker/DB логи, external payload или значения secrets. Истёкший heartbeat
сам по себе не разрешает нового исполнителя: recovery требует host stop proof.

## Артефакт и откат

После независимого review и terminal PR CI
Reviewer ставит annotated tag v1.2.2 на проверенном commit main. Tag pipeline
должен завершить CI, Security,
isolated first-rollout contract, публикацию linux/amd64 images, scan и
provenance. Release owner запускает manual evidence gate с
--handoff docs/operations/production-handoff.md; Operations сверяет exact
digests с approved manifest. Mutable tag не служит runtime identifier.

Действующий root-owned deploy wrapper пока разрешает только v1.1.22 и не
применим к v1.2.2. Operations использует временный audited operator access и
пошаговый runbook либо сначала обновляет wrapper отдельным review. До
успешного ручного цикла dispatcher timer остаётся выключенным.

Для serving rollback сохранить verified v1.2.1 API/bot digests; их работа на
схеме 0017 уже наблюдалась. Возврат v1.2.1 source-acquirer запрещён, пока
четыре runtime-дефекта не исправлены. Destructive downgrade БД запрещён;
восстановление backup требует остановки writers и оценки записей после
снимка.

## Нерешённые вопросы

Для GO ещё нужны verified release manifest,
подтверждение backup retention либо явно принятое исключение, измерение
runtime/quota, полный ручной run с 30-дневным coverage и первый плановый
NHL run. Exact deployed revision и smoke фиксирует Operations; после них
закрывается TASK-025-9.
