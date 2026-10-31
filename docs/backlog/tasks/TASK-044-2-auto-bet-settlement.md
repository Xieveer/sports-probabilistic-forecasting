# TASK-044-2 — Автоматический расчёт открытых ставок

> **Статус:** done
> **Эпик:** [EPIC-044](../EPIC-044-bets-cycle-report.md)
> **Требование:** [REQ-044](../../product/requirements/REQ-044-automatic-bet-settlement-and-season-report.md)
> **Решение:** [ADR-044](../../architecture/adr/ADR-044-automatic-bet-settlement.md)

После canonical import тот же Data Cycle рассчитывает однозначные открытые
ставки NHL `winner_withOT`, сохраняет выплату и audit, а отдельный outbox
доставляет владельцу сводку после завершения run. Неоднозначные случаи
остаются открытыми с причиной.

[Отчёт](../../changes/done/TASK-044-2-auto-bet-settlement.md).
