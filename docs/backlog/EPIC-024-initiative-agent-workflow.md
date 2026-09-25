# EPIC-024 — Работа агентов вокруг бизнес-инициативы

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-024](../product/requirements/REQ-024-initiative-agent-workflow.md)
> **ADR:** [ADR-025](../architecture/adr/ADR-025-initiative-memory-and-orchestration-boundaries.md)

## Память Product Owner

- Инициатива: `EPIC-024`.
- Ветка инициативы: `initiative/epic-024-agent-workflow`.
- Workflow / этап: `engineering / PR preparation`.
- Исходная цель: минимальный процесс агентов, ведущий две ветки задач до бизнес-результата;
  [подтверждённый REQ-024](../product/requirements/REQ-024-initiative-agent-workflow.md).
- Критерии приёмки и DoD: критерии REQ-024, независимое review, зелёные проверки и merge
  в `main`; production release не запрошен.
- Релиз: не требуется.
- Выполнено: интервью и подтверждение требований; ADR-025; четыре TASK реализованы;
  Developer устранил три research finding, Reviewer повторно подтвердил gates;
  локальные `make test` (1058 passed), lint, mypy, ai-validate и docs проходят.
- Решения: память в EPIC/TASK без отдельного state или CLI; ADR-025.
- Артефакты: REQ-024, ADR-025, TASK-024-1–4, четыре отчёта `done`, текущая ветка.
- Предыдущая роль: Reviewer.
- Следующая роль: Reviewer — финальная проверка и commit/push; затем Product Owner — PR/CI.
- Открытые вопросы / блокеры: GitHub CI и merge ещё не выполнены; расчёт трёх profit
  на одной выборке проверяется по evidence конкретного research, не этим diff.
- Research: не применяется к этой инженерной инициативе.
- Обновлено: 2026-09-25.

## Цель и границы

Провести инициативу через минимальный Engineering или Research workflow с постоянной
памятью, независимым review и согласованным результатом. Сохранить действующий формат
TASK и `done`, упростить дублирующиеся роли/правила, перевести профили на фиксированную
карту GPT-6 и связать внешний Operations Agent без переноса его репозитория.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-024-1](tasks/TASK-024-1-product-owner-memory.md) | Память инициатив и возобновление | ADR-025 | validation и сценарий двух инициатив | done |
| [TASK-024-2](tasks/TASK-024-2-gpt-6-profiles.md) | Фиксированная карта моделей и validator | — | `make ai-validate`, unit | done |
| [TASK-024-3](tasks/TASK-024-3-research-gates.md) | Business gates Research | — | research unit-тесты | done |
| [TASK-024-4](tasks/TASK-024-4-workflow-and-operations.md) | Правила двух веток, Operations handoff и ревизия ролей | ADR, TASK-024-1–3 | `make ai-validate`, сценарии REQ | done |

## Риски и rollout

- Старые инструкции и REQ-009/013 требуют согласования с новой схемой; исторические
  артефакты не удаляются.
- Старые сохранённые Research run должны оставаться читаемыми.
- Operations Agent остаётся отдельным репозиторием и не выполняет deployment в рамках
  этого эпика. Откат AI-слоя — возврат изменённых профилей/инструкций без изменения данных.

## Полное EPIC review

Независимый Reviewer проверил весь diff и повторно подтвердил устранение трёх
research findings. REQ-024, ADR-025, четыре TASK и отчёта `done`, код, тесты и
документация согласованы; незавершённый scope — PR/terminal CI/merge без релиза.
Проверенный коммит: `f0b003ada757e716795771a06b39e80528f5e069`.
Проверки: `make test` — 1058 passed; `make lint`, `make ai-validate`, `make docs`,
целевой mypy и pre-commit hooks — успешно; после форматирования hook фокусный
набор — 38 passed. Остаточный риск: единая тестовая выборка для сравниваемых
profit подтверждается evidence конкретного исследования, а не этим контрактом.
Следующий gate: Product Owner создаёт PR, ждёт terminal CI и merge в `main`.
