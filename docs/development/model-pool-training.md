# Обучение model pool

`build_pool_dataset` из `sports_forecast.training.model_pool` объединяет
датасеты только для членов одного `model_pool` и одного `market_spec` из
каталога `conf/portfolio/default.yaml`. До объединения он проверяет спорт,
принадлежность турнира пулу и точное совпадение контрактов колонок. В итоговый
датафрейм добавляется колонка `tournament`; она хранит происхождение каждой
строки.

Для запуска обучения вызывающий код сначала формирует `PooledDataset`, затем
передаёт его `frame` в `SingleExperimentRunner.run_experiment_with_dataframe`.
В конфигурации runner должен быть явно задан `model_pool.name` и
`model_pool.identity`. Identity передаётся в MLflow-теги, а артефакты сохраняются
в изолированном пути `models/pools/<pool>/<market_spec>/...`. Этот маршрут не
изменяет legacy-путь NHL и не выполняет promotion.

После вычисления метрик вызывающий код создаёт `CandidateReport` и сохраняет его
через `write_candidate_report`. Файл `candidate-report.json` содержит:

- `model_identity`;
- `ml_metrics`: `logloss`, `auc`, `brier`;
- `betting_metrics`: `roi`, `coverage`, `n_bets`;
- `simulation_metrics`: `roi_std`.

Отчёт является отчётом кандидата. Решение о promotion, указатель production и
подключение реального футбольного источника данных находятся за границами
TASK-003-2.
