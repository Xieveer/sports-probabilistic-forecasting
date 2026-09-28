# TASK-025-25 — Разместить remote verification вне малого tmpfs

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Блокирует:** [TASK-025-22](TASK-025-22-local-quality-parity.md)

## Наблюдаемый дефект

Production Compose ограничивает `/tmp` archive-sync 64 MiB, а remote
verification скачивает в `TemporaryDirectory()` полный source-state объект
около 181 MiB. Первый локальный sync с увеличенным tmpfs прошёл, но exact
production конфигурация завершилась `exit=1` с `OSError`, без OOM.

## Критерии исправления

- [x] Red-тест доказывает, что remote copy должен создаваться под durable
  sync-state root, а не в стандартном `/tmp`.
- [x] Временный каталог remote verification расположен в writable sync-state
  volume; прежние verified/failed и проверка файлов сохранены.
- [x] Оба архива проходят actual Compose `archive-sync` command при
  `mem_limit=512m` и `/tmp=64m` с локальным S3 fixture.
- [x] Независимое review и финальные релевантные проверки завершены.

До исправления адресный тест упал: destination находился под `/tmp`.
После исправления 10 тестов `test_operational_archive_sync.py` прошли под
лимитом 1 GiB. Compose с локальным override только для образа, сети и
bind-mount исправленного файла выполнил source-state и canonical sync;
оба вызова `exit=0`, state содержит два `verified`. Данные production не
затронуты.
`UV_NO_SYNC=1 make lint`, `UV_NO_SYNC=1 make type-check`, Ruff format check
и `git diff --check` прошли. `UV_NO_SYNC=1` использован потому, что после
обновления версии проекта локальный `uv run` пытался обратиться к недоступному
PyPI за build dependency; установленные инструменты и lock не менялись.
Независимый Reviewer не нашёл P0–P2 findings.

Результат — в [отчёте](../../changes/done/TASK-025-25-archive-sync-tmpfs.md).
