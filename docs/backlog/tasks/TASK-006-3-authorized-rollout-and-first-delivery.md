# TASK-006-3 — Разрешённый rollout и первое сообщение

> **Статус:** blocked
> **Владелец:** DevOps Operations Agent
> **Эпик:** [EPIC-006](../EPIC-006-first-telegram-delivery.md)
> **Требование:** [REQ-006](../../product/requirements/REQ-006-first-telegram-delivery.md)
> **ADR:** [ADR-006](../../architecture/adr/ADR-006-first-telegram-delivery-verification.md)

## Результат и границы

После отдельного разрешения владельца production-candidate развёрнут по handoff,
а владелец получил одно контролируемое Telegram-сообщение. Задача не расширяет
функциональность и не выполняет массовую рассылку.

## Критерии приёмки

- [ ] Получено и зафиксировано явное разрешение владельца на rollout и
  внешнюю Telegram-отправку.
- [ ] Пройдены migration/health/readiness/acceptance по production handoff.
- [ ] Delivery-verification запущен один раз в разрешённом окружении; владелец
  подтвердил получение сообщения.
- [ ] Evidence содержит версии и безопасные статусы, но не secrets, chat ID и
  полные внешние ответы; rollback готов при ошибке.

## План реализации

1. Снять blocker только после письменного разрешения владельца и готового
   evidence TASK-006-1/006-2.
2. Выполнить rollout и безопасный technical acceptance по runbook.
3. Запустить delivery-verification, получить подтверждение владельца и оформить
   done-отчёт либо безопасный rollback/finding.

## Затрагиваемые области и зависимости

- VPS, secret store, registry, production PostgreSQL и Telegram — внешние
  системы под ответственностью Operations Agent.
- Блокеры: отдельное разрешение владельца, TASK-006-1, TASK-006-2, ADR-006
  accepted.

## Проверка

- `make acceptance-check` в operator environment, evidence rollout и явное
  подтверждение владельца о получении сообщения.

## Handoff и отчёт

- Отчёт выполнения: создаётся implementer/Operations Agent в `docs/changes/done/`.
- Follow-up / findings: rollback или security finding при неуспехе.
