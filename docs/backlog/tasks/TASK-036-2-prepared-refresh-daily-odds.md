# TASK-036-2 — Сбор текущих коэффициентов после проверки архива

> **Статус:** done — локальная реализация и целевые тесты пройдены; независимый review и production gate ожидаются
> **Владелец:** Developer
> **Эпик:** [EPIC-036](../EPIC-036-registry-rollout.md)

## Дефект

Worker, получающий уже подготовленный source-first archive, принудительно
отключал `data_odds` и отмечал стадию `skipped`. Поэтому расписанный refresh
обновлял прогнозы, но не сохранял текущие NHL котировки. В production preflight
это проявилось как ноль будущих NHL odds observations.

## Критерии

1. Подготовленный архив полностью проверяется до первого запроса к Odds API.
2. При включённом `data_odds_enabled` Worker выполняет не более одного
   ограниченного NHL future odds batch и сохраняет outcome в acquisition
   attempt и стадии `data_odds`.
3. При выключенном `data_odds_enabled` provider не вызывается, сохраняется
   прежний пропуск стадии; обычный source refresh сохраняет прежнюю семантику
   выключенного флага.
4. Ошибка проверки архива не допускает обращения к Odds API.

## Изменение

Подготовленный input загружается и проверяется до запуска odds stage. Только
после успешной проверки stage вызывает существующий `run_nhl_future_odds_batch`.
Новый scheduler, provider client или повторный вызов batch не добавлялся.

Детали и проверки: [отчёт](../../changes/done/TASK-036-2-prepared-refresh-daily-odds.md).
