# EPIC-025 — Расписание бота и готовность NHL к сезону

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Память Product Owner

- Инициатива: `EPIC-025`.
- Ветка инициативы: `initiative/epic-025-bot-readiness` в основном каталоге проекта.
- Workflow / этап: `engineering / TASK-025-2 reviewed, зависимость TASK-025-3`.
- Исходная цель: календарь NHL независимо от прогноза, готовность событий,
  админ-управление Data Cycle и выпуск `1.2.0`;
  [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md).
- Критерии приёмки и DoD: подтверждены владельцем в REQ-025; независимый
  review, CI и production health/smoke входят в release gate.
- Релиз: production `1.2.0` запрошен пользователем.
- Выполнено: владелец дал полную постановку в Google Doc; REQ-025 приведён к
  ней и подтверждена трактовка «Сегодня» до 08:00 МСК; ограничение API
  прогнозами, 48-часовой минимум source и расхождение `/refresh` с systemd
  зафиксированы; 25 базовых тестов бота прошли. Read-only Operations audit
  не смог подтвердить runtime timer из-за SSH timeout. Read-only probe
  configured NHL API 2026-09-26 вернул HTTP 200 и 3 игры на 30 сентября,
  а октябрьский якорь вернул опубликованные дальние матчи; production store
  и его 30-дневное покрытие всё ещё не проверены. Первый diff TASK-025-1
  прошёл correction cycle после findings и повторное независимое review
  без блокирующих замечаний; Developer выполнил 61 тест/lint/Alembic head,
  Reviewer повторно выполнил 46 целевых тестов. Ошибки mypy из первого
  commit gate исправлены; повторный commit gate прошёл все hooks.
  Проверенный content commit: `b23e2ccc3b869667e95e0f46fbe472731a6f1c8e`.
- Решения: [ADR-026](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)
  принят после независимого review: календарь независим от прогноза, control
  state в PostgreSQL, ограниченный control API и systemd dispatcher;
  для NHL один связанный цикл;
  ручная команда повторяет data job без перезапуска служб; футбол проверяется
  по общему контракту без включения в `1.2.0`.
- Артефакты: [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md).
- Предыдущая роль: Reviewer — повторное review TASK-025-2 без findings после
  устранения двух P1; 47 целевых тестов прошли.
- Следующая роль: Reviewer — content commit gate TASK-025-2; затем Developer —
  реализовать TASK-025-3.
- Открытые вопросы / блокеры: фактическая работа runtime scheduler не
  проверена из-за недоступного SSH. EPIC-023 имеет статус `in_progress`,
  пересечение требует сверки.
- Обновлено: 2026-09-26.

## Цель и границы

Реализовать [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md):
календарь и готовность событий, Data Cycle с управлением из Telegram,
операционную готовность NHL и выпуск `1.2.0` в production. Футбол проверяется
контрольным сценарием без включения в пользовательское меню.

## Декомпозиция

| Задача | Результат | Проверка | Статус |
|---|---|---|---|
| [TASK-025-1](tasks/TASK-025-1-calendar-api.md) | Calendar acquisition → canonical store → API | 08:00, 30 суток, coverage, revision, футбол fixture | done |
| [TASK-025-2](tasks/TASK-025-2-event-readiness.md) | Readiness прогноза и коэффициентов поверх календаря | missing/stale/deadline, футбол fixture | blocked: `odds.failed` в TASK-025-3 |
| [TASK-025-3](tasks/TASK-025-3-data-cycle-runs.md) | Durable Data Cycle, stage results и failed acquisition | fault injection, summary, recovery | backlog |
| [TASK-025-4](tasks/TASK-025-4-schedule-control.md) | Persisted schedule, manual control, dispatcher | admin auth, races, restart, catch-up | backlog |
| [TASK-025-5](tasks/TASK-025-5-telegram-experience.md) | Telegram calendar, admin controls, notifications, code-based E2E | 08:00, auth, idempotency, bot→API | backlog |

Следующий зависимый срез: Operations readiness и выпуск. Его TASK создаётся
после реализации предыдущих срезов, чтобы включить проверенный release scope.

## Риски и rollout

Бот может быть исправен при пустой витрине прогнозов; источник, materialization
и scheduler требуют отдельной проверки. До rollout необходимы фактические
runtime evidence, rollback target и terminal CI для exact commit.

## Полное EPIC review

Ожидает завершения задач и независимого review.
