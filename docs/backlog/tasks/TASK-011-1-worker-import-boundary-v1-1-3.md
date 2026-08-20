# TASK-011-1 — Import-граница Worker и release-gate v1.1.3

> **Статус:** done
> **Владелец:** implementer + devops-reviewer
> **Эпик:** [EPIC-011](../EPIC-011-worker-import-boundary-v1-1-3.md)
> **Требование:** [REQ-011](../../product/requirements/REQ-011-worker-import-boundary-v1-1-3.md)
> **ADR:** [ADR-011](../../architecture/adr/ADR-011-lazy-deploy-control-plane-import.md)

## Результат и границы

Изолировать MLflow control plane от Worker verifier, добавить Docker release-gate
до push и подготовить handoff v1.1.3. Не изменять v1.1.2, registry, VPS или
model bundle contents.

## Критерии приёмки

- [x] Import verifier проходит при недоступном MLflow.
- [x] Явный control-plane re-export `ModelPromoter` сохраняется ленивым.
- [x] Workflow собирает Worker target и запускает production import gate до push.
- [x] Версия и канонический handoff подготовлены к v1.1.3.

## План реализации

1. Добавить падающие unit/workflow contract tests для import boundary.
2. Выполнить минимальную lazy загрузку и release-gate.
3. Подтвердить targeted checks, review и передать Operations immutable release
   contract без публикации.

## Проверка

Targeted pytest, mypy, lint, `make production-check` и Docker Worker gate.

## Handoff и отчёт

После зелёных проверок: [отчёт TASK-011-1](../../changes/done/TASK-011-1-worker-import-boundary-v1-1-3.md).
