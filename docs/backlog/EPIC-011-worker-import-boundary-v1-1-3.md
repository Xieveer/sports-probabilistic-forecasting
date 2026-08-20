# EPIC-011 — Patch-релиз v1.1.3: import-граница Worker

> **Статус:** done
> **Приоритет:** critical
> **Владелец:** главный агент
> **Требование:** [REQ-011](../product/requirements/REQ-011-worker-import-boundary-v1-1-3.md)
> **ADR:** [ADR-011](../architecture/adr/ADR-011-lazy-deploy-control-plane-import.md)

## Цель и границы

Устранить блокирующий import MLflow в production Worker через новый immutable
patch-релиз v1.1.3. Эпик не модифицирует v1.1.2, не публикует artefacts и не
выполняет deployment.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-011-1](tasks/TASK-011-1-worker-import-boundary-v1-1-3.md) | Lazy import, Worker image gate и release handoff | REQ-011, ADR-011 | red/green import test, workflow contract, Docker gate | done |

## Риски и rollout

- v1.1.2 digests остаются опубликованными и не могут быть заменены.
- Operations пересобирает тот же bundle из тех же трёх файлов с
  `app_version=1.1.3`, пользуясь опубликованными immutable evidence.

## Полное EPIC review

Review подтвердил lazy import boundary, совместимость explicit `ModelPromoter`,
release-gate внутри Worker target и запрет изменения v1.1.2. Единственный P2
finding в версии строки Operations исправлен до merge. Release pipeline для
tag `v1.1.3` успешно выполнил gates, image scans и provenance; evidence — в
[production handoff](../operations/production-handoff.md).
