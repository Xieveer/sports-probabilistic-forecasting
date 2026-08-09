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

`dvc.yaml` остаётся отдельным dev/CI контуром воспроизводимости. Новый DAG не
изменяет его multirun stages и не делает DVC production scheduler-ом.

Legacy `data_refresh` сохраняется на время перехода; production scheduler
должен включать только один из двух DAG для одного и того же турнира, иначе
per-key lock лишь сериализует дублирующую работу.
