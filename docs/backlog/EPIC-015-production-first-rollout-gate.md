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

Четыре P1 финального review устранены. Повторное independent review
2026-09-07 не выявило blocking findings в implementation diff; проверенный
commit: `2772b93a198573f354643b242ae9a60493020f97`. Independent gates:
mypy passed, targeted pytest — 48 passed, `make production-check`, `make lint`,
`make docs` и `git diff --check` — passed. Sphinx выдал одно существующее
warning об `_static`.

EPIC остаётся `in_progress` до tag CI с official release evidence.
После него потребуется terminal EPIC review доказательств и внешняя
проверка владельцем: required first-rollout check и tag protection в GitHub.
