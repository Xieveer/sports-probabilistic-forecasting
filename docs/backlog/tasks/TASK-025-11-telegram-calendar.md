# TASK-025-11 — Календарь NHL в Telegram

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Результат

Команда `/upcoming` показывает календарные NHL события из `/calendar/nhl`
независимо от наличия Prediction row, с готовностью прогноза и коэффициентов.
Старые прогнозные команды сохраняют свой контракт. Футбол в меню не включается.

## Критерии приёмки

- [x] «Сегодня», «Завтра», `3`, `7`, `14`, `30` дней используют единые
  букмекерские сутки 08:00–08:00 Europe/Moscow; в 03:00 «Сегодня» означает
  остаток уже начавшихся суток. Горизонт `N` включает текущие сутки и `N−1`.
- [x] Известные будущие события показываются даже без прогноза или odds;
  время, участники, calendar/prediction/odds state и итог понятны по каждому.
  Перенос/отмена сохраняют идентичность и отдельную пометку.
- [x] Подтверждённо пустое окно отличается от incomplete/stale/unavailable
  coverage. API failure не выдаётся за отсутствие матчей; длинный список
  имеет ограничение Telegram и безопасную пагинацию/усечение с числом всего.
- [x] Кодовый сценарий handler → ASGI API → calendar/readiness проходит с
  fake Telegram transport и fixed clock, без production token, браузера и
  внешней сети; граничные 03:00/08:00 и все горизонты проверены.
- [x] `/predict`, `/edge` и admin команды не сломаны; help/menu описывают
  фактическое новое поведение `/upcoming`.

## Граница и проверка

- Зависит от TASK-025-1/2 и использует текущий calendar API. Новые Data Cycle
  management handlers и уведомления — TASK-025-5 после TASK-025-4.
- Red→green→refactor; целевые bot/API integration tests, регрессия старых
  команд, lint и независимый Reviewer.

## Handoff и отчёт

- Отчёт выполнения: [TASK-025-11](../../changes/done/TASK-025-11-telegram-calendar.md).
- Независимое review завершено без findings; selective commit/push выполняет
  Product Owner.
