# Оркестрация portfolio heavy path

`portfolio_refresh` читает `SF_PORTFOLIO_CATALOG` (по умолчанию
`conf/portfolio/default.yaml`) при разборе DAG. Каждый deployment profile
становится отдельной heavy-задачей с полями tournament, source, model pool и
market/spec. Добавление поддерживаемого турнира выполняется через каталог и
profile, без изменения списка в DAG.

Ключ блокировки выводится из пары `tournament/source`; повтор того же target
сериализуется через свой `flock`, а независимые targets ограничиваются
существующим Airflow pool `SF_REFRESH_POOL`. Число slots pool определяет
допустимую конкурентность и не должно увеличиваться без измерений источников.

`dvc.yaml` остаётся отдельным локальным контуром воспроизводимости. Его features
stage выбирает все готовые interim-турниры с Hydra-конфигом; DVC не является
production scheduler-ом.

Legacy `data_refresh` сохранён для ручной диагностики с `schedule=None`.
Плановый Airflow `portfolio_refresh` читает только deployment profiles;
действующий production NHL использует systemd и Worker, без Airflow.
