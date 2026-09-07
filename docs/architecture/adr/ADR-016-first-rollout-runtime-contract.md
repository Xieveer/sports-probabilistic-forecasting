# ADR-016 — Изолированные identities и воспроизводимый first-rollout gate

> **Статус:** accepted
> **Дата:** 2026-09-05
> **Связанное требование:** [REQ-017](../../product/requirements/REQ-017-production-first-rollout-contract.md)

## Контекст и критерии выбора

Runtime image нельзя запускать через `uv run`: editable sync требует записи в
`/app`. Чистая DB создаёт только bootstrap owner, но API URL использует ещё не
существующий reader. Решение должно исключать secret values из Compose render,
работать без root и быть проверяемым до release handoff.

## Рассмотренные варианты

1. **Status quo: `uv run` и один `sf_user`.** Не проходит read-only runtime и
   создаёт циклическую зависимость reader role перед Alembic.
2. **Один owner URL для всех процессов.** Упрощает bootstrap, но нарушает least
   privilege и делает API/Worker обладателями DDL credential.
3. **Выделенный `sf_migrator`, file-backed secrets и bootstrap/grant CLI
   (выбран).** PostgreSQL init создаёт identities до migration; миграционный
   service применяет DDL и затем idempotent grants. API и Worker читают только
   собственные secret files через tiny runtime entrypoint.

## Решение

Все application commands запускаются console scripts или
`/app/.venv/bin/python`. Compose передаёт secret files в `/run/secrets`; shared
entrypoint читает только разрешённый `*_FILE` в environment процесса и не
печатает значение. `sf_migrator` владеет schema и выполняет Alembic; bootstrap
создаёт `sf_api_reader` и `sf_refresh_writer`; после migration отдельная
idempotent command выдаёт grants. E2E runner запускает only digest-pinned images
в isolated Docker project и сохраняет redacted JSON evidence.

## Последствия

- Положительные: устраняется write в `/app`, identities можно проверить по DB
  catalog, CI воспроизводит initial rollout.
- Отрицательные: Operations управляет пятью secret files и запускает migration
  profile до API/Worker.
- Безопасность и эксплуатация: passwords не живут в Git, image layers, Compose
  render или logs; all runtime root filesystems read-only, writable paths явно
  tmpfs/bind mounts.

## Проверка и пересмотр

Runner проверяет default CMD, DB catalog/grants, bind mounts, readiness,
rollback и evidence schema. Пересмотр необходим, если Postgres переносится в
managed service с отдельным IAM/identity mechanism.

## Источники и неизвестное

- [REQ-017](../../product/requirements/REQ-017-production-first-rollout-contract.md).
- Реальные VPS IAM, backup RPO/RTO и required-check branch/tag policy
  подтверждаются Operations/GitHub administrators до rollout.
