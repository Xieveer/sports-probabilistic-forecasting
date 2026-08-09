# TASK-002-3 — Конфигурируемый утренний digest и failure-notify

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-002](../EPIC-002-nhl-production-mvp.md)
> **Требование:** [REQ-002](../../product/requirements/REQ-002-nhl-production-mvp.md)
> **ADR:** [ADR-002](../../architecture/adr/ADR-002-nhl-telegram-notification-orchestration.md)

## Результат и границы

Подключить TASK-002-1 и TASK-002-2 к heavy path notification-профиля: initial
digest каждому allowlist-получателю после успешного refresh/gate и краткое
Telegram-уведомление администраторам при неуспехе. NHL-профиль задаёт запуск в
10:00 `Europe/Moscow`.
Не добавлять 15-минутный poll и не публиковать API.

## Критерии приёмки

- [x] DAG берёт расписание, timezone и защиту от параллельного heavy refresh из
  профиля; NHL-профиль стартует ежедневно в 10:00 МСК.
- [x] После успешного refresh/gate каждый allowlist chat ID получает один
  digest матчей на 48 часов, включая вариант без коэффициентов.
- [x] Ошибка refresh либо gate не вызывает initial digest и уведомляет только
  admin list; allowlist-пользователь не получает служебный текст.
- [x] Initial digest создаёт baseline notification state.
- [x] Общая validation запускается после refresh и до quality gate/initial digest.

## План реализации

1. Добавить падающие DAG source и orchestration tests для timezone, fan-out,
   baseline и failure path.
2. Добавить notification-профиль и изменить DAG factory/post-refresh orchestration
   для конфигурационного timezone-aware расписания, gate dependency и вызова
   notification service.
3. Добавить безопасный admin notification adapter/обработку failure без токенов
   в логах.
4. Выполнить целевые тесты и `make test-unit`.

## Затрагиваемые области и зависимости

- TASK-002-1 и TASK-002-2 должны быть `done`.
- DAG factory и notification-профили, shared DAG helpers, post-refresh
  orchestration, Telegram adapter, compose/env documentation, tests.

## Проверка

- Целевые orchestration/DAG/Telegram mock tests.
- `make test-unit`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-002-3-nhl-morning-digest](../../changes/done/TASK-002-3-nhl-morning-digest.md).
- Follow-up / findings: нет.
