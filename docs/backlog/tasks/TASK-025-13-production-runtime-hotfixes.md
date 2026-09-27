# TASK-025-13 — Исправить ошибки production Data Cycle

> **Статус:** done — код, локальные проверки и независимое review завершены
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Результат

Исправить четыре ошибки, обнаруженные при production запуске Data Cycle v1.2.1:
недостаточный INSERT grant для `executor_generation`, отсутствие execute bit у
systemd runner, отсутствие DB URL у source-acquirer и бесконечный heartbeat loop
после завершения stage при устаревшем выводе `jobs -p`.

## Критерии приёмки

- [x] `sf_control_api` может создать run с `executor_generation` через least-privilege grant.
- [x] Файл, указанный в systemd `ExecStart`, отслеживается Git как executable.
- [x] Source-acquirer получает worker DB URL через secret file и не использует SQLite fallback.
- [x] Stage process ожидается напрямую; завершившийся stage прекращает heartbeat loop, а живой stage сохраняет heartbeat и fencing при потере lease.
- [x] Целевые contract tests проходят. Этот worktree не запускал production rollout и не менял production данные.

## Handoff и отчёт

- [Отчёт выполнения](../../changes/done/TASK-025-13-production-runtime-hotfixes.md).
- Независимое review проверило 52 целевых теста, Ruff, `bash -n` и diff без
  P0–P2 findings. Production rollout выполняется Operations отдельно.
