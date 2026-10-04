# TASK-025-18 — Явное отключение будущих odds без остановки прогнозов

> **Статус:** cancelled — оставшиеся критерии сняты решением владельца 2026-10-03
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Цель

В production v1.2.5 три независимых Odds API ключа вернули HTTP 401
`INVALID_KEY`. Владелец решил продолжать готовность NHL без odds.
Календарь и прогнозы должны публиковаться независимо от этой внешней
подписки; ежедневный цикл не должен посылать заведомо бесполезный HTTP
запрос и маскировать отсутствие коэффициентов как готовность.

## Критерии приёмки

- [x] Явный runtime switch отключает source odds post-step и future odds acquisition;
  значение по умолчанию сохраняет прежний режим ON.
- [x] В режиме OFF нет Odds API HTTP вызовов, `data_odds` имеет
  `partial_success` и наблюдаемые counts, readiness odds остаётся `missing`.
- [x] Calendar, quality, predictions, publication и archive продолжаются;
  при их успехе итог run `partial_success` и одно итоговое уведомление.
- [x] Неверное значение switch отклоняется до HTTP, без молчаливого OFF.
- [x] Red→green и независимое review подтверждают ON/OFF paths, default,
  отсутствие дубля executor, Compose/runner и football contract fixture.
- [ ] v1.2.6 tag/evidence, backup/rollback, production manual run и первый
  scheduled run проходят; таймер включается только после успеха.

## Handoff

Кодовый результат и runtime gate фиксируются в
[отчёте выполнения](../../changes/done/TASK-025-18-optional-future-odds.md).

## Итог закрытия EPIC-025

Реализация включена в выпущенную v1.2.15. Неотмеченные выше критерии отдельного релиза/проверки не подтверждены в этой TASK и сняты при принятии итогового результата EPIC-025 владельцем. Это не отметка об их успешном выполнении.

Production run v1.2.15 прошёл без future odds HTTP; итог success.
