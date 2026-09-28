# TASK-025-25 — Remote verification вне tmpfs

> **Статус:** done; независимое review без P0–P2 findings.

## Причина и исправление

`sync_operational_archive` создавал `TemporaryDirectory()` в `/tmp`.
Production Compose даёт archive-sync только 64 MiB tmpfs, тогда как один
source-state объект на локальном полном NHL snapshot занимает около 181 MiB.
Контрольный запуск с теми же лимитами завершился `exit=1`, `OOMKilled=false`,
safe error `OSError`. Временный каталог теперь создаётся под
`SF_ARCHIVE_SYNC_STATE_ROOT` — writable bind volume; каталог удаляется после
remote verification штатным context manager.

## Доказательства

- Red: `test_sync_downloads_remote_copy_under_state_root` упал, потому что
  destination находился под `/tmp`.
- Green: `tests/test_operational_archive_sync.py` — 10 passed под лимитом
  1 GiB и таймаутом 30 секунд.
- `UV_NO_SYNC=1 make lint`, `UV_NO_SYNC=1 make type-check`, Ruff format check
  и `git diff --check` прошли. Обычный `make lint` после изменения версии
  не смог скачать build dependency с недоступного PyPI; `uv.lock` обновлён
  через `uv lock --offline`.
- Rendered Compose archive-sync: `mem_limit=512m`, `/tmp=64m`, внешний
  S3 fixture внутри отдельной Docker сети. Production Compose command с
  локальным override образа, сети и исправленного модуля успешно
  remote-verified оба новых архива; durable state — два `verified`.
- Независимый Reviewer проверил код, regression test и resource evidence;
  P0–P2 findings нет, `git diff --check` чистый.

## Граница

Production, внешнее Object Storage и большие исходные данные не менялись.
Exact systemd wrapper и внешний source fetch остаются gates
[TASK-025-22](../../backlog/tasks/TASK-025-22-local-quality-parity.md).
