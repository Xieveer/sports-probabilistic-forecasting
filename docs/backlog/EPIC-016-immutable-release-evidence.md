# EPIC-016 — Immutable release evidence v1.1.14

> **Статус:** in_progress
> **Приоритет:** critical
> **Владелец:** главный агент
> **Требование:** [REQ-018](../product/requirements/REQ-018-immutable-release-evidence-v1-1-14.md)
> **ADR:** [ADR-017](../architecture/adr/ADR-017-two-phase-release-evidence.md)

## Цель и границы

Подготовить двухфазный release contract без deployment. Evidence tag создаётся только после
внешне успешного application tag pipeline.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-016-1](tasks/TASK-016-1-release-evidence-gate.md) | Validator, workflow, static handoff и release docs | ADR-017 | targeted tests + Compose render | done |

## Риски и rollout

До успешных CI/Security/Docker/first-rollout runs и protected tag policy — NO-GO. Rollback,
migration и first deployment остаются обязанностью Operations после owner approval.

## Полное EPIC review

Ожидает external pipeline evidence, independent review и проверенный commit. Evidence commit/tag
создаётся только после successful application tag pipeline.
