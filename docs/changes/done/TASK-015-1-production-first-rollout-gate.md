# TASK-015-1 — отчёт production first-rollout gate

> **Статус задачи:** reviewed; awaiting tag CI evidence
> **Дата:** 2026-09-06
> **Задача:** [TASK-015-1](../../backlog/tasks/TASK-015-1-runtime-bootstrap-and-rollout-gate.md)

## Результат

Runtime images используют installed environment без `uv run`; DB bootstrap создаёт
least-privilege roles до Alembic. Historical local JSON удалён: он не соответствовал
актуальной fail-closed schema. Официальный redacted evidence создаёт только tag CI.

## Подтверждённые этапы

- digest-only images, UID/GID `10001:10001` и read-only runtime;
- clean PostgreSQL bootstrap, Alembic `0009_prediction_refresh_provenance`;
- model/bootstrap/source-state, bounded Worker и idempotent run ID;
- MinIO archive-sync, API readiness, Telegram stub/heartbeat;
- no-secret logs и isolated logical restore pre-migration backup.

## Проверки

- Full PTY runner: exit code 0.
- Targeted pytest/Ruff и `git diff --check` — successful в ходе задачи.

## Review remediation

P1 remediation завершён: API/Worker grants стали whitelist-only с deny для
`alembic_version`; DB restore сверяет pre-migration schema/content sentinel;
model pointer проходит `current → previous → current`. Runner требует Docker
`healthy` для bot, сканирует stdout+stderr long-lived и one-shot containers,
сохраняет Worker peak RSS и disk evidence. CI строит OCI artifact один раз,
тестирует и публикует тот же digest; Actions закреплены SHA. Добавлен
воспроизводимый `make type-check`.

Последующее финальное independent review выявило P1: clean tree проверяется
после OCI artifacts, grants не покрывают реальные runtime queries, historical
JSON не соответствует новой evidence schema, handoff описывает secret values
вместо `*_FILE`. Remediation добавляет clean-tree gate до OCI download,
позитивные runtime DB probes, точные sequence grants и complete systemd Compose
profile. Full clean runner прошёл в изолированном clean Git clone за 128.914 с;
tag CI должен повторить его с реальным commit и OCI digests. TASK остаётся
`in_progress`; отчёт не является production approval до повторного review и CI.

## Проверки remediation

- `uv run pytest tests/test_production_first_rollout_contract.py tests/test_release_version_contract.py tests/test_production_topology.py -q` — 37 passed.
- `uv run mypy --follow-imports=skip --ignore-missing-imports scripts/run_production_first_rollout.py` — successful.
- `make type-check`, `make lint`, `make production-check`, `git diff --check` — successful.
- `make test-unit` — 974 passed, 8 deselected.

## Independent review evidence

Повторное independent review 2026-09-07 не выявило blocking findings.
Проверенный implementation diff зафиксирован в commit
`2772b93a198573f354643b242ae9a60493020f97`.

Независимо выполнены mypy, 48 targeted tests, `make production-check`,
`make lint`, `make docs` и `git diff --check`; все gates завершились
успешно. Sphinx сохранил одно существующее warning об `_static`.

## Остаточный внешний шаг

GitHub required check для release tags должен быть назначен владельцем репозитория;
это не изменяется локальным кодом.

## Необходимая следующая remediation

Канонический список P1 и критерии повторного review:
[TASK-015-1](../../backlog/tasks/TASK-015-1-runtime-bootstrap-and-rollout-gate.md).
