# EPIC-041 — Расширенное исследование клубного 1X2

> **Статус:** done — исследовательское решение ITERATE
> **Владелец:** Product Owner
> **Требование:** [REQ-041](../product/requirements/REQ-041-advanced-club-1x2-search.md)

## Память Product Owner

- Инициатива: `EPIC-041`.
- Ветка: `initiative/epic-041-advanced-club-1x2` в отдельном worktree.
- Этап: две модели обучены и независимо проверены; исследование завершено решением ITERATE.
- Цель: два сравнимых исследовательских кандидата и честная финансовая проверка.
- Решение: один `winner_1x2`, long и wide стратегии; минимум 50 завершённых
  trials на каждую, TSCV только на train, без калибровки и feature selection.
- Betting: фиксированный порог `edge > 0.05`, одна ставка на матч по максимуму
  edge; flat stake 10 единиц при банке 50 000; весь holdout в знаменателе покрытия.
- Evidence: [EPIC-040](EPIC-040-club-football-platform-e2e.md) дал baseline и
  тот же temporal holdout; [ADR-042](../architecture/adr/ADR-042-club-1x2-research-evaluation.md)
  закрепляет способ оценки.
- Evidence: [отчёт исследования](../research/epic-041-advanced-club-1x2.md),
  MLflow runs `f1df41fd678041b7ab1ee895b94fc5c3` и
  `b56175b70a4b444f93de995940283728`; обе Optuna study имеют
  50 COMPLETE и 0 FAIL. ROI при `edge > 0.05`: `−13.16%` long и
  `−12.57%` wide; базовые модели тоже отрицательны.
- Предыдущая роль: независимый Reviewer — сверил runs, studies, trace,
  SHA-256 и расчёт метрик; кодовых блокеров нет, документационный gate устранён.
- Следующая роль: Product Owner — зафиксировать ITERATE и открыть отдельную
  инициативу только после выбора следующей исследовательской гипотезы.
- Release intent: production выпуск не запрошен.
- Обновлено: 2026-10-12.

## Задачи

| Задача | Результат | Статус |
| --- | --- | --- |
| [TASK-041-1](tasks/TASK-041-1-event-optuna-betting.md) | Event-level Optuna и одно событие — одна ставка | done |
| [TASK-041-2](tasks/TASK-041-2-advanced-experiment.md) | Два advanced запуска, отчёт и решение | done |

## Риски

Исторические цены Smart Tables не имеют проверенного as-of времени. Long
кандидат может дать отрицательный остаток ничьей; такие матчи исключаются из
ставок с измерением доли и сохраняются в знаменателе общего покрытия.
