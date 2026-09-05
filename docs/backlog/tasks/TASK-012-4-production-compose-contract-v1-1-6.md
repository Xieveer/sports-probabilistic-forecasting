# TASK-012-4 — Production Compose contract и gates v1.1.6

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-012](../EPIC-012-nhl-source-state-archive.md)
> **Требование:** [REQ-016](../../product/requirements/REQ-016-production-compose-contract-v1-1-6.md)
> **ADR:** [ADR-015](../../architecture/adr/ADR-015-production-compose-model-bind-mount.md)

## Результат и границы

Исправить model bind mount и добавить до-publish rendered/final-image gates.
Не запускаются DB, migrations, application runtime, timer или deployment.

## Критерии приёмки

- [x] Model root Worker является read-only host bind mount.
- [x] Fixture rendered Compose валидирует mounts, images, private topology и resources.
- [x] Final Worker валидирует staged artifacts и model bundle при read-only/no-network identity.
- [x] Release handoff описывает обязательный server-side review.

## План реализации

1. Добавить падающий topology/release-contract test.
2. Обновить Compose, fixture builders и release gates.
3. Обновить release/runbook documents и выполнить targeted проверки.

## Проверка

Targeted pytest, rendered Compose, final Worker Docker gate, lint/type checks,
`make docs`, `make production-check` и доступные security checks.

## Handoff и отчёт

Отчёт: [TASK-012-4 report](../../changes/done/TASK-012-4-production-compose-contract-v1-1-6.md).
Независимые review/security и DevOps release decision остаются обязательными до tag.
