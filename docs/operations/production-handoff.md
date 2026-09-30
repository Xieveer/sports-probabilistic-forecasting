# Передача сервиса в эксплуатацию: v1.2.12 candidate

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting.
- Инициатива: [EPIC-025](../backlog/EPIC-025-bot-schedule-readiness.md);
  исправления [TASK-025-28](../backlog/tasks/TASK-025-28-acceptance-docs-response.md),
  [TASK-025-29](../backlog/tasks/TASK-025-29-idempotent-archive-sync.md) и
  [TASK-025-30](../backlog/tasks/TASK-025-30-future-odds-production.md) и
  [TASK-025-31](../backlog/tasks/TASK-025-31-control-stall-mark.md) и
  [TASK-025-32](../backlog/tasks/TASK-025-32-archive-sync-host-network.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- Целевая среда: production VPS `ops-prod-01`; версия: `1.2.12`.
- source_tag: `v1.2.12` (целевой, до release gates не создан).
- Ветка: `initiative/epic-025-archive-network`.
- Source commit, image digests, evidence tag и CI URLs фиксируются в
  отдельном release evidence commit после merge/tag pipelines.

## Идентификация и ответственность

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
`SF_APP_VERSION=1.2.12` и `SF_DATA_ODDS_ENABLED=true`. Исторический
backfill не входит в ежедневный runner; Worker выполняет один batch будущих
коэффициентов на run. Значения ключей и полный rendered Compose не сохранять
в логи/evidence.

Только `archive-sync` получает host network. До production запуска
проверить отсутствие listener, Docker socket, DB secrets и зависимостей от
Compose DNS; сохранить previous Compose и проверить доступные localhost
службы хоста. Sync остаётся non-root, с read-only rootfs, без capabilities
и повышения привилегий. Остальные services сохраняют bridge.

До нового Data Cycle штатный host recovery должен завершить зависший run после
проверки `MainPID=0`, отсутствия его работающих контейнеров и совпадения
owner/generation. Затем сверяются terminal `failed/archive_sync_failed`,
outbox и отсутствие active run. Прямое изменение БД запрещено. Пока ручной
цикл не принят, оба NHL timer остаются выключенными.

## Healthcheck и smoke-проверка

После установки exact source tag/images/model wrapper проверить `healthy`,
restart counts, `/health`, `/ready`, HTML `/docs`, JSON `/openapi.json`,
календарь NHL и bot heartbeat. До recovery штатным sync подтвердить оба
сохранённых artifact: remote content, prefix-specific durable `verified` и
отсутствие TLS timeout из exact release image. Ручная host-запись первого
artifact не считается этим gate. Затем выполнить штатный recovery зависшего
run и проверить terminal outcome/outbox. Выполнить один новый ручной Data Cycle
и подтвердить:
`calendar`, `quality`, `predictions`, `publication`, `archive_sync` успешны;
`data_odds` выполнила запрос и записала попытку/наблюдения; Worker записал
прогнозы; архивы remote-verified; terminal outbox доставлен один раз.
`partial_success` допустим только для отдельных отсутствующих линий при
успешной основной задаче, с явным покрытием и без скрытой ошибки provider.

Проверить `/predict/upcoming/nhl?...&live_pinnacle=true`: API возвращает
`live_odds_status=ok` и численные Pinnacle поля хотя бы для доступных матчей;
`live_pinnacle=false` не обращается к провайдеру. Пользовательский Telegram
путь должен показывать коэффициенты в карточке прогноза, а terminal summary —
покрытие odds. Отсутствующие линии отображаются явно, без фиктивных цен.
Исполнить `make acceptance-check` с защищёнными runtime inputs; script не
печатает payload/секреты. До включения ежедневного расписания проверить
настройку времени/интервала в БД, затем включить только dispatcher timer и
подтвердить next trigger, один плановый run и его уведомление. Legacy timer
остаётся выключенным. При любой новой production ошибке остановиться и
передать пользователю факты до retry/rollback.

## Данные и совместимость

Перед v1.2.12 rollout создать свежий root-only PostgreSQL backup и подтвердить
изолированный restore и off-host копию по SHA-256. Предыдущий проверенный
backup перед v1.2.10 сохранён; он не заменяет свежий gate после записи
1 834 прогнозов. Alembic остаётся `0017_data_cycle_notification_outbox`.
Для модели нужен новый content-addressed wrapper с `app_version=1.2.12`
и exact source commit; содержимое весов, `features.txt` и `deploy.yaml`
сверяется с активным production bundle. Включение historical backfill не
производится. Локальный ключ Odds API ответил HTTP 200 на один NHL запрос;
доступность именно серверного secret проверяется отдельно без вывода значения.

## Наблюдаемость

В production change record фиксировать UTC, commit/tag/manifest digest,
running image digests, backup hash, bundle ID, container restarts/OOM, RAM,
disk, run/stage/failure code, provider attempts/quota headers, число прогнозов,
odds coverage, архивные verification states, notification delivery и
timer last/next trigger. Не сохранять полные внешние ответы и credentials.

## Артефакт и откат

После независимого review и terminal PR CI Reviewer ставит annotated
`v1.2.12` на exact merged commit `main`. Tag pipeline должен завершить CI,
Security, first-rollout, публикацию linux/amd64 images, scan и provenance.
Release evidence фиксирует source/evidence tags, полный manifest, model
wrapper и ссылки CI; `make verify-release-evidence` проверяет их вместе с
этим handoff через `--handoff docs/operations/production-handoff.md`.
Operations Agent сохраняет root-only прежние env/images/model
pointer и свежий backup. Предыдущие serving refs v1.2.10 допускают откат
без DB downgrade, но при новой ошибке решение об откате принимает пользователь.

## Нерешённые вопросы

До production GO остаются: чистое review TASK/EPIC, terminal PR/tag CI,
immutable release evidence и model wrapper, свежий backup/restore/off-host,
штатное завершение старого run, проверка серверного Odds API secret и
ограниченный ручной цикл. Статус candidate означает готовый контракт
проверки, а не подтверждённый production успех.
