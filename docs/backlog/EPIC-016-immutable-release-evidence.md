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
| [TASK-016-2](tasks/TASK-016-2-worker-runtime-digest-evidence.md) | Runnable Worker digest, platform/runtime gate и evidence.2 | ADR-017 | targeted tests + exact registry smoke | in_progress |

## Риски и rollout

До успешных CI/Security/Docker/first-rollout runs и protected tag policy — NO-GO. Rollback,
migration и first deployment остаются обязанностью Operations после owner approval.

## Полное EPIC review

Independent review локального scope завершено без blocking findings. Reviewer
независимо выполнил `make type-check`, targeted release tests (18 passed) и
`git diff --check`. Проверенный commit:
`9daf2d5bb040a5b8860961a12cb81a48997eaeac`.

Полное EPIC review и статус `done` ожидают external CI/Security/Docker/first-rollout
evidence, publication/scans/provenance/Linux amd64 и protected tag policy. Evidence commit/tag
создаётся только после successful application tag pipeline.
