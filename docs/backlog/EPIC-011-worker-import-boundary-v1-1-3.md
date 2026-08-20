# EPIC-011 — Patch-релиз v1.1.3: import-граница Worker

> **Статус:** in_progress
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
| [TASK-011-1](tasks/TASK-011-1-worker-import-boundary-v1-1-3.md) | Lazy import, Worker image gate и release handoff | REQ-011, ADR-011 | red/green import test, workflow contract, Docker gate | in_progress |

## Риски и rollout

- v1.1.2 digests остаются опубликованными и не могут быть заменены.
- До tag pipeline нет новых v1.1.3 digests/provenance; это release NO-GO.
- Operations пересобирает тот же bundle из тех же трёх файлов только после
  получения v1.1.3 immutable evidence.
