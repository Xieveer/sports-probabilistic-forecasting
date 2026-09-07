# REQ-017 — Контракт первого production rollout

> **Статус:** confirmed
> **Владелец продукта:** пользователь
> **Создано:** 2026-09-05
> **Продолжает:** [REQ-016](REQ-016-production-compose-contract-v1-1-6.md)

## Результат и ценность

Перед передачей patch release в Operations команда получает воспроизводимое
доказательство полного server-side пути: от пустой PostgreSQL и подготовленных
host mounts до healthy API и bot, с проверяемым откатом. Зелёный unit CI без
этого доказательства не является готовностью к выпуску.

## Scope

- Runtime CMD и operational Compose commands используют установленный
  `/app/.venv`, а не `uv run`, и запускаются как `sf` (`10001:10001`) с
  read-only root filesystem.
- Initial PostgreSQL bootstrap создаёт idempotent migration, API-reader и
  Worker-writer roles с минимальными grants и отдельными file-backed secrets.
- Локальный clean-project runner проверяет immutable images, mounts, миграции,
  bundles, bounded Worker run, archive-sync, readiness, heartbeat и rollback.
- Tag-only GitHub Actions запускает runner до publication/handoff и сохраняет
  machine-readable evidence без секретов.

## Non-scope

- Выполнение rollout, выдача production IAM/credentials, изменение VPS,
  публикация образов или создание release tag.
- Destructive Alembic downgrade: additive schema откатывается forward-fix или
  проверенным logical backup в isolated database.

## Проверяемые критерии приёмки

- [ ] Ни один runtime CMD/Compose entrypoint не содержит `uv run`; default
  runtime processes проходят как `10001:10001` при `--read-only`.
- [ ] Compose получает DB credentials из secret files; rendered configuration
  не содержит secret values, API/Worker/bot не получают Object Storage secrets.
- [ ] Чистая PostgreSQL создаёт роли idempotent; Alembic использует migrator,
  API — reader, Worker — writer; grants проверяются после migration.
- [ ] `scripts/run_production_first_rollout.py` создаёт isolated runtime root,
  выполняет сценарий и публикует JSON evidence с указанными в ТЗ identities,
  digest, health, resource и rollback полями.
- [ ] Required tag workflow блокирует image publication и production handoff,
  если runner не завершился успешно.

## Риски и предположения

- Для локального test Object Storage используется отдельный ephemeral endpoint;
  реальные IAM policies остаются обязанностью Operations.
- Telegram acceptance использует test token/локальный controlled endpoint и не
  отправляет сообщения реальным пользователям.
- Выбран отдельный `sf_migrator`; это уменьшает использование owner credential
  в runtime, но требует явной secret file до старта migration service.

## Подтверждение

Полное ТЗ пользователя от 2026-09-05 является подтверждением scope и
критериев. Выбор имени выделенной migration role — минимальное техническое
решение в [ADR-016](../architecture/adr/ADR-016-first-rollout-runtime-contract.md).
