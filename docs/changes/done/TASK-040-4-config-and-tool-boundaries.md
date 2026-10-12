# TASK-040-4 — Границы конфигурации и инструментов

> **Статус:** реализация, локальные проверки и независимое review завершены
> **Задача:** [TASK-040-4](../../backlog/tasks/TASK-040-4-config-and-tool-boundaries.md)
> **Решение:** [ADR-041](../../architecture/adr/ADR-041-local-data-stage-tournament-selection.md)

## Изменено

`dvc.yaml` больше не перечисляет турниры для features. Небольшой CLI находит
каждый `data/interim/<name>/matches_interim.parquet`, требует соответствующий
Hydra-конфиг и запускает существующий feature builder. Плановый legacy Airflow
`data_refresh` переведён в ручной режим (`schedule=None`); плановый
`portfolio_refresh` продолжает брать состав из deployment profiles.
README и `dvc.yaml` описывают фактический локальный и production контуры.

## Фактическая проверка

- Red → green: тесты автообнаружения и ручного legacy DAG сначала завершились
  ошибкой, после исправления прошли.
- Реальное локальное interim содержит 10 подготовленных турниров, включая
  `football_top_leagues`; Hydra `features_pipeline` успешно скомпонован для
  каждого. `dvc dag` сохранил ingest → clean → features → validate.
- Новый CLI выполнен для клубного interim в отдельном временном каталоге:
  созданы и валидированы 63 242 train-long и 31 621 train-wide строка.
- 12 целевых тестов оркестрации и новых контрактов прошли. Независимый
  Reviewer не нашёл P0/P1/P2 в изменённом срезе. `make test-unit` завершился
  результатом 1757 passed, 18 deselected.

## Не изменено и остаточные риски

Production systemd/Worker, модельные pointers и расписание сервера не менялись.
Legacy Airflow DAG остаётся доступным для ручного запуска. Проверка нового вида
спорта и фактического production расписания не входит в локальный клубный E2E.
