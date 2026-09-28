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
- source_tag: `v1.2.9` (целевой; тег ещё не создан).
- source_commit/evidence_tag: фиксируются после merge и tag gates.
- CI, Security, Docker, image digests, scan и provenance: ожидают source tag.

## Идентификация и ответственность

v1.2.9 исправляет ложный отказ freshness gate на прогнозах, созданных после
начала матча; ограничивает память archive-sync при сравнении больших файлов;
размещает remote verification вне `/tmp=64m`; исключает ненужные train-таблицы
из refresh Worker. Версия и lock согласованы (`pyproject.toml`, `uv.lock`).
Изменений схемы БД, модели, коэффициентов и публичного API нет.

Production preflight: v1.2.8 healthy, Alembic `0017`, оба NHL timer disabled,
последний run `failed/quality_failed`, active runs нет. Production bundle
`sha256:5b3cb6e2ca0b588059de7416a5cbdae1e955e4b9a91b08be51da43684e3640b0`
содержит 489 ordered features и проверенные веса. Для v1.2.9 нужен новый
content-addressed wrapper с теми же весами, `app_version=1.2.9` и exact
source_commit/tag; текущий production pointer до готовности нового bundle
не менять.

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
Точный systemd wrapper целиком и release/tag CI пока не проверены.

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

Перед v1.2.9 нужен свежий root-only `pg_dump -Fc` после production v1.2.8
ошибки, checksum/catalog, isolated restore на exact PostgreSQL image,
off-host upload/download hash и третья локальная копия. Backup перед
v1.2.8 уже проверен локально, но не является актуальным backup для нового
rollout. Схема остаётся `0017_data_cycle_notification_outbox`;
role-bootstrap/migrator выполняются idempotently из approved image.
Объекты архивов immutable; retention/encryption service account не видит.

## Наблюдаемость

В production change record сохранить UTC, source commit, manifest hash,
running image IDs, restart counts, DB revision, backup hash, bundle ID,
run/stage statuses, coverage, число прогнозов, 0 provider requests в
OFF-режиме, notification delivery и timer last/next trigger. Секреты,
полные Docker/DB логи и ответы провайдера не публиковать.

## Артефакт и откат

После terminal PR CI и финального review Reviewer создаёт annotated
`v1.2.9` на exact merged commit `main`. Tag pipeline обязан завершить CI,
Security, first-rollout contract, linux/amd64 images, scan и provenance.
Release owner создаёт immutable evidence commit/tag и запускает
`make verify-release-evidence` с `--handoff docs/operations/production-handoff.md`
для exact manifest/handoff. Operations
сверяет digests и сохраняет root-only rollback refs v1.2.8, прежний model
pointer и backup. Serving rollback на v1.2.8 допускается по сохранённым
digest/env/model pointer без downgrade БД; если post-rollout ошибка повторит
баг, дальнейшие действия останавливаются до инструкции пользователя.

## Нерешённые вопросы

Для решения GO требуются exact wrapper gate или обоснованное
закрытие этого пробела, terminal PR/CI, source tag,
manifest/images/evidence, свежий backup/restore/off-host evidence и wrapper
production-модели для `1.2.9`. Production rollout пока NO GO.
