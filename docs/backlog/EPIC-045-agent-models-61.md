# EPIC-045 — Обновление Sol для агентов

> **Статус:** in_progress
> **Приоритет:** medium
> **Владелец:** Product Owner
> **Требование:** [REQ-045](../product/requirements/REQ-045-agent-models-61.md)
> **ADR:** не требуется

## Память Product Owner

- Инициатива: `EPIC-045`.
- Ветка инициативы: `initiative/epic-045-agent-models-61`.
- Workflow / этап: `engineering / commit и PR`.
- Исходная цель: обновить Sol-профили до 6.1, сохранив Luna и Astra; [REQ-045](../product/requirements/REQ-045-agent-models-61.md).
- Критерии приёмки и DoD: три критерия REQ-045, независимое review, зелёный CI и merge.
- Релиз: не требуется.
- Выполнено: зафиксирована карта моделей; тест валидатора прошёл red → green;
  12 AI-тестов и `make ai-validate` прошли; независимый Reviewer подтвердил TASK
  и полный scope EPIC без блокирующих findings.
- Решения: Terra не назначается после уточнения владельца; ADR не нужен.
- Артефакты: REQ-045, [TASK-045-1](tasks/TASK-045-1-agent-models-61.md), отчёт `done`.
- Предыдущая роль: Reviewer — независимое TASK и полное EPIC review.
- Следующая роль: Product Owner — PR, terminal CI и merge после отправки ветки Reviewer.
- Открытые вопросы / блокеры: нет.
- Research: не применяется.
- Обновлено: 2026-10-31.

## Цель и границы

Обновить назначение моделей Sol в проектном AI-слое без изменения ролей, процесса и
production-приложения. Исторические артефакты сохраняют состояние своего периода.

## Декомпозиция

| Задача | Результат | Проверка | Статус |
|---|---|---|---|
| [TASK-045-1](tasks/TASK-045-1-agent-models-61.md) | Профили, валидатор и текущая карта моделей | AI tests, `make ai-validate` | done |

## Риски и rollout

Проектные настройки применяются после доверия репозиторию и запуска новой сессии Codex.
Откат — возврат профилей и валидатора в отдельном PR. Production rollout не нужен.

## Полное EPIC review

Независимый Reviewer проверил REQ-045, профили, валидатор, тесты и текущую карту моделей.
Прежний Sol заменён во всех активных назначениях; Luna, Astra, reasoning и sandbox
сохранены. Замечание форматирования теста устранено; блокирующих findings нет.
Проверки: 12 AI-тестов, `make ai-validate`, целевые Ruff check/format и `git diff --check`
прошли. Production-код, секреты и внешние сервисы этим diff не менялись.
Hash проверенного коммита: [`d29a40a3f952675bcc0733988f3af3f4b1054f58`](https://github.com/Xieveer/sports-probabilistic-forecasting/commit/d29a40a3f952675bcc0733988f3af3f4b1054f58).
Этот hash фиксируется отдельным documentation-only evidence-коммитом; PR и CI ожидаются.
