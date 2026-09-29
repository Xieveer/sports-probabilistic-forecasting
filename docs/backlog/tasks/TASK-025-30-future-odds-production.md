# TASK-025-30 — Включить будущие коэффициенты в production cycle и API

> **Статус:** reviewed_pending_release
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)

## Дефект

В production profile v1.2.10 `SF_DATA_ODDS_ENABLED=false`, поэтому отдельная
стадия `data_odds` не обращается к The Odds API. У API отсутствуют secret mounts
и `ODDS_API_KEY_*_FILE`, хотя `live_pinnacle=true` используется в сообщениях
бота. Простое включение profile flag одновременно запускало исторический
OddsStore backfill в source-acquirer, который не нужен для будущих матчей и
может остановить весь цикл до materialization.

## Критерии

- [x] При `SF_DATA_ODDS_ENABLED=true` Worker получает `data_odds_enabled=true`
  и выполняет ограниченный batch для будущих NHL матчей.
- [x] Ежедневный source snapshot пропускает исторический OddsStore backfill;
  календарь и прогноз не зависят от доступности исторической линии.
- [x] API получает только четыре file-backed Odds API credentials через Compose
  secrets и может вернуть live Pinnacle в `/predict` для сообщения бота.
- [x] Production Compose validator отвергает отсутствие этих secret mounts и
  plain-text ключ в environment.
- [ ] На изолированном контуре подтверждены будущие odds, `/predict` и текст
  Telegram с коэффициентами при ограничении ресурсов.
- [ ] На production подтверждены активный профиль `true`, результат стадии
  `data_odds`, API live quote и сообщение бота.

## Граница

Исторический OddsStore backfill сохраняется как отдельная ручная процедура.
Схема БД, модель, формула edge и бот formatter не меняются. Production
включается после review, CI, исправления archive-sync и безопасного завершения
старого run.

Результат — в [отчёте](../../changes/done/TASK-025-30-future-odds-production.md).
