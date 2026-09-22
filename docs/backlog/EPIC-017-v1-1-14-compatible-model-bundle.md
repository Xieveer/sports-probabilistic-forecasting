# EPIC-017 — Совместимый production model bundle v1.1.14

> **Статус:** in_progress
> **Приоритет:** critical
> **Владелец:** главный агент
> **Требование:** [REQ-019](../product/requirements/REQ-019-v1-1-14-compatible-model-bundle.md)

## Цель

Подготовить и безопасно активировать immutable model bundle, совместимый с application
release v1.1.14, без retraining и запуска production workload.

| Задача | Результат | Проверка | Статус |
|---|---|---|---|
| [TASK-017-1](tasks/TASK-017-1-reissue-compatible-model-bundle.md) | Build, runtime verification, staging и atomic activation | checksum + exact Worker verify | in_progress |
