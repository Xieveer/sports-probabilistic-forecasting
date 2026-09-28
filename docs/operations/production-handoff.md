# Передача сервиса в эксплуатацию: v1.2.9 candidate

> Фактическое состояние на 2026-09-28: production работает на v1.2.8;
> API, бот и PostgreSQL healthy, `/health` и `/ready` отвечают 200.
> Оба NHL timer выключены. Последний production Data Cycle завершился
> `failed/quality_failed`; новая версия в production ещё не развёрнута.

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting.
- Canonical repository: Xieveer/sports-probabilistic-forecasting.
- Инициатива: [EPIC-025](../backlog/EPIC-025-bot-schedule-readiness.md),
  [TASK-025-22](../backlog/tasks/TASK-025-22-local-quality-parity.md),
  [TASK-025-23](../backlog/tasks/TASK-025-23-pytest-memory-guard.md),
  [TASK-025-24](../backlog/tasks/TASK-025-24-archive-sync-bounded-memory.md),
  [TASK-025-25](../backlog/tasks/TASK-025-25-archive-sync-tmpfs.md),
  [TASK-025-26](../backlog/tasks/TASK-025-26-refresh-inference-memory.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- Целевая среда: production VPS; версия: `1.2.9`.
- source_tag: `v1.2.9`.
- source_commit: `f7156e0d4471fbe1a789b89da5d17c06facc0dbc`.
- evidence_tag: `v1.2.9-evidence.1` (создаётся после проверки manifest).
- PR: https://github.com/Xieveer/sports-probabilistic-forecasting/pull/50.
- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36484643203.
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36484642930.
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36484917017.
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36484917017/job/109141372305.

Tag pipeline terminal `success`; четыре образа опубликованы как immutable
linux/amd64, scan и provenance завершены. Удалённые digest совпали с tested
first-rollout digest:

- postgres: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94` — без изменения.
- api: `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:517813d5da90e721e7250d6b74c924adbbf495210ec0695bf3a65b4db2772a71` — published linux/amd64 scan provenance.
- worker: `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:77044d7418f3179c0a2196a1fe1f7007d29812f3dbdaaf83a1990769e65b3f92` — published linux/amd64 scan provenance.
- telegram_bot: `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:fcb51061c778a01dc43fdb5dc05ed7598b0bf88aabc2c426d7d8de29756b8d4a` — published linux/amd64 scan provenance.
- archive_sync: `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:28ef3ec4cabeb747ef24deb6ef07c2958c8dff11fb69896a3f3ca6701e3d4339` — published linux/amd64 scan provenance.

## Идентификация и ответственность

v1.2.9 исправляет ложный отказ freshness gate на прогнозах, созданных после
начала матча; ограничивает память archive-sync при сравнении больших файлов;
размещает remote verification вне `/tmp=64m`; исключает ненужные train-таблицы
из refresh Worker. Версия и lock согласованы (`pyproject.toml`, `uv.lock`).
Изменений схемы БД, модели, коэффициентов и публичного API нет.

Production preflight: v1.2.8 healthy, Alembic `0017`, оба NHL timer disabled,
последний run `failed/quality_failed`, active runs нет. Production bundle
`sha256:5b3cb6e2ca0b588059de7416a5cbdae1e955e4b9a91b08be51da43684e3640b0`
содержит 489 ordered features и проверенные веса. Для v1.2.9 создан новый
content-addressed wrapper с теми же весами, `app_version=1.2.9` и exact
source_commit/tag; текущий production pointer до release gate не менять.
Локально создан и проверен bundle
`sha256:d4713aa738330d279f1190d46a2311aad140b9500a29ca3b24400ad4d929ec10`
на exact source commit. Его установку на production выполняет только
Operations после подтверждения остальных gates.

## Runtime и конфигурация

Compose получает только immutable `IMAGE@sha256:DIGEST` из release manifest
и защищённые `*_FILE` paths. API, Worker и бот работают без host ports под
UID/GID `10001:10001`. `nhl_admins` одинаков у API, Worker и bot map.
Перед rollout Operations сверяет фактический systemd `SF_COMPOSE_ENV_FILE`
и `/etc/sports-forecast/refresh/nhl.env`: пять image refs,
`SF_APP_VERSION=1.2.9`, tournament/market/spec/algorithm/features selectors,
`SF_DATA_ODDS_ENABLED=false`, source/model/archive roots и Compose dry-run.
Старые и новые NHL timer остаются выключенными до успешного ручного цикла.

## Локальные доказательства

Изолированный PostgreSQL 16 восстановлен из backup перед v1.2.8. На его
истории прежний freshness gate нашёл 1 621 ложный долг по `finished`, новый
вернул `valid=True`, `expired=0`, `missing=0`. Внешний NHL source-acquirer
обновил копию локального source под лимитом 1 GiB до 2026-10-29.
Связанный локальный Data Cycle
`876f0523-3f8c-44b6-95a8-0234b4258fbd` на свежем source и весах
production-модели завершился `partial_success` лишь из-за явно выключенных
odds. Worker при `mem_limit=3g`, swap=0 опубликовал 1 847 прогнозов без OOM;
calendar/quality/predictions/publication успешны. Оба archive-sync при
`mem_limit=512m`, `/tmp=64m`, swap=0 remote-verified новые архивы; outbox
доставлен тестовому Telegram-боту за одну попытку. Пользователь ранее
подтвердил реальные `/upcoming`, `/cycle_history` и terminal notification
через @SSPredictBot, подключённого только к изолированным API/БД.
32 релевантных теста, lint, mypy, format и `git diff --check` прошли под
ограничением ресурсов. Полный pytest suite после инцидента 14.3 GB RSS не
запускался. Независимое review TASK-025-22/23/24/25/26 не выявило P0–P2.
Release/tag CI завершился успешно. Для точного systemd/Compose wrapper
подготовлен изолированный контур с опубликованными digest; тяжёлый Worker
не запускался: тестовый Docker scope попал в system slice с
`memory.max=max`, несмотря на лимит 6 GiB у user slice. Без общего
проверенного лимита на все контейнеры wrapper gate остаётся открытым.

## Healthcheck и smoke-проверка

После ограниченного rollout до ручного Data Cycle сверить running digests,
healthy/restart counts, `/health`, `/ready`, NHL calendar API 0/7/30 под
реальной reader role, readiness и admin status/history/schedule.
Один ручной цикл с `SF_DATA_ODDS_ENABLED=false` должен дать terminal
`partial_success`, ноль Odds API запросов, 30-дневное coverage, прогнозы для
eligible событий, odds `missing`, два verified archives и одно итоговое
уведомление с тем же run ID. Проверить пользовательские команды бота,
`make acceptance-check` с утверждёнными runtime inputs, отсутствие overlap.
Новый dispatcher timer включать только после успешного ручного цикла;
проверить next trigger, первый плановый run и уведомление. При ошибке
оставить timer выключенным, зафиксировать состояние и запросить инструкции
владельца без повторного rollout.

## Данные и совместимость

Свежий root-only `pg_dump -Fc` после production v1.2.8 ошибки создан:
`pre-v1.2.9-20260928T213539314360486.dump`, 57 921 104 байт,
SHA-256 `bd5dc06ed22d0957b96f10fdb16112f965c11dacc7c759e490124c228bcd983b`.
Каталог проверен; isolated restore на exact PostgreSQL image завершён
успешно: схема `0017`, 22 496 событий и 1 834 прогноза. Третья защищённая
локальная копия имеет тот же hash. Доступ к выделенному off-host
`production-backups/*` не найден: upload/download hash остаётся gate.
Схема остаётся `0017_data_cycle_notification_outbox`;
role-bootstrap/migrator выполняются idempotently из approved image.
Объекты архивов immutable; retention/encryption service account не видит.

## Наблюдаемость

В production change record сохранить UTC, source commit, manifest hash,
running image IDs, restart counts, DB revision, backup hash, bundle ID,
run/stage statuses, coverage, число прогнозов, 0 provider requests в
OFF-режиме, notification delivery и timer last/next trigger. Секреты,
полные Docker/DB логи и ответы провайдера не публиковать.

## Артефакт и откат

Annotated `v1.2.9` уже указывает на exact merged commit `main`;
перед выпуском сверить этот immutable tag и terminal tag pipeline с CI,
Security, first-rollout contract, linux/amd64 images, scan и provenance.
Release owner создаёт immutable evidence commit/tag и запускает
`make verify-release-evidence` с `--handoff docs/operations/production-handoff.md`
для exact manifest/handoff. Operations
сверяет digests и сохраняет root-only rollback refs v1.2.8, прежний model
pointer и backup. Serving rollback на v1.2.8 допускается по сохранённым
digest/env/model pointer без downgrade БД; если post-rollout ошибка повторит
баг, дальнейшие действия останавливаются до инструкции пользователя.

## Нерешённые вопросы

Для решения GO требуются безопасный exact wrapper gate, terminal evidence
CI, off-host backup evidence и установка проверенного wrapper
production-модели для `1.2.9`. Production rollout пока NO GO.
