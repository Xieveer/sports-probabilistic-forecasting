# TASK-025-15 — Логирование Hydra в read-only Worker

> **Статус:** реализация, проверки и независимое review завершены
> **Задача:** [TASK-025-15](../../backlog/tasks/TASK-025-15-readonly-worker-hydra-logging.md)

## Изменение

Запуск canonical CLI из systemd runner явно передаёт
`hydra/job_logging=disabled` и `hydra.output_subdir=null`. Dockerfile уже
содержал эти аргументы в CMD, но `docker compose run` переопределял CMD.
Контейнер остаётся read-only; логи идут в stdout/systemd journal.

## Проверка

Регрессионный тест сначала упал на отсутствии `hydra/job_logging=disabled` в
Worker-команде runner. После исправления 26 целевых тестов runner/topology
прошли; `bash -n` и `git diff --check` прошли. Реальный запуск Hydra из
read-only `/sys` воспроизвёл исходный `PermissionError` при создании log file.
С двумя overrides Hydra прошла настройку и остановилась на ожидаемом
отсутствии scheduler environment input, не пытаясь записать файл.
`make lint`, `make production-check` и полный unit-набор прошли: 1201 passed,
13 deselected. `make docs` собрался с 155 предупреждениями Sphinx.
Первый `make pre-commit` автоматически отформатировал regression test;
повторный запуск прошёл все hooks. Независимый Reviewer проверил весь diff,
Hydra config, Docker CMD/Compose read-only contract, logger и выполнил 28
целевых тестов, `bash -n`, `git diff HEAD --check`; P0–P2 findings нет.
Production acceptance ведётся в
[TASK-025-9](../../backlog/tasks/TASK-025-9-release-readiness.md).
