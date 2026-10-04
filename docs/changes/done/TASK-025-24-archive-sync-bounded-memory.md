# TASK-025-24 — Ограничение памяти archive-sync

> **Статус:** done; независимое review без P0–P2 findings.

## Причина и исправление

Большой NHL source-state archive (~181 MiB) полностью загрузился в локальный
S3 fixture, но исходный archive-sync завершился `exit=137`, `OOMKilled=true`
при лимите 512 MiB во время remote verification. Сравнение через два
`Path.read_bytes()` создавало две полные копии файла в памяти. Сравнение
заменено на побайтовую проверку блоками по 1 MiB с прежним отказом при
неравенстве файлов.

## Доказательства

- Red: `test_sync_large_archive_does_not_read_whole_file` упал на
  `AssertionError: Большой файл прочитан целиком` под лимитом 1 GiB.
- Green: `tests/test_operational_archive_sync.py` — 9 passed под лимитом
  1 GiB и таймаутом 30 секунд, включая same-size corruption; Ruff check/format
  и `git diff --check` прошли.
- Локальный Worker создал оба архива на восстановленной истории. Повторные
  source-state и canonical sync через production CLI в Worker v1.2.8 image с
  точечной подменой исправленного модуля завершились `exit=0`,
  `OOMKilled=false` при лимите 512 MiB. Локальный S3 fixture не имел внешней
  сети; оба durable state — `verified`.
- Независимый Reviewer проверил реализацию и регрессионные тесты без P0–P2
  findings; сверил evidence `9 passed` в TASK, отчёте и EPIC.

## Граница

Production и внешнее Object Storage не затрагивались. Полный Data Cycle,
тестовый Telegram-путь и CI остаются открытыми gates
[TASK-025-22](../../backlog/tasks/TASK-025-22-local-quality-parity.md).
