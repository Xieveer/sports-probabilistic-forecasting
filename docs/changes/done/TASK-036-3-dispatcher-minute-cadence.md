# TASK-036-3 — Минутный запуск Data Cycle dispatcher

> **Статус:** подготовлено; production gate ожидается
> **Задача:** [TASK-036-3](../../backlog/tasks/TASK-036-3-dispatcher-minute-cadence.md)

## Изменение

В `sports-forecast-data-cycle-dispatcher.service` установлен
`StartLimitIntervalSec=0`; burst limit убран. Сохранился timer с
`OnUnitActiveSec=60s`, service timeout 2 минуты и защита активного цикла в
PostgreSQL. Runbook дополнился процедурой проверки 20 ticks.

## Доказательства

- Production read-only preflight v1.3.1: service с `StartLimitBurst=5` за
  15 минут достиг `start-limit-hit`, heartbeat устарел. Это исходный дефект.
- Контрактный тест на исходном шаблоне упал на ожидании
  `StartLimitIntervalSec=0`; после правки тот же тест прошёл.
- `PYTHONPATH=. ../epic-035-v1-3-2-release/.venv/bin/pytest -q
  tests/test_production_topology.py`: 24 passed.
- `../epic-035-v1-3-2-release/.venv/bin/ruff check
  tests/test_production_topology.py` и `git diff --check`: passed.
- Локальный `systemd-analyze verify` не дал успешного результата: на рабочей
  станции нет release пути `/opt/sports-forecast/...` и присутствуют
  посторонние host unit warnings. Проверка установленного unit входит в
  production gate.

## Остаточный gate

На production установить unit только с релизом, выполнить `daemon-reload`,
сбросить старое состояние `start-limit-hit` и наблюдать 20 последовательных
минутных срабатываний с продвижением heartbeat. До этого TASK не подтверждает
исправление фактического расписания на VPS.
