# EPIC-006 — Первое подтверждённое Telegram-сообщение

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-006](../product/requirements/REQ-006-first-telegram-delivery.md)
> **ADR:** [ADR-006](../architecture/adr/ADR-006-first-telegram-delivery-verification.md)

## Цель и границы

Перевести опубликованный production-кандидат в первый наблюдаемый результат для
владельца: контролируемое Telegram-сообщение, отправленное из локального
workspace разработки. Эпик не выполняет deployment или команды на VPS.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-006-1](tasks/TASK-006-1-release-gate-remediation.md) | Решение security/release blockers и проверяемый candidate | REQ-005 / handoff | security, published image evidence, production-check | done |
| [TASK-006-2](tasks/TASK-006-2-controlled-delivery-verification.md) | Узкий opt-in сценарий первой доставки | ADR-006 accepted, local security baseline TASK-006-1 | red/green tests, no scheduler/acceptance invocation | done |
| [TASK-006-3](tasks/TASK-006-3-authorized-rollout-and-first-delivery.md) | Локальная проверка и подтверждение получения | TASK-006-1, TASK-006-2, явное разрешение владельца | Локальная отправка + сообщение получено владельцем | blocked |

## Риски и rollout

- Security audit зелёный, immutable images опубликованы; `TASK-006-3` остаётся
  `blocked` до настройки локального recipient и явной Telegram-отправки.
- Успешный healthcheck или bot heartbeat не равен полученному пользователем
  сообщению; финальным доказательством эпика служит подтверждение владельца.
- Откат rollout выполняется по [production handoff](../operations/production-handoff.md);
  delivery-verification не должна создавать миграции или менять прогнозы.
