# TASK-013-2 — Провести pilot изоляции текущего Codex runtime

> **Статус:** done
> **Владелец:** главный агент
> **Эпик:** [EPIC-013](../EPIC-013-research-mode.md)
> **Требование:** [REQ-013](../../product/requirements/REQ-013-research-mode.md)
> **ADR:** [ADR-013](../../architecture/adr/ADR-013-research-mode-state-machine.md)

## Результат и границы

Проверить на текущем runtime фактический handoff между новыми сессиями без API key: каждый
шаг получает только serializable ContextPackage и durable state. Используются синтетические
гипотеза, source record и experiment metrics; service, сеть, данные и production code не
изменяются.

## Критерии приёмки

- [x] Scientist, Data Researcher и Evaluator запускаются как отдельные сессии без fork истории.
- [x] Следующий шаг восстанавливает только переданный package и может выполнить свою задачу.
- [x] Evidence фиксирует runtime-границы и не заявляет неподтверждённый Python/Codex adapter.

## План реализации

1. Создать синтетический Goal/State package без секретов и сетевых данных.
2. Последовательно вызвать три роли с `fork_turns=none`.
3. Сохранить outputs и выводы в отчёте, обновить ADR/Research Mode при необходимости.

## Проверка

- Наблюдение трёх agent calls с явными package и без истории.
- `make ai-validate` после обновления документации.

## Handoff и отчёт

- Отчёт выполнения: [TASK-013-2](../../changes/done/TASK-013-2-codex-runtime-isolation-pilot.md).
- Follow-up / findings: provenance/as-of и retry реализованы TASK-013-3; programmatic adapter
  отменён пользователем вместе с TASK-013-4.
- Review: независимый финальный review завершён без P0/P1/P2 findings после исправлений.
- Commit/push: хеш проверенного коммита фиксируется reviewer в отчёте отдельным evidence-коммитом.
