# TASK-025-13 — Исправления production Data Cycle

> **Статус:** реализация и целевые проверки завершены; передано на независимое review
> **Задача:** [TASK-025-13](../../backlog/tasks/TASK-025-13-production-runtime-hotfixes.md)

## Изменения

- Добавлен `executor_generation` в ограниченный INSERT grant `sf_control_api`.
- `run-canonical-refresh.sh` теперь хранится в Git как executable, как требует systemd `ExecStart`.
- Source-acquirer получает `DATABASE_URL_FILE` и secret `worker_database_url`, чтобы сохранять calendar/odds projection в PostgreSQL.
- Heartbeat вынесен в отдельный watcher, а основной runner ожидает stage через `wait` по PID. Ошибка heartbeat останавливает stage и передаёт terminal outcome host recovery; отказ stage прекращает heartbeat watcher.
- Runtime topology отражает DB доступ source-acquirer.

## Проверки

| Команда | Результат |
|---|---|
| `uv run pytest -q tests/test_production_topology.py tests/test_readiness_and_migrations.py` | 28 passed |
| `uv run ruff check sports_forecast/deploy/database_roles.py tests/test_production_topology.py tests/test_readiness_and_migrations.py` | Passed |
| `bash -n deploy/systemd/data-cycle-owner-guard.sh deploy/systemd/run-canonical-refresh.sh` | Passed |
| `git diff --check` | Passed |

Тест устаревшего `jobs -p` был запущен до исправления и завис при смоделированном
ложном сообщении о работающем PID. После перехода на ожидание stage PID тест
завершился с исходным кодом ошибки `23`. Дополнительные тесты проверяют heartbeat
длительной стадии и остановку с отметкой recovery при отказе heartbeat.

## Граница результата

Исправления не развёртывались этим TASK. Production rollout, проверку нового
image и первый штатный Data Cycle завершает Operations Agent в TASK-025-9.
