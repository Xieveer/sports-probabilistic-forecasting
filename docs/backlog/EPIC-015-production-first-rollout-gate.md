# EPIC-015 — Production first-rollout gate

> **Статус:** in_progress
> **Приоритет:** critical
> **Владелец:** главный агент
> **Требование:** [REQ-017](../product/requirements/REQ-017-production-first-rollout-contract.md)
> **ADR:** [ADR-016](../architecture/adr/ADR-016-first-rollout-runtime-contract.md)

## Цель и границы

Реализовать доказуемый первый rollout в чистом Docker project. Не выполнять
production deployment, publication или выдачу реальных credentials.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-015-1](tasks/TASK-015-1-runtime-bootstrap-and-rollout-gate.md) | Runtime commands, DB roles, local runner и tag gate | ADR-016 | targeted tests + clean Docker scenario | in_progress |

## Риски и rollout

Rollback additive migration выполняется logical restore в isolated DB; production
downgrade не выполняется. Реальные secret files и IAM остаются вне repository.

## Review remediation scope

- Worker table-level grants и catalog deny для Alembic/control tables.
- Fail-closed evidence: health, restart count, ports, resources и scrubbed logs.
- DB restore revision/content и model pointer `current → previous → current`.
- Immutable workflow inputs, tag-version/provenance и clean-tree evidence.
- Воспроизводимый green type gate для затронутого scope.

### Повторное review remediation (2026-09-06)

Исправлены build-once OCI provenance, DB restore schema/content, catalog deny,
Docker health bot, secret-bearing argv и воспроизводимый type gate. До terminal
статуса оставалось Worker RSS/disk evidence; оно добавлено, но финальное review
обнаружило P1 в clean-tree ordering, table grants, актуальности evidence и
runbook secret-file contract.

После закрытия требуется новый independent review. Required GitHub check для
release tags назначается владельцем репозитория вне Git tree.

## Полное EPIC review

Финальный reviewer выявил четыре P1, зафиксированные в TASK-015-1. Их remediation
ожидает повторного independent review и tag CI с official evidence, поэтому EPIC
остаётся `in_progress`. После clean final review потребуется внешняя проверка
владельцем: назначить required first-rollout check и tag protection в GitHub.
