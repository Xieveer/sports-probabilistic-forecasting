# EPIC-025 — Расписание бота и готовность NHL к сезону

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Память Product Owner

- Инициатива: `EPIC-025`.
- Ветка инициативы: `initiative/epic-025-bot-readiness` в основном каталоге проекта.
- Workflow / этап: `engineering / TASK-025-7 reviewed, dependent scope в TASK-025-4/8/10`.
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
  Срез readiness TASK-025-2 прошёл correction cycle по двум P1, повторное
  независимое review и 47 целевых тестов; pre-commit чистый. Content commit
  `9ef0e73` отправлен в origin. `odds.failed` и сбор будущих котировок
  остаются зависимостями TASK-025-6, поэтому TASK-025-2 помечен blocked.
  Read-only VPS preflight подтвердил, что NHL systemd timer установлен, но
  `disabled/inactive`, последнего и следующего запуска нет. Daily scheduler
  сейчас не работает; Docker/DB/run history недоступны текущему SSH-пользователю.
  Исследование The Odds API выявило риск ложного `ready` у трёхисходного h2h,
  если старый OddsStore отбросил ничью. TASK-025-2 получил второй correction
  cycle: provenance и строгая семантика рынка исправлены, re-review чистое,
  82 целевых теста и pre-commit прошли; commit `8e85193` опубликован.
  TASK-025-3 создал durable run до source и сохранил failed calendar attempt;
  четыре findings Reviewer исправлены, повторное review чистое, 30 целевых
  тестов прошли. Content commit TASK-025-3 `705db65` опубликован, повторный
  commit gate прошёл 30 тестов и все hooks. TASK-025-7 добавил policy-driven
  terminal guard и безопасный summary/history query DTO; после correction cycle
  повторный Reviewer не нашёл блокирующих findings (22 целевых теста).
  Полные счётчики в TASK-025-10, защищённый HTTP в TASK-025-4,
  recovery/fencing в TASK-025-8; будущие odds — в TASK-025-6.
- Решения: [ADR-026](../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)
  принят после независимого review: календарь независим от прогноза, control
  state в PostgreSQL, ограниченный control API и systemd dispatcher;
  для NHL один связанный цикл;
  ручная команда повторяет data job без перезапуска служб; футбол проверяется
  по общему контракту без включения в `1.2.0`.
- Артефакты: [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md).
- Предыдущая роль: Reviewer — повторное review TASK-025-7 без блокирующих
  findings после terminal/summary correction cycle.
- Следующая роль: Product Owner — content commit TASK-025-7; затем Developer —
  TASK-025-6 и control/Telegram срезы.
- Открытые вопросы / блокеры: ежедневный NHL timer на VPS выключен; нет
  привилегированного read-only доступа к Docker/DB и подтверждённого backup,
  runtime run history и rollback digest. Это production release NO-GO до
  исправления и проверки. EPIC-023 имеет статус `in_progress`, пересечение
  требует сверки.
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
| [TASK-025-2](tasks/TASK-025-2-event-readiness.md) | Readiness прогноза и коэффициентов поверх календаря | missing/stale/deadline, футбол fixture | blocked: `odds.failed` в TASK-025-6 |
| [TASK-025-3](tasks/TASK-025-3-data-cycle-runs.md) | Durable ingress, failed acquisition, stage wiring | source failure, shell path, migration | done; runtime gate остаётся |
| [TASK-025-6](tasks/TASK-025-6-future-odds.md) | Calendar-first future NHL odds | semantic evidence, quota, identity, freshness | backlog |
| [TASK-025-7](tasks/TASK-025-7-data-cycle-recovery-summary.md) | Terminal stages, summary и run history query contract | stage faults, coverage, safe DTO | blocked: producers/API в TASK-025-10/4 |
| [TASK-025-8](tasks/TASK-025-8-executor-fencing.md) | Executor recovery/fencing after crash | PostgreSQL race, no duplicate executor | backlog |
| [TASK-025-9](tasks/TASK-025-9-release-readiness.md) | Production v1.2.0 and NHL daily scheduler | terminal CI, migration, health/smoke, timer run | backlog |
| [TASK-025-10](tasks/TASK-025-10-run-summary-producers.md) | Full run summary producers and coverage | same-run counters, n/a denominator, football fixture | backlog |
| [TASK-025-4](tasks/TASK-025-4-schedule-control.md) | Persisted schedule, manual control, dispatcher | admin auth, races, restart, catch-up | backlog |
| [TASK-025-5](tasks/TASK-025-5-telegram-experience.md) | Telegram calendar, admin controls, notifications, code-based E2E | 08:00, auth, idempotency, bot→API | backlog |

Operations release gate зафиксирован в TASK-025-9; фактические inputs и
rollback target уточняются по результатам завершённых функциональных срезов.

## Риски и rollout

Бот может быть исправен при пустой витрине прогнозов; источник, materialization
и scheduler требуют отдельной проверки. До rollout необходимы фактические
runtime evidence, rollback target и terminal CI для exact commit.

## Полное EPIC review

Ожидает завершения задач и независимого review.
