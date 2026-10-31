# TASK-041-1 — Event-level Optuna и betting 1X2

> **Статус:** done
> **Инициатива:** [EPIC-041](../EPIC-041-advanced-club-1x2-search.md)

## Результат

Optuna поддерживает группировку по `id` для 1X2 и требует не менее заданного
числа завершённых trials. Holdout betting выбирает не более одного исхода на
матч, сообщает финансовые метрики и trace.

## Проверка

Адресные тесты Optuna, TSCV и 1X2 betting, регрессия действующих бинарных рынков.
Результат и остаточный риск записаны в [отчёте done](../../changes/done/TASK-041-1-event-optuna-betting.md).
