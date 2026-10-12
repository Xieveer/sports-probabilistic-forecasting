# TASK-039-1 — Убрать Odds API из ежедневного Data Cycle

> **Статус:** done — исправление прошло review, CI и production cycle
> **Эпик:** [EPIC-039](../EPIC-039-v1-3-7-daily-cycle.md)
> **Тип:** исправление регрессии подтверждённого [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **Ветка:** `initiative/epic-039-v1-3-7-daily-odds`

## Дефект и результат

Ежедневный runner уже отключает odds в source snapshot, но Worker получает Hydra default `data_odds_enabled=true` и запрашивает The Odds API. Поэтому полный Data Cycle v1.3.6 потратил запросы при пересчёте прогнозов. Нужно явно отключить стадию `data_odds` в этом runner, не меняя live odds путь `/predict` и явный ручной refresh.

## Проверка

- Контрактный тест runner сначала воспроизводит отсутствие override, затем проходит с ним.
- Тест реальных генераторов подтверждает, что новый результат влияет на следующие rolling/другие признаки, а прошлый прогноз не меняется.
- Фактический production run использует проверенный архив, сохраняет прогнозы, отмечает `data_odds=skipped` и не создаёт новый odds acquisition attempt. `/predict` продолжает возвращать live odds при наличии линии.
- Независимый review проверяет код, regression/security и границы исправления; terminal CI/Security и release gates обязательны.

## Передача

Developer фиксирует результат в [отчёте done](../../changes/done/TASK-039-1-daily-cycle-odds.md). Product Owner ведёт отдельный immutable release `v1.3.7` и production gate.
