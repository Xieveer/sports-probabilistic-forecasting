# TASK-041-2 — Два advanced эксперимента клубного 1X2

> **Статус:** done — исследовательское решение ITERATE
> **Задача:** [TASK-041-2](../../backlog/tasks/TASK-041-2-advanced-experiment.md)
> **Требование:** [REQ-041](../../product/requirements/REQ-041-advanced-club-1x2-search.md)

## Изменено

На общем пуле девяти клубных соревнований построены 510 long и 1 020 wide
advanced признаков. CatBoost обучен с четырьмя event-level временными fold и
отдельной Optuna study на каждую стратегию. Обе study имеют 50 COMPLETE,
0 FAIL, 0 PRUNED trials. Калибровка и отдельный feature selection отключены.
Выбор параметров использовал последние 10 000 событий до holdout; финальный
shadow-refit использовал всю train-историю.

На закреплённом holdout 2025/26 для обеих моделей рассчитаны полный 1X2
logloss, accuracy, Brier и правило одной ставки при `edge > 0.05`.
Long: logloss `1.0057`, 1 153 ставок, coverage `41.1%`, ROI `−13.16%`.
Wide: logloss `0.9991`, 1 079 ставок, coverage `38.5%`, ROI `−12.57%`.
Подробные параметры, метрики, bootstrap, baseline и ограничения находятся в
[каноническом отчёте](../../research/epic-041-advanced-club-1x2.md).

## Фактическая проверка

- MLflow runs `f1df41fd678041b7ab1ee895b94fc5c3` и
  `b56175b70a4b444f93de995940283728` имеют статус FINISHED и business
  metrics; исходные SQLite studies и shadow `.cbm` сохранены локально.
- Независимый reviewer сверил counts Optuna, MLflow market/betting metrics,
  SHA-256 processed parquet и моделей. Пересчёт trace совпал с отчётом:
  long turnover `11 530`, profit `−1517.73`; wide turnover `10 790`,
  profit `−1356.14`. Кодовых блокирующих findings нет.
- `make lint`, `make ai-validate` и `make docs` завершились успешно;
  сборка Sphinx сообщила 155 предупреждений из существующей документации.

## Не изменено и остаточные риски

Production pointer, materialization и выдача в боте не изменялись.
Исторические котировки не имеют проверенного as-of времени; даже будущий
положительный backtest потребует проверки реализуемости цены и нового
out-of-sample периода. Критерий ROI ≥5% из REQ-021 не достигнут.
