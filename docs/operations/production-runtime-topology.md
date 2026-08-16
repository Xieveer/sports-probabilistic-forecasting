# Production topology canonical refresh

Этот runbook — контракт `TASK-007-5`; он не разрешает deployment или изменение
VPS. Файлы [`deploy/systemd/`](../../deploy/systemd/) являются шаблонами для
Operations Agent.

## Границы контейнеров и доступов

| Контейнер | Доступ к БД | Mounts | Object Storage |
|---|---|---|---|
| `api` | `SF_API_DATABASE_URL`, read-only витрина | нет | нет |
| `telegram-bot` | нет, только внутренний API | нет | нет |
| `worker` | `SF_WORKER_DATABASE_URL`, canonical refresh/write | immutable `runtime_models`, source snapshot read-only, archive staging read-write | нет |
| `archive-sync` | нет | archive staging read-only, отдельный sync state read-write | write/read verify только `operational-archive/*` |

Роли `sf_api_reader` и `sf_refresh_writer` создаёт Operations Agent после
migrations и ограничивает соответствующими таблицами/операциями. `worker` не
получает DVC, MLflow или Object Storage credentials. Отдельная Operations sync
учётная запись имеет write/read-verify только к `operational-archive/`; local training
читает snapshot отдельной read-only учётной записью и prefix.

## Scheduler profile

1. Скопировать `refresh-profile.env.example` в
   `/etc/sports-forecast/refresh/<profile>.env`, установить `0600 root:root`.
   Не помещать в него Object Storage credentials.
2. Установить service и timer templates. Для каждого profile добавить
   `schedule.conf` в `.timer.d/` и `runtime.conf` в `.service.d/` из шаблонов.
   Первое задаёт единственный cadence, второе — подтверждённый timeout.
3. После `systemctl daemon-reload` включить только конкретный timer:
   `systemctl enable --now sports-forecast-canonical-refresh@<profile>.timer`.

Каждый запуск получает run ID `<profile>-<UTC timestamp>-<UUID>`. `flock -n`
завершает overlap без ожидания; DB per-tournament lock остаётся второй границей
защиты. `TimeoutStartSec`, `Restart=on-failure`, `RestartSec=5m` и systemd
start limit задают timeout/retry. Успех не определяется exit code timer-а:
durable сигнал — `worker_executions.status=succeeded` для этого run ID.

До включения timer Operations Agent выполняет только dry-run: `docker compose
config`, `bash -n deploy/systemd/run-canonical-refresh.sh` и `systemd-analyze
verify` templates. Реальный `systemctl enable`, доступы S3 и rollout требуют
отдельного разрешения владельца.
