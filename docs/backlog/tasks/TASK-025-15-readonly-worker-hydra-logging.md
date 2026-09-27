# TASK-025-15 — Логирование Hydra в read-only Worker

> **Статус:** done — код и независимое review завершены; runtime gate в TASK-025-9
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Наблюдаемый дефект

Ручной Data Cycle v1.2.3 `e96868fa-04cd-4c3a-bff8-c5b34f51b709`
опубликовал NHL source snapshot, затем Worker завершился exit 1 до canonical
materialization. Запуск CLI из `run-canonical-refresh.sh` переопределил Dockerfile
CMD и не передал аргументы отключения файлового логирования Hydra. В read-only
контейнере Hydra попыталась создать `/app/canonical_full_refresh_cli.log` и
получила `Errno 30`. После host stop proof run закрыт как
`failed/source_fetch_failed`, одно итоговое уведомление доставлено; оба NHL
таймера остались выключенными.

## Критерии исправления

- [x] Runner запускает canonical CLI с логированием в stdout и без создания
  Hydra output files в read-only `/app`.
- [x] Red-тест воспроизводит отсутствие безопасных Hydra overrides в runtime
  команде; после исправления он и соседние runner/CLI тесты проходят.
- [x] Не меняются состав стадий, права контейнера, read-only root filesystem,
  схема БД и данные модели.
- [x] Независимый Reviewer не обнаруживает P0–P2; version, handoff и release
  gate согласованы как v1.2.4.
- [ ] После immutable tag/evidence и свежего backup один ручной NHL Data Cycle
  подтверждает 30-дневный календарь, terminal stages и уведомление; затем
  проверяется первый плановый запуск. Runtime acceptance остаётся в TASK-025-9.

## Handoff

[Отчёт выполнения](../../changes/done/TASK-025-15-readonly-worker-hydra-logging.md)
заполняется после целевых проверок. Production incident и runbook ведёт
Operations Agent в отдельном репозитории.
