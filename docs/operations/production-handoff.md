# Передача сервиса в эксплуатацию: v1.2.11 candidate

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting.
- Инициатива: [EPIC-025](../backlog/EPIC-025-bot-schedule-readiness.md);
  исправления [TASK-025-28](../backlog/tasks/TASK-025-28-acceptance-docs-response.md),
  [TASK-025-29](../backlog/tasks/TASK-025-29-idempotent-archive-sync.md) и
  [TASK-025-30](../backlog/tasks/TASK-025-30-future-odds-production.md) и
  [TASK-025-31](../backlog/tasks/TASK-025-31-control-stall-mark.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- Целевая среда: production VPS `ops-prod-01`; версия: `1.2.11`.
- source_tag: `v1.2.11` (annotated, exact merged commit).
- source_commit: `c4d1487034f4d9a44bbac406b719b325e198a9d9`.
- evidence_tag: `v1.2.11-evidence.1` (создаётся после проверки evidence).
- PR: https://github.com/Xieveer/sports-probabilistic-forecasting/pull/53.
- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36617763368.
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36617763468.
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36617840641.
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36617840641/job/109577475412.

Tag pipeline завершился успешно: first-rollout прогнал чистую установку,
схему `0017`, Worker, два archive-sync artifacts, API и bot health без
рестартов. Опубликованные digest совпали с проверенными OCI artifacts;
каждый application image имеет linux/amd64 manifest, scan и provenance:

- postgres: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94` — без изменения.
- api: `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:b952e17414c0bd1b82eb3fe6e1ad2094da3698fd917f2ce509f831abc058b5f8` — published linux/amd64 scan provenance.
- worker: `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:2a1bdeb08f3936fa521e0a29d6498c46bb4f462433a68e1c860f6264f0e127d6` — published linux/amd64 scan provenance.
- telegram_bot: `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:cf62257699b362be759d56324560c279f8e4ead72e39d893e1fe1153ecaa6f15` — published linux/amd64 scan provenance.
- archive_sync: `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:ade257d38420aed37ce678e506f9599f2c6ccc124a8d0704915c08b5cd867508` — published linux/amd64 scan provenance.

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

v1.2.11 ограничивает повторную передачу уже проверенных архивов и сетевые
таймауты, даёт API file-backed ключи The Odds API, отделяет ежедневный сбор
будущих коэффициентов от исторического OddsStore backfill и исправляет
acceptance для HTML `/docs` и исправляет вызов recovery у Control API.
Схема БД, права ролей и веса модели не меняются.

## Runtime и конфигурация

Используются только immutable `IMAGE@sha256:DIGEST`, UID/GID `10001:10001`,
Compose secret mounts и прежние лимиты памяти. API получает четыре
`ODDS_API_KEY_*_FILE`/`ODDS_API_KEY_FILE`, как Worker; Telegram bot получает
коэффициенты через API без доступа к этим ключам. Production profile содержит
только `*_FILE` paths для credential, без plain-text значений; при rollout задаются
`SF_APP_VERSION=1.2.11` и `SF_DATA_ODDS_ENABLED=true`. Исторический
backfill не входит в ежедневный runner; Worker выполняет один batch будущих
коэффициентов на run. Значения ключей и полный rendered Compose не сохранять
в логи/evidence.

До нового запуска штатный host recovery должен завершить старый run после
проверки `MainPID=0`, отсутствия его работающих контейнеров и совпадения
owner/generation. Затем сверяются terminal `failed/archive_sync_failed`,
outbox и отсутствие active run. Прямое изменение БД запрещено. Пока ручной
цикл не принят, оба NHL timer остаются выключенными.

## Healthcheck и smoke-проверка

После установки exact source tag/images/model wrapper проверить `healthy`,
restart counts, `/health`, `/ready`, HTML `/docs`, JSON `/openapi.json`,
календарь NHL и bot heartbeat. Выполнить один ручной Data Cycle и подтвердить:
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

Свежий root-only PostgreSQL dump после записи 1 834 прогнозов создан
2026-09-29 19:06 UTC: 57 929 242 bytes,
SHA-256 `86cb645facdf4217069954597350c4aae2750f99af530abc24ed9c044977f27b`.
Изолированный restore под 1 GiB/no swap и off-host download/byte comparison
прошли; подробности — в Operations Agent backup gate. Alembic остаётся
`0017_data_cycle_notification_outbox`.
Локально собран content-addressed model wrapper
`sha256:a10450b0e2735032fe4d291e65521e189d14d387889131350c7fc45195424751`
с `app_version=1.2.11` и exact source commit; SHA-256 весов, `features.txt`
и `deploy.yaml` совпадают с предыдущим verified bundle. Exact Worker image
проверит wrapper перед promotion. Historical backfill не включается.
Все четыре серверных Odds API secret файла побайтово синхронизированы с
локальными 2026-09-29 19:19 UTC; один ограниченный NHL запрос с бесплатным
ключом вернул HTTP 200 и 496 оставшихся запросов. Платные ключи отключены;
их provider запросы не выполнялись. Значения ключей в evidence не входят.

## Наблюдаемость

В production change record фиксировать UTC, commit/tag/manifest digest,
running image digests, backup hash, bundle ID, container restarts/OOM, RAM,
disk, run/stage/failure code, provider attempts/quota headers, число прогнозов,
odds coverage, архивные verification states, notification delivery и
timer last/next trigger. Не сохранять полные внешние ответы и credentials.

## Артефакт и откат

После независимого review и terminal PR CI Reviewer поставил annotated
`v1.2.11` на exact merged commit `main`. Tag pipeline завершил CI,
Security, first-rollout, публикацию linux/amd64 images, scan и provenance.
Release evidence фиксирует source/evidence tags, полный manifest, model
wrapper и ссылки CI; `make verify-release-evidence` проверяет их вместе с
этим handoff через `--handoff docs/operations/production-handoff.md`.
Operations Agent сохраняет root-only прежние env/images/model
pointer и свежий backup. Предыдущие serving refs v1.2.10 допускают откат
без DB downgrade, но при новой ошибке решение об откате принимает пользователь.

## Нерешённые вопросы

Независимый Reviewer проверил manifest, exact source tag/commit, terminal
CI/Security/Docker и first-rollout, опубликованные четыре image digests,
backup/restore/off-host и серверный Odds API credential gate по Operations
evidence. Блокирующих findings нет. Проверенный content commit:
`8cde74015cf51a1655a8e291f9854fbbbcca9e6f`. Это release evidence review;
фактические recovery, Data Cycle, Telegram и scheduler gates ещё открыты.

До production GO остаются: terminal CI immutable release evidence,
проверка wrapper в exact Worker image, установка проверенных refs на VPS,
штатное завершение старого run и ограниченный ручной цикл с odds/Telegram.
Ежедневный timer включается только после его acceptance. Статус candidate означает готовый контракт
проверки, а не подтверждённый production успех.
