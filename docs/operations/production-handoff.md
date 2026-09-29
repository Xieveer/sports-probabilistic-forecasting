# Передача сервиса в эксплуатацию: v1.2.10 candidate

> Фактическое состояние на последней проверке 2026-09-29: production работает на v1.2.8;
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
  [TASK-025-26](../backlog/tasks/TASK-025-26-refresh-inference-memory.md),
  [TASK-025-27](../backlog/tasks/TASK-025-27-archive-manifest-loop.md),
  [TASK-025-28](../backlog/tasks/TASK-025-28-acceptance-docs-response.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- Целевая среда: production VPS; версия: `1.2.10`.
- source_tag: `v1.2.10`.
- source_commit: `38ac3bc4cfc9cd6d771652183e49b006b3100d63`.
- evidence_tag: `v1.2.10-evidence.2` (создаётся после повторной проверки manifest).
- PR: https://github.com/Xieveer/sports-probabilistic-forecasting/pull/52.
- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36593929894.
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36593930087.
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36594026233.
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36594026233/job/109496586224.

Evidence.1 сохранился как проверенный снимок до выявления ошибки скрипта
acceptance. Evidence.2 фиксирует безопасный эквивалент без изменения source tag.

Tag pipeline завершился `success`: четыре образа опубликованы как immutable
linux/amd64, scan и provenance прошли. Published digest совпали с digest
образов, проверенных first-rollout:

- postgres: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94` — без изменения.
- api: `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:eb97bef597f77df29f8dd223579bcc5692087b34de81383000e96398c56adf57` — published linux/amd64 scan provenance.
- worker: `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:a0668d7b2e386dd1dfad92b2d99cd9cbd5235d0dbe2287f163bfb179a9107fb9` — published linux/amd64 scan provenance.
- telegram_bot: `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:d690af1bc5440a604a8b92c2f614fbea47a5ada8f0d01ca3b0fba9e8e286dcd5` — published linux/amd64 scan provenance.
- archive_sync: `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:0adacbba4c069b733dd59d3c55a305da9c8f3b9a9ede6612099d970d5ffb99aa` — published linux/amd64 scan provenance.

## Идентификация и ответственность

v1.2.9 исправила ложный отказ freshness gate на прогнозах, созданных после
начала матча; ограничила память archive-sync при сравнении больших файлов;
разместила remote verification вне `/tmp=64m`; исключила ненужные train-таблицы
из refresh Worker. Локальный exact wrapper выявил дефект цикла перечисления
manifest: Compose наследует stdin и может синхронизировать только первый
архив при успешном статусе. v1.2.10 исправляет этот дефект. Версия и lock
согласованы (`pyproject.toml`, `uv.lock`).
Изменений схемы БД, модели, коэффициентов и публичного API нет.

Production preflight: v1.2.8 healthy, Alembic `0017`, оба NHL timer disabled,
последний run `failed/quality_failed`, active runs нет. Production bundle
`sha256:5b3cb6e2ca0b588059de7416a5cbdae1e955e4b9a91b08be51da43684e3640b0`
содержит 489 ordered features и проверенные веса. Для v1.2.10 нужен новый
content-addressed wrapper с теми же весами, `app_version=1.2.10` и exact
source_commit/tag. Локально собран и проверен bundle
`sha256:f7deb1534537726c9f462b2de5c440f57344a59c8a6e97acc0e20ce25528d5b6`;
SHA всех трёх model files совпали с production current bundle. Текущий
production pointer до установки новой версии не менять.

## Runtime и конфигурация

Compose получает только immutable `IMAGE@sha256:DIGEST` из release manifest
и защищённые `*_FILE` paths. API, Worker и бот работают без host ports под
UID/GID `10001:10001`. `nhl_admins` одинаков у API, Worker и bot map.
Перед rollout Operations сверяет фактический systemd `SF_COMPOSE_ENV_FILE`
и `/etc/sports-forecast/refresh/nhl.env`: пять image refs,
`SF_APP_VERSION=1.2.10`, tournament/market/spec/algorithm/features selectors,
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
Точный v1.2.9 shell wrapper в изолированном Compose прошёл source, quality,
predictions и publication под общим cgroup 6 GiB/no swap: peak 3.65 GiB,
Worker без OOM. Archive gate не прошёл: локальные права сначала дали
`artifacts=0`; после их исправления отдельный archive loop подтвердил чтение
stdin первым `docker compose run` и только один sync из трёх manifest. Это кодовый дефект
[TASK-025-27](../backlog/tasks/TASK-025-27-archive-manifest-loop.md);
v1.2.9 остаётся NO GO. Ограниченный локальный wrapper с исправленным shell
`f2fdfa8` завершился `Result=success/exit0`, Data Cycle
`64cc3e85-944e-4c0b-afcb-b46e3d9dfc11` — ожидаемым `partial_success` при
выключенных odds. Новый пустой archive root содержал два ожидаемых manifest:
canonical и NHL source-state. Оба синхронизированы и remote-verified,
`archive_sync success/artifacts=2`; для обоих сохранено локальное состояние
`verified`. Общий cgroup 6 GiB/no swap имел исторический пик около 3.65 GiB
с учётом предыдущих попыток; прирост OOM и OOM kill в этом прогоне равен
нулю. Прогон использовал опубликованные образы/модель v1.2.9 и локальный
UID1000 override для host shell; production исполняет systemd shell под root,
контейнеры — под UID10001. Это доказательство исправленного shell на полном
локальном пути, а exact v1.2.10 image/identity gate остаётся за tag pipeline
и первым ограниченным production rollout. Первый подготовительный запуск
fixture был остановлен до Worker из-за неверного bind source root, затем
исправленный mount и incremental date проверены перед успешным прогоном.
PR #52 и main CI/Security прошли; независимый review TASK-025-27 без P0–P2.
Source tag `v1.2.10` и release/tag CI/first-rollout завершились успешно.

## Healthcheck и smoke-проверка

После ограниченного rollout до ручного Data Cycle сверить running digests,
healthy/restart counts, `/health`, `/ready`, NHL calendar API 0/7/30 под
реальной reader role, readiness и admin status/history/schedule.
Production schedule row остаётся `enabled=true` при выключенном systemd timer,
а `next_run_at` просрочен. Сначала создать ручной run через авторизованный
admin API, затем однократно запустить dispatcher service; до этого dispatcher
не стартовать. После claim проверить перенос overdue schedule slot в будущее
и отсутствие второго активного run.

Один ручной цикл с `SF_DATA_ODDS_ENABLED=false` должен дать terminal
`partial_success`, ноль Odds API запросов, 30-дневное coverage, прогнозы для
eligible событий, odds `missing`, новые canonical и source-state archives
со статусом `verified` и одно итоговое уведомление с тем же run ID. Проверить
пользовательские команды бота,
отсутствие overlap. Для v1.2.10 вместо `make acceptance-check` выполнить
эквивалентные read-only проверки с утверждёнными runtime inputs: `GET /health`
и `/ready` с проверкой `status`, `db_connected` и версии; `GET /docs` как
`200 text/html`, `GET /openapi.json` как валидный JSON; prediction endpoint
с проверкой версии модели; `SELECT` последнего успешного Worker execution и
terminal Data Cycle stages; безопасный bot heartbeat. Скрипт
`scripts/acceptance_check.py` из immutable source tag ошибочно парсит HTML
`/docs` как JSON и даёт ложный отказ даже на здоровом API; дефект отслеживает
[TASK-025-28](../backlog/tasks/TASK-025-28-acceptance-docs-response.md).
Зафиксировать по каждой альтернативной проверке статус, UTC и run ID в
Operations change record без содержимого ответов и секретов.

Production archive staging уже содержит два старых manifest. После нового
цикла `archive_sync.artifacts` должен равняться фактическому числу manifest,
перечисленных в root, и быть не меньше двух; точное число зависит от
content-addressed совпадений. Оба новых типа archive должны пройти
remote verification, включая случаи повторного использования immutable ID.

Новый dispatcher timer включать только после успешного ручного цикла;
проверить next trigger, первый плановый run и уведомление. При ошибке
оставить timer выключенным, зафиксировать состояние и запросить инструкции
владельца без повторного rollout.

## Данные и совместимость

Свежий root-only `pg_dump -Fc` перед v1.2.10 создан:
`pre-v1.2.10-20260929T160157108514371.dump`, 57 921 104 байт,
SHA-256 `bd09610575141f7ce23b4f6fc4ebfa3f8b3b91cb4b74ab2f7073eebc7c216b5d`.
Изолированное восстановление на exact PostgreSQL image и полное off-host
скачивание из Yandex Object Storage подтвердили тот же hash и размер;
подробности в `operations-agent/docs/changes/2026-09-29-v1.2.10-backup-gate.md`.
Предыдущий backup перед v1.2.9 сохранён. Схема остаётся
`0017_data_cycle_notification_outbox`;
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
`v1.2.10` на exact merged commit `main`. Tag pipeline обязан завершить CI,
Security, first-rollout contract, linux/amd64 images, scan и provenance.
Release owner создаёт immutable evidence commit/tag и запускает
`make verify-release-evidence` с `--handoff docs/operations/production-handoff.md`
для exact manifest/handoff. Operations
сверяет digests и сохраняет root-only rollback refs v1.2.8, прежний model
pointer и backup. Serving rollback на v1.2.8 допускается по сохранённым
digest/env/model pointer без downgrade БД; если post-rollout ошибка повторит
баг, дальнейшие действия останавливаются до инструкции пользователя.

## Нерешённые вопросы

Для решения GO остаются повторная immutable evidence.2 CI/tag и проверка точных
runtime refs на production. Локальный UID и образный разрыв следует
проверить на первых ограниченных production шагах до включения timer.
Production rollout пока NO GO до завершения evidence gate.
