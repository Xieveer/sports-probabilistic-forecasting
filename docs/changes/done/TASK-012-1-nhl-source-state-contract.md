# TASK-012-1 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-20
> **Задача:** [TASK-012-1](../../backlog/tasks/TASK-012-1-nhl-source-state-contract.md)

## Результат

Добавлен source-state contract под `operational-archive/nhl-source-state/v1`.
Bundle содержит `source.csv`, Pinnacle OddsStore, odds checkpoint и verified
manifest с checksum, schema versions, counts и provenance. Добавлены CLI build и
verify/install с idempotence, rollback при interrupted replacement и derivation
`current.csv` только после проверки.

Успешный canonical refresh экспортирует source-state после commit. Scheduler
remote-sync-ит canonical и source-state artifacts отдельным process; failure
оставляет staging и предыдущий valid state. Local latest pull перечисляет
manifest-ы, пропускает corrupt newest, проверяет checksum и создаёт descriptor
с доступным OddsStore без автоматического DVC/training.

## Проверки

- `uv run pytest tests/test_source_state.py tests/test_source_state_cli.py tests/test_operational_archive_sync.py tests/test_serving_data_archive.py tests/test_canonical_snapshot.py tests/test_canonical_full_refresh.py tests/test_source_snapshot.py tests/test_production_topology.py tests/test_release_version_contract.py -q` — 52 passed.
- `.venv/bin/pytest -m unit -q` — 917 passed, 8 deselected, 35 warnings
  (запуск с временно убранным stale editable `egg-info`, восстановленным после теста).
- `uv run ruff check ...` по изменённым production/test файлам — успешно.
- `uv run pre-commit run mypy --files ...` — успешно.
- `make lint` — успешно.
- `make docs` — успешно, 1 существующее предупреждение `_static`.
- `.venv/bin/python scripts/validate_production_readiness.py` — `Production handoff is valid`.
- `.venv/bin/python scripts/validate_ai_layer.py` — `AI layer is valid`.
- `docker compose ... config --quiet` с фиктивными non-secret inputs — успешно.
- `bash -n deploy/systemd/run-canonical-refresh.sh` и `git diff --check` — успешно.
- Регрессионные проверки review: 14 тестов source-state/archive-sync — успешно.
- Исправлены review findings: artifact ID валидируется до записи в local staging,
  S3 listing поддерживает continuation tokens, версия OddsStore в manifest
  вычисляется по фактическим колонкам Parquet.

## Документация, review и follow-up

Обновлены REQ-012, ADR-012 (`accepted`), EPIC/TASK, canonical bootstrap/full
refresh, topology, handoff, `.env.example`, Compose/systemd и tag workflow.
Реальные Object Storage IAM/lifecycle checks, production scheduler run,
initial artifact size и image digests остаются внешним Operations evidence.
Независимый review выполнен после исправлений; выпускной tag, image digests и
внешнее Object Storage evidence остаются отдельным release/Operations шагом.
