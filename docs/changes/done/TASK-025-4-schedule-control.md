# TASK-025-4 — Отчёт: persistent schedule и control API

> **Статус:** Developer handoff; независимое review ожидается
> **Дата:** 2026-09-26
> **Задача:** [TASK-025-4](../../backlog/tasks/TASK-025-4-schedule-control.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат

Добавлены persistent schedule для pipeline, optimistic revision, общая функция
вычисления следующего слота от `base_time`, authenticated admin API, idempotent
manual request и dispatcher due-slot reservation. Default — `10:00
Europe/Moscow`, автоматический цикл включён, интервал `24h`. Сейчас разрешены
интервалы `4, 6, 8, 12, 24` часов; выбирать меньший production интервал можно
после измерения времени полного цикла и квоты источников.

Один partial unique index на Data Cycle сохраняет только один active run. API
создаёт `waiting` run до исполнения; одинаковый idempotency key возвращает тот
же run, новый manual request при active run возвращает его же, а новый callback
после terminal failure создаёт новый UUID. Manual run работает при отключённом
auto schedule и не сдвигает его. Dispatcher пишет heartbeat, схлопывает overdue
slots в один run, сохраняет `scheduled_for` и missed-slot count; при active run
не создаёт неограниченную очередь.

Control API требует service key из `SF_CONTROL_API_KEY_FILE` и Telegram principal
из `SF_CONTROL_ADMIN_IDS`; пустая конфигурация запрещает доступ. Публичный Caddy
возвращает 404 для `/admin`. API/dispatcher используют отдельную
`sf_control_api` database identity: чтение run state, запись schedule/heartbeat
и column-level INSERT начального `waiting` run/stages. `sf_api_reader` не видит
control history, а control role не может обновлять terminal run status.

Systemd dispatcher запускается минутным timer и передаёт только UUID в
фиксированный `sports-forecast-data-cycle@<UUID>.service`; pipeline allowlist
сейчас содержит только NHL. Прежний service template направляет вызов через тот
же bridge. На VPS старый timer должен быть выключен при rollout, новый включён
после миграции и подготовки secrets. Bot UI остаётся в TASK-025-5; recovery и
fencing зависшего `running` executor остаётся в TASK-025-8.

## Проверки

| Проверка | Результат |
|---|---|
| `uv run pytest -q tests/test_production_topology.py tests/test_readiness_and_migrations.py tests/test_admin_control_api.py tests/test_data_cycle_schedule.py tests/test_runtime_db_role_privileges.py` | 34 passed, 2 PostgreSQL integration tests skipped без переменных подключения |
| Compose scheduler `config --quiet` с чистым окружением (`env -i`) и примером `refresh-profile.env.example` | прошёл; host bridge явно передаёт `--env-file` из `SF_COMPOSE_ENV_FILE` |
| Совмещённый прогон TASK-025-4/10 и затронутых topology/migration тестов | 85 passed, 2 PostgreSQL integration tests skipped без переменных подключения; прогон выполнен после исправления замечаний обоих TASK |
| `SF_TEST_POSTGRES_URL=<disposable PostgreSQL 16 URL> uv run pytest -q tests/test_data_cycle_schedule.py::test_postgresql_serializes_due_dispatch_and_manual_idempotency` | 1 passed: параллельное scheduled dispatch и одинаковый manual key возвращают один run |
| `SF_TEST_CONTROL_DATABASE_URL` и `SF_TEST_API_READER_DATABASE_URL` на disposable PostgreSQL: `uv run pytest -q tests/test_runtime_db_role_privileges.py` | ранее прошёл на временных runtime credentials: control не читает predictions и не завершает run; reader не читает control history |
| `DATABASE_URL=<disposable PostgreSQL URL> uv run alembic -c alembic.ini upgrade head` | прошла чистая PostgreSQL 16 migration до `0014_pipeline_schedule_control` |
| PostgreSQL grant exercise: schedule/run/stage inserts через `sf_control_api`, запрет terminal update | прошёл |
| SQLite migration idempotency и targeted unit/ASGI tests | прошли |
| `bash -n` для dispatcher/wrapper/archive scripts; `git diff --check`; touched Python `ruff check` и `ruff format --check` | прошли |
| `systemd-analyze verify` для новых и legacy units | проверил unit syntax; локальный host path `/opt/sports-forecast` отсутствует, поэтому проверка сообщает о недоступности ExecStart файла |
| `uv run pre-commit run --all-files` на совмещённом diff | все hooks прошли после исправления четырёх mypy ошибок в control API |
| `make lint`, `make docs` на совмещённом diff | прошли; Sphinx завершился с 24 предупреждениями |
| Независимое review TASK4 и повтор после findings | Пройдено; Compose environment и terminal replay исправлены |

## Остаточные gates

- Production database bootstrap, backup/restore, секреты, timer replacement,
  scheduler heartbeat и фактический ежедневный cycle остаются Operations gates.
- Recovery/fencing, автоматический retry `running` cycle и host process stop
  evidence не входят в этот TASK и остаются в TASK-025-8.
- Telegram admin UI и handler/API end-to-end остаются в TASK-025-5.
