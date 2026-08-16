# EPIC-008 — Проверяемые gates процесса Codex-агентов

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-009](../product/requirements/REQ-009-agent-workflow-gates.md)
> **ADR:** [ADR-009](../architecture/adr/ADR-009-enforce-agent-workflow-gates.md)

## Цель и границы

Сделать пользовательский workflow агентов явным и проверяемым. Вне границ — прикладной код и
выполнение внешнего Git push.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-008-1](tasks/TASK-008-1-enforce-agent-workflow-gates.md) | Правила, templates и валидатор workflow | ADR-009 | unit + `make ai-validate` | done |

## Риски и rollout

Проверка контролирует контракт, а не фактическую независимость человека или Git credentials.
Rollback — отменить изменённые process-файлы одним обратным review-коммитом.

## Полное EPIC review

Ожидает независимого reviewer. До его review EPIC остаётся `in_progress`; reviewer должен
проверить REQ-009, ADR-009, TASK-008-1, профиль reviewer, rules, templates и валидатор,
зафиксировать findings/проверки и только после этого выполнить итоговый commit/push.
