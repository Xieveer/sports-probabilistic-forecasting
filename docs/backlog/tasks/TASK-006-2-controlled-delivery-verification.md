# TASK-006-2 — Контролируемая проверка первой доставки

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-006](../EPIC-006-first-telegram-delivery.md)
> **Требование:** [REQ-006](../../product/requirements/REQ-006-first-telegram-delivery.md)
> **ADR:** [ADR-006](../../architecture/adr/ADR-006-first-telegram-delivery-verification.md)

## Результат и границы

Реализован отдельный opt-in операторский сценарий, который после технического
acceptance может отправить распознаваемое проверочное сообщение одному
секретно-конфигурируемому получателю и безопасно зафиксировать outcome. Обычный
acceptance, scheduler и регулярные NHL digest не меняются.

## Критерии приёмки

- [x] Без явного opt-in сценарий не вызывает Telegram transport.
- [x] Вызов невозможен из CI, scheduler и non-mutating acceptance.
- [x] Tests подтверждают один выбранный recipient, redaction и корреляцию с
  release identity без токенов/chat ID/response body в логах и отчётах.
- [x] Операторская инструкция описывает preconditions, повтор после сбоя и
  ручное подтверждение владельца.

## План реализации

1. После принятия ADR создать падающие unit/integration tests для opt-in,
   запрета неявного запуска и redaction.
2. Добавить минимальный изолированный command/service contract и документацию.
3. Выполнить целевые тесты; фактическую внешнюю отправку оставить TASK-006-3.

## Затрагиваемые области и зависимости

- Telegram adapter/orchestration, tests, operator runbook и handoff.
- Реализация может идти после принятия ADR-006 и локального security baseline
  TASK-006-1; реальная отправка остаётся зависимой от immutable images/evidence
  и TASK-006-3. Production secrets в тестах не требуются.

## Проверка

- `tests/test_delivery_verification.py`, `make test-unit`, `make security` и
  `make production-check` пройдены 2026-08-09; отсутствие вызова в acceptance
  и scheduler подтверждено тестом.

## Handoff и отчёт

- Отчёт выполнения: [TASK-006-2](../../changes/done/TASK-006-2-controlled-delivery-verification.md).
- Follow-up / findings: ссылка для TASK-006-3 и security review.
