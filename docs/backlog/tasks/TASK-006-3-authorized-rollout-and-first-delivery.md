# TASK-006-3 — Локальная проверка и первое сообщение

> **Статус:** blocked
> **Владелец:** команда разработки
> **Эпик:** [EPIC-006](../EPIC-006-first-telegram-delivery.md)
> **Требование:** [REQ-006](../../product/requirements/REQ-006-first-telegram-delivery.md)
> **ADR:** [ADR-006](../../architecture/adr/ADR-006-first-telegram-delivery-verification.md)

## Результат и границы

После отдельного разрешения владельца команда разработки локально запускает
контролируемую проверку delivery, а владелец получает одно Telegram-сообщение.
Задача не запускает команды на VPS.

## Критерии приёмки

- [ ] Получено и зафиксировано явное разрешение владельца на локальную
  Telegram-отправку.
- [ ] Локальный environment содержит `BOT_TOKEN` и ровно один
  `SF_DELIVERY_VERIFICATION_CHAT_ID` без их вывода.
- [ ] Delivery-verification запущен один раз из workspace; владелец
  подтвердил получение сообщения.
- [ ] Evidence содержит release/model identity и безопасные статусы, но не
  secrets, chat ID и полные внешние ответы.

## План реализации

1. Проверить локальную secret-конфигурацию без вывода значений.
2. После явного разрешения запустить delivery-verification один раз.
3. Получить подтверждение владельца и оформить done-отчёт либо finding.

## Затрагиваемые области и зависимости

- Local workspace и Telegram transport; VPS, registry и production PostgreSQL
  не входят в эту задачу и остаются у внешнего server operations agent.
- Блокеры: `SF_DELIVERY_VERIFICATION_CHAT_ID`, отдельное разрешение владельца,
  TASK-006-1, TASK-006-2, ADR-006 accepted.

## Проверка

- Явный локальный запуск команды, безопасный stdout status и подтверждение
  владельца о получении сообщения.

## Handoff и отчёт

- Отчёт выполнения: создаётся командой разработки в `docs/changes/done/`.
- Follow-up / findings: передать внешний VPS rollout server operations agent.
