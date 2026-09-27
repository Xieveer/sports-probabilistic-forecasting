# Production topology canonical refresh

Этот runbook — контракт `TASK-007-5`; он не разрешает deployment или изменение
VPS. Файлы [`deploy/systemd/`](../../deploy/systemd/) являются шаблонами для
Operations Agent.

## Границы контейнеров и доступов

| Контейнер | Доступ к БД | Mounts | Object Storage |
|---|---|---|---|
| `api` | `SF_API_DATABASE_URL_FILE`, read-only витрина; `SF_CONTROL_DATABASE_URL_FILE`, ограниченный control state | нет | нет |
| `telegram-bot` | нет, только внутренний API | нет | нет |
| `data-cycle-dispatcher` | `SF_CONTROL_DATABASE_URL_FILE`, schedule/run reservation и heartbeat | нет | нет |
| `worker` | `SF_WORKER_DATABASE_URL_FILE`, canonical refresh/write | `${SF_MODEL_RUNTIME_ROOT}:/app/models:ro`, source snapshot read-only, archive staging read-write | нет |
| `archive-sync` | нет | archive staging read-only, отдельный sync state read-write | write/read verify только `operational-archive/*`, включая `nhl-source-state/v1/` |

Роли `sf_api_reader`, `sf_control_api` и `sf_refresh_writer` создаёт Operations
Agent после migrations и ограничивает соответствующими таблицами/операциями.
Control API и dispatcher могут создать только `waiting` run/stage; terminal
status и stage results обновляет только Worker identity. `sf_api_reader` не
читает control history. `worker` не
получает DVC, MLflow или Object Storage credentials. Отдельная Operations sync
учётная запись имеет write/read-verify только к `operational-archive/`; local training
читает snapshot отдельной read-only учётной записью и prefix. `DeleteObject` этим
аккаунтам не выдаётся; lifecycle удаляет только source-state artifacts старше
90 дней.

`SF_MODEL_RUNTIME_ROOT=/srv/sports-forecast/runtime_models` — host state, не
Docker volume. До запуска Worker Operations убеждается, что `current` — symlink
на `bundles/sha256:<id>`, путь и содержимое доступны `10001:10001` только для
чтения. В base Compose единственный persistent named volume — `pg_data`.

## Scheduler и цикл

1. Хранить `SF_CONTROL_API_DB_PASSWORD_FILE`, `SF_CONTROL_DATABASE_URL_FILE` и
   `SF_CONTROL_API_KEY_FILE` в защищённых secret files вне Git. Только API и
   Telegram bot получают service key; dispatcher получает только control DB URL.
   `BOT_ADMIN_USER_IDS` передаётся Control API как allowlist principal.
2. Скопировать `refresh-profile.env.example` в
   `/etc/sports-forecast/refresh/nhl.env` и `dispatcher.conf.example` в
   `/etc/sports-forecast/refresh/dispatcher.env`, права `0600 root:root`.
   Не помещать в эти файлы значения credentials или Object Storage secrets.
3. Установить `sports-forecast-data-cycle-dispatcher.service/.timer` и
   `sports-forecast-data-cycle@.service`. Dispatcher опрашивает persistent
   business schedule раз в минуту и запускает только waiting run через UUID
   template. Business schedule хранится в БД: `10:00 Europe/Moscow`, интервал
   `24h` по умолчанию; допустимые интервалы `4, 6, 8, 12, 24` часов. До
   измерения runtime не уменьшать production default `24h`.
4. На rollout выключить прежний
   `sports-forecast-canonical-refresh@nhl.timer`, затем включить новый
   `sports-forecast-data-cycle-dispatcher.timer`. Оба systemd service entry
   используют общий durable run и одинаковый UUID unit name, поэтому два timer
   не создают два цикла. Legacy service направляет ручной вызов в тот же bridge.

Один active `data_cycle_runs` на pipeline защищён PostgreSQL partial unique
index. Dispatcher блокирует schedule row на время due-slot reservation,
схлопывает несколько просроченных слотов в один run и сохраняет `scheduled_for`
и число пропущенных слотов. Manual run разрешён при auto off и использует тот же
active-run gate. Старый timer не исполняет собственную cadence поверх business
schedule.

При stale heartbeat Control API показывает dispatcher недоступным, а активный
run становится `stalled`, не освобождая active slot. Следующий dispatcher tick
передаёт stalled run в `recover-data-cycle.sh`. Скрипт сверяет owner ID с
systemd `InvocationID`, останавливает соответствующий unit и все найденные
Compose one-off контейнеры, сверяет их run ID/generation/owner labels и только
после пустой проверки работающих контейнеров отправляет host evidence для
terminal recovery. Неполная или противоречивая инвентаризация завершает recovery
ошибкой; слот остаётся занят и требует ручного разбора. Heartbeat timeout сам
по себе никогда не разрешает второй claim. Детали реализации и fault tests —
[TASK-025-8](../backlog/tasks/TASK-025-8-executor-fencing.md).

После rollback восстанавливается совместимая пара `image + systemd unit set`:
старый image требует старого wrapper contract. Data Cycle history и additive
schema не удаляются.

До включения timer Operations Agent выполняет dry-run: `docker compose config`,
`bash -n deploy/systemd/dispatch-data-cycle.sh`,
`bash -n deploy/systemd/run-canonical-refresh.sh` и `systemd-analyze verify`
всех трёх новых unit templates. Фактическое включение и daily-run остаются
production release gates.
