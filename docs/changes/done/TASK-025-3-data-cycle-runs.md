# TASK-025-3 — Durable runs и failed acquisition

> **Статус evidence:** реализация slice A; повторное независимое review пройдено.
> Реальный shell/Compose runtime остаётся release gate. Полный recovery/history вынесен в
> [TASK-025-7](../../backlog/tasks/TASK-025-7-data-cycle-recovery-summary.md).

## Изменения

- Добавлены durable `data_cycle_runs` и `data_cycle_stage_results`, ограничения
  одного активного run на турнир, фиксированные stage/failure allowlists,
  безопасные counters и additive migration `0012`.
- Runner создаёт run до NHL source acquisition. Ошибка calendar acquisition
  закрывает run/stage и обновляет failed attempt, сохраняя окно предыдущего
  покрытия и `last_successful_at` отдельно от последнего `checked_at`.
- Успешный canonical import, quality gate, inference, publication и archive
  фиксируют стадии. До TASK-025-6 legacy odds path остаётся `partial_success`
  с нулём независимо подтверждённых odds observations.
- `sf_refresh_writer` получил grants для lifecycle tables; `sf_api_reader` не
  получил доступа к control history. Обновлены календарный response и
  эксплуатационные заметки по migrations, topology и alerts.

## Проверки

| Команда | Результат |
|---|---|
| `uv run pytest tests/test_archive_manifest_enumeration.py tests/test_data_cycle_lifecycle.py tests/test_data_cycle_runner_contract.py tests/test_readiness_and_migrations.py::test_migration_command_creates_schema_and_is_idempotent tests/test_calendar_api.py tests/test_canonical_full_refresh.py tests/test_canonical_full_refresh_cli.py -q` | 30 passed |
| `uv run ruff check` по затронутым Python files | успешно |
| `uv run ruff format --check` по затронутым Python files | успешно |
| `uv run pre-commit run mypy --files ...` по repository/CLI/tests | успешно |
| `bash -n deploy/systemd/run-canonical-refresh.sh deploy/systemd/list-canonical-archive-manifests.sh` | успешно |
| `git diff --check` | успешно |

Исправлены findings: ошибка runner классифицируется по `current_stage` из БД;
стадия не может завершиться успешно до `start`, а run — при активной стадии;
ненулевой результат archive `find` останавливает стадию до sync и terminal success.

Отдельный широкий `uv run mypy` без hook-конфигурации завершился ошибками в
существующих SQLAlchemy `Column` моделях/repository typing; согласованный
pre-commit mypy hook с проектными настройками прошёл.

## Оставшиеся gates

- Повторный Reviewer независимо проверил 30 целевых тестов, синтаксис обоих
  shell scripts и diff-check; блокирующих findings не осталось.
- Выполнение полного shell/Compose запуска и миграции на целевом runtime не
  проверялось; это release gate Operations Agent.
- Executor crash/timeout recovery, fencing, summary/history API, полный fault
  matrix и PostgreSQL concurrency остаются в TASK-025-7. Calendar-first odds
  acquisition остаётся в TASK-025-6.
