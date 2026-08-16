# EPIC-008 — Проверяемые gates процесса Codex-агентов

> **Статус:** done
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

Независимый reviewer проверил REQ-009, ADR-009, terminal TASK-008-1 и его отчёт,
профили и роли, skill, templates, валидатор и отрицательные regression-тесты.
Ранее найденные P1/P2 исправлены; блокирующих findings в финальном review нет.
Каноническая документация синхронизирована, незавершённого scope нет; release evidence для
изменения process-layer ограничено локальными gates, production rollout не применим.

Фактически выполнены: `uv run pytest tests/test_ai_layer_validation.py -q` (6 passed),
целевой mypy hook (Passed), Ruff (Passed), `make ai-validate` (valid), `make docs`
(успешно с существующим warning о `_static`) и `git diff --check` (успешно).
Хеш проверенного коммита: `077ee01fc321e9a9eb80920df1bbb31869e32cb1`.
