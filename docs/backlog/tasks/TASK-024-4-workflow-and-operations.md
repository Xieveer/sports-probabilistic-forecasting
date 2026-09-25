# TASK-024-4 — Маршрутизация ролей и Operations handoff

> **Статус:** done
> **Владелец:** Product Owner
> **Эпик:** [EPIC-024](../EPIC-024-initiative-agent-workflow.md)
> **Требование:** [REQ-024](../../product/requirements/REQ-024-initiative-agent-workflow.md)
> **ADR:** [ADR-025](../../architecture/adr/ADR-025-initiative-memory-and-orchestration-boundaries.md)

## Результат и границы

Правила выбирают минимальную ветку Engineering, Research или серверную работу Operations.
Установлены отдельные роли, независимое review, CI recovery, release gate и граница
Research → Engineering только по решению пользователя. Дублирующиеся роли/skills и
конфликтующие инструкции удалены или согласованы.

## Критерии приёмки

- [x] Малый bug fix проходит PO → Developer → Reviewer без BA/ADR, но с TASK и `done`.
- [x] Research на готовых данных пропускает Data Researcher; без данных ставит задачи на
  безопасный сбор и ожидает пользователя.
- [x] Reviewer проверяет Research один раз перед отчётом; GO не запускает релиз сам.
- [x] Инструкция CI после PR требует terminal-статус, диагностику падения и повторное review.
- [x] Релизный маршрут описывает проверенный тег в `main` и Operations deployment,
  обычный инженерный маршрут — merge без тега и новых образов; реальный релиз не входил в задачу.
- [x] Локальный профиль вызывает Operations Agent из отдельного репозитория, а инструкция
  требует обновлять обе применимые документации и возвращать нужную правку кода Product Owner.

## План реализации

1. Сценарии в eval/валидации для ключевых переходов.
2. Изменение ролей, skills, AGENTS и handoff, интеграция внешнего Operations Agent.
3. Согласование старой документации и `make ai-validate`.

## Затрагиваемые области и зависимости

`AGENTS.md`, `agents/`, `skills/`, `references/`, `docs/development/`, `docs/research/`,
`evals/`, Operations Agent; зависит от архитектуры и других срезов.

## Проверка

`make ai-validate`, фокусные eval/тесты и проверка сценариев REQ-024.

## Handoff и отчёт

- Отчёт выполнения: [TASK-024-4](../../changes/done/TASK-024-4-workflow-and-operations.md).
- Follow-up / findings: нет.
- Review: независимая проверка REQ-024 без блокирующих findings.
- Commit/push: ожидает Reviewer.
