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
- [x] Locked runtime resolution содержит `pyarrow>=23.0.1`, а `make security`
  завершается без известных уязвимостей до создания release candidate.

## Security remediation v1.1.7

После перепривязки `v1.1.6` запуск
[34093047138](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/34093047138)
остановился на dependency audit до создания OCI artifacts и публикации образов:
`pip-audit` обнаружил `PYSEC-2026-113` в `pyarrow 22.0.0`. Ранний binding
`7f8b86f` уже запускал успешный pipeline `33961438667` и публиковал образы;
все его артефакты, как и новый binding, quarantined и не используются для
rollout. Владелец подтвердил обновление полного совместимого dependency
resolution для отдельного immutable candidate `v1.1.7`. Минимальная допустимая
версия PyArrow — `23.0.1`; lock фиксирует разрешённую версию и проходит security gate.

Tag CI `v1.1.7` прошёл lint, unit tests, dependency audit, documentation и
filesystem/secret scan, но остановился на rendered Compose contract: workflow
активировал runtime profiles, не активировав `migration`, хотя verifier требует
полный сервисный contract. OCI artifacts, first-rollout и publication не
запускались. Исправленный отдельный candidate — `v1.1.8`; `v1.1.7` запрещён
для rollout.

Tag CI `v1.1.8` прошёл rendered Compose contract, но Worker gate остановился
до OCI build: read-only container не получил writable `/tmp` для Matplotlib.
Tag CI `v1.1.9` прошёл все release gates и собрал четыре prebuilt OCI image
artifacts, но fail-closed остановился на first-rollout: OCI layout нельзя
загрузить через `docker load`. Candidate `v1.1.10` использует один Docker
archive для build, first-rollout и exact publication. Tag CI `v1.1.10` успешно
загрузил эти archive, но затем остановился на clean-tree gate: обычный
`git status --porcelain` свернул untracked directory и не позволил строго
сопоставить четыре archive. Candidate `v1.1.11` перечисляет untracked files
поимённо и разрешает только ожидаемые `*.docker.tar`.

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
