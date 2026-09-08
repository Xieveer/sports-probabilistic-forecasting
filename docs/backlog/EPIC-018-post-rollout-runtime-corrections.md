# EPIC-018 — Runtime-исправления после rollout

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-020](../product/requirements/REQ-020-post-rollout-runtime-corrections.md)

## Цель

Исправить наблюдаемые после production rollout контракты readiness, DB bootstrap,
cross-version model recovery и Telegram command menu без deployment или release tag.

| Задача | Результат | Проверка | Статус |
|---|---|---|---|
| [TASK-018-1](tasks/TASK-018-1-status-readiness.md) | `/status` читает `/ready` безопасно | unit handler | done |
| [TASK-018-2](tasks/TASK-018-2-bootstrap-database-url-file.md) | bootstrap читает `DATABASE_URL_FILE` | CLI/config unit | done |
| [TASK-018-3](tasks/TASK-018-3-cross-version-model-recovery.md) | cross-version `previous` | model bundle unit | done |
| [TASK-018-4](tasks/TASK-018-4-telegram-command-menu.md) | Telegram command menu | bot runtime unit | done |
