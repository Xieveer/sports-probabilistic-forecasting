# Передача сервиса в эксплуатацию: v1.2.15 candidate

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting.
- Инициатива: [EPIC-025](../backlog/EPIC-025-bot-schedule-readiness.md);
  исправления [TASK-025-28](../backlog/tasks/TASK-025-28-acceptance-docs-response.md),
  [TASK-025-29](../backlog/tasks/TASK-025-29-idempotent-archive-sync.md) и
  [TASK-025-30](../backlog/tasks/TASK-025-30-future-odds-production.md) и
  [TASK-025-31](../backlog/tasks/TASK-025-31-control-stall-mark.md) и
  [TASK-025-32](../backlog/tasks/TASK-025-32-archive-sync-host-network.md),
  [TASK-025-33](../backlog/tasks/TASK-025-33-nhl-preseason-model-boundary.md) и
  [TASK-025-34](../backlog/tasks/TASK-025-34-data-cycle-source-first.md) и
  [TASK-025-36](../backlog/tasks/TASK-025-36-first-rollout-source-first-lifecycle.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- Целевая среда: production VPS `ops-prod-01`; версия: `1.2.15`.
- source_tag: `v1.2.15` (annotated, exact merged commit).
- source_commit: `774602cb3d2db8ce65b4411637ff86e057fc76ec`.
- evidence_tag: `v1.2.15-evidence.1` (создаётся после проверки evidence).
- PR: https://github.com/Xieveer/sports-probabilistic-forecasting/pull/57.
- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36931498144.
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36931498140.
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36931948706.
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36931948706/job/110605048556.
- Tag pipeline завершился успешно: first-rollout, публикация tested OCI,
  linux/amd64 manifest, scan и provenance для каждого application image.

- postgres: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94` — без изменения.
- api: `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:f06373e8dd1bc30542d81c6596619362640e40530976ef25d3a62d05072b8514` — published linux/amd64 scan provenance.
- worker: `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:7e023a4b89e38ffb32e18bf6c91c6b67f0bbd16ad4f69460a63e0df006faf311` — published linux/amd64 scan provenance.
- telegram_bot: `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:f18ea827634be047f2a0c30e508f446efcf48d9133521584d7551945c59b6ac8` — published linux/amd64 scan provenance.
- archive_sync: `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:0dad0feb0d2375e0879c5dec24442d9b5d38619e691713af589a0790729a7543` — published linux/amd64 scan provenance.

## Идентификация и ответственность

В production установлена v1.2.12. Последний ручной NHL run
`7ae3909e-73f7-473b-ab54-22909fda2cad` завершён `partial_success`:
обязательные стадии и archive sync успешны, future odds не найдены.
Активных запусков нет, оба NHL timer выключены. Кандидат v1.2.15 меняет
порядок на source/canonical → verified Object Storage → features → DB,
убирает запрос future odds из ежедневного run и допускает в NHL-модель
только `regular`/`playoffs`. Source/canonical хранят остальные типы.
Вероятности и текущие котировки связываются в `/predict` при запросе.
Выпущенная модель не переобучается.
Тег v1.2.13 остался неизменным: его release pipeline завершился ошибкой
first-rollout Worker, поэтому образы не были опубликованы и VPS не менялся.
Причина correction cycle — устаревшее `game_type=R` в тестовом source fixture,
которое новый NHL-фильтр исключил целиком. Исправление fixture и проверка
его прохождения через clean вошли в v1.2.14. Tag pipeline v1.2.14 также
остановился на first-rollout Worker до публикации образов: сценарий не создал
Data Cycle run и подготовленный immutable snapshot, требуемые новым Worker.
Исправление тестового жизненного цикла входит в v1.2.15; оба прежних тега
остаются неизменными и не являются основанием deployment.
Изолированный full first-rollout на пяти OCI artifacts v1.2.14 с обновлённым
host runner прошёл: два архива remote-verified до Worker, повторный Worker
идемпотентен, API, календарь и бот готовы. Для локального незакоммиченного
diff временно обойдена только проверка clean worktree; exact v1.2.15 tag
pipeline должен повторить gate без обхода.

v1.2.10 подняла API, Telegram bot и PostgreSQL, но ручной Data Cycle
`c729bdd0-7ea5-405d-ba71-ae2c2f68b5e2` завершил systemd unit с кодом 1:
после публикации 1 834 прогнозов archive-sync получил `ReadTimeoutError`.
В БД run остался `running/archive_sync`, outbox пуст. Оба NHL timer выключены.
Причина и остановка записаны в Operations Agent change record
`docs/changes/2026-09-29-v1.2.10-interrupted-rollout.md` его репозитория.
Однократный dispatcher tick 2026-09-29 18:29 UTC тоже завершился кодом 1:
Control API использовал `SELECT FOR UPDATE` для `data_cycle_runs` без
необходимого `UPDATE` grant. Run остался `running`, heartbeat 16:54:55 UTC;
recovery не началось. TASK-025-31 устраняет row lock, сохраняя узкую
атомарную `SECURITY DEFINER` функцию и прежние grants.

v1.2.11 ограничила повторную передачу уже проверенных архивов и сетевые
таймауты, даёт API file-backed ключи The Odds API, отделяет ежедневный сбор
будущих коэффициентов от исторического OddsStore backfill и исправляет
acceptance для HTML `/docs` и исправляет вызов recovery у Control API.
Схема БД, права ролей и веса модели не меняются. В production v1.2.11
API/bot/DB здоровы, но новый ручной run
`47ebfeb2-5113-465d-9a8e-92f709370639` остаётся `running/archive_sync`:
штатный контейнер через Docker bridge повторяемо не завершает TLS handshake
к Object Storage. Оба NHL timer выключены. Host S3 client записал и проверил
первый artifact, но durable state остался `failed`, а второй artifact не
передан. Операционное evidence —
`docs/changes/2026-09-30-v1.2.11-archive-network-diagnosis.md` в репозитории
Operations Agent. v1.2.12 переводит только `archive-sync` на host network по
[ADR-027](../architecture/adr/ADR-027-archive-sync-host-network.md).

## Runtime и конфигурация

Используются только immutable `IMAGE@sha256:DIGEST`, UID/GID `10001:10001`,
Compose secret mounts и прежние лимиты памяти. API получает четыре
`ODDS_API_KEY_*_FILE`/`ODDS_API_KEY_FILE`, как Worker; Telegram bot получает
коэффициенты через API без доступа к этим ключам. Production profile содержит
только `*_FILE` paths для credential, без plain-text значений; в нём заданы
`SF_APP_VERSION=1.2.15` и `SF_DATA_ODDS_ENABLED=false`. Исторический
backfill и запрос будущих коэффициентов не входят в ежедневный runner.
Значения ключей и полный rendered Compose не сохранять
в логи/evidence.

Только `archive-sync` получает host network. До production запуска
проверить отсутствие listener, Docker socket, DB secrets и зависимостей от
Compose DNS; сохранить previous Compose и проверить доступные localhost
службы хоста. Sync остаётся non-root, с read-only rootfs, без capabilities
и повышения привилегий. Остальные services сохраняют bridge.

Последний run уже terminal. Перед новым запуском повторно проверить отсутствие
активных run и работающего refresh unit. Прямое изменение БД запрещено.
Пока ручной цикл не принят, оба NHL timer остаются выключенными.

## Healthcheck и smoke-проверка

После установки exact source tag/images/model wrapper проверить `healthy`,
restart counts, `/health`, `/ready`, HTML `/docs`, JSON `/openapi.json`,
календарь NHL и bot heartbeat. Выполнить один новый ручной Data Cycle и
подтвердить: `calendar`, `quality`, `archive_sync`, `predictions`,
`publication` успешны в таком порядке; ровно два artifact текущего `run_id`
получили remote `verified` до Worker, а provenance прогнозов ссылается на
этот canonical artifact; `data_odds` помечена `skipped`, без запроса к
провайдеру; итог run — `success`, terminal outbox доставлен один раз.
Проверить отсутствие preseason и иных NHL-типов в модельном входе, при
сохранении их в архиве и календаре.

Проверить `/predict/upcoming/nhl?...&live_pinnacle=true`: API возвращает
`live_odds_status=ok` и численные Pinnacle поля хотя бы для доступных матчей;
`live_pinnacle=false` не обращается к провайдеру. Пользовательский Telegram
путь должен показывать коэффициенты в карточке прогноза. Отсутствующие
линии отображаются явно, без фиктивных цен.
Исполнить `make acceptance-check` с защищёнными runtime inputs; script не
печатает payload/секреты. До включения ежедневного расписания проверить
настройку времени/интервала в БД, затем включить только dispatcher timer и
подтвердить next trigger, один плановый run и его уведомление. Legacy timer
остаётся выключенным. При любой новой production ошибке остановиться и
передать пользователю факты до retry/rollback.

## Данные и совместимость

Перед v1.2.15 rollout подтвердить свежий root-only PostgreSQL backup,
изолированный restore и off-host копию по SHA-256. Перед v1.2.13 rollout
этот gate уже был выполнен, но непосредственно перед switch нужно повторно
проверить checksum и отсутствие новых DB writes. Предыдущий проверенный
backup перед v1.2.10 сохранён; он не заменяет свежий gate после записи
1 834 прогнозов. Alembic остаётся `0017_data_cycle_notification_outbox`.
Preflight 2026-10-01 20:31 UTC создал root-only dump
`/var/backups/sports-forecast/postgres/pre-v1.2.13-20261001T203108663751207.dump`
(57 956 170 bytes, SHA-256
`3c182d88a49a739105c6afd7b66fe92f9f5796fb34cf40c699503ee9005e9184`).
Изолированный restore без сети на exact PostgreSQL image подтвердил таблицы,
22 544 canonical events и 1 882 predictions; off-host копия после обратного
скачивания совпала по размеру и SHA-256. Перед v1.2.15 switch проверить, что
этот backup остаётся актуальным; при новых DB writes создать новый.
Для модели собран новый content-addressed wrapper
`sha256:453520a3521925d1bf08b6be04d8436dd53394d6973f8ce2a217d14732454413`
с `app_version=1.2.15` и exact source commit; manifest SHA-256
`a5e5ab767d8ecb95508c4efbca5fb0e4ef5ebe850da46b0df2b93a64c557635c`.
`verify_model_bundle` локально и на VPS внутри exact опубликованного Worker
image прошёл; CatBoost загрузил 489 признаков, совпадающих с `features.txt`.
Bundle и candidate profile размещены в root-only staging, active model
pointer и работающие сервисы не менялись. Включение historical backfill не
производится. Локальный ключ Odds API ответил HTTP 200 на один NHL запрос;
доступность именно серверного secret проверяется отдельно без вывода значения.

## Наблюдаемость

В production change record фиксировать UTC, commit/tag/manifest digest,
running image digests, backup hash, bundle ID, container restarts/OOM, RAM,
disk, run/stage/failure code, provider attempts/quota headers, число прогнозов,
odds coverage, архивные verification states, notification delivery и
timer last/next trigger. Не сохранять полные внешние ответы и credentials.

## Артефакт и откат

После независимого review и terminal PR CI Reviewer поставил annotated
`v1.2.15` на exact merged commit `main`. Tag pipeline завершил CI,
Security, first-rollout, публикацию linux/amd64 images, scan и provenance.
Release evidence фиксирует source/evidence tags, полный manifest, model
wrapper и ссылки CI; `make verify-release-evidence` проверяет их вместе с
этим handoff через `--handoff docs/operations/production-handoff.md`.
Operations Agent сохраняет root-only прежние env/images/model
pointer и свежий backup. Предыдущие serving refs v1.2.12 допускают откат
без DB downgrade, но при новой ошибке решение об откате принимает пользователь.

## Нерешённые вопросы

До production GO остаются: независимая проверка и immutable release evidence,
свежий backup/restore/off-host, проверка серверного Odds API secret для
`/predict` и ограниченный ручной цикл. Статус candidate означает готовый контракт
проверки, а не подтверждённый production успех.
