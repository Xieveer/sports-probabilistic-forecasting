# EPIC-005 — Готовность production serving-контура

> **Статус:** done
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-005](../product/requirements/REQ-005-production-serving-release.md)
> **ADR:** [ADR-005](../architecture/adr/ADR-005-production-serving-boundary.md)

## Цель и границы

Закрыть `NO-GO` findings DevOps до передачи production-контракта. Эпик не
выполняет deployment, release tagging/push или изменение production-host.
Архитектурная граница и жизненный цикл данных согласованы владельцем; реализация
ведётся одним зависимым срезом за раз.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-005-1](tasks/TASK-005-1-production-topology-and-release-gates.md) | Минимальный Compose и ручной immutable release gate | ADR-005 accepted | compose config + CI/static tests | done |
| [TASK-005-2](tasks/TASK-005-2-readiness-and-migrations.md) | Readiness и versioned migration/recovery | ADR-005 accepted | API + PostgreSQL integration tests | done |
| [TASK-005-3](tasks/TASK-005-3-immutable-model-artifact.md) | Immutable model bundle/pointer | TASK-003-1, TASK-003-2, TASK-003-3 | manifest/promotion contracts | done |
| [TASK-005-7](tasks/TASK-005-7-serving-data-sync-and-archive.md) | DVC/archive/serving-data sync contract | TASK-005-1 | archive and bundle contracts | done |
| [TASK-005-4](tasks/TASK-005-4-materialization-job.md) | Bounded idempotent Worker job | TASK-005-2, TASK-005-3, TASK-005-7 | Worker/PostgreSQL integration test | done |
| [TASK-005-5](tasks/TASK-005-5-bot-heartbeat-and-observability.md) | Safe bot/Worker/API signals for Alloy | TASK-005-1, TASK-005-2, TASK-005-4 | redaction + health tests | done |
| [TASK-005-6](tasks/TASK-005-6-acceptance-and-release-handoff.md) | Acceptance test, measured resources and completed handoff | TASK-005-1…005-5 | prod-like evidence + production-check | done |

## Критерии → задачи → доказательства

| Критерий REQ-005 | Задачи | Доказательство |
|---|---|---|
| release/provenance и topology | 005-1, 005-6 | CI workflow, `docker compose config`, image scan/digest evidence |
| migrations и API readiness | 005-2 | failing/green tests, migration dry-run/recovery runbook |
| immutable model | 003-1…3, 005-3 | manifest/promotion/rollback contracts |
| DVC/archive/runtime data | 005-7 | direction/retention/validation contracts |
| Worker | 005-4 | PostgreSQL idempotency and state integration tests |
| bot/metrics/observability | 005-5 | heartbeat/redaction tests, Alloy-facing runbook |
| acceptance/handoff | 005-6 | non-mutating script, measurement and handoff validation |

## Риски и rollout

- `TASK-003-3` является критическим путём: до него production-model contract
  отсутствует. Не заменять его копированием mutable директории `models/`.
- Каждая schema migration должна быть additive и иметь recovery через backup;
  release images/models остаются immutable.
- Реальный tag, image publish, scans against published image и rollout — только
  после завершения эпика и отдельного разрешения пользователя.
