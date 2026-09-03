# TASK-012-3 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-09-03
> **Задача:** [TASK-012-3](../../backlog/tasks/TASK-012-3-worker-runtime-dependency-v1-1-5.md)

## Результат

Patch `1.1.5` делает `omegaconf` явной production-зависимостью и добавляет
`/app/.venv/bin` в `PATH`, поэтому bare `python` финального Worker image видит
runtime packages. `hydra-core` обновлён с уязвимой `1.3.2` до `1.3.6` после
результата dependency audit. Добавлен read-only/no-network final-image gate с
UID `10001`, module imports, отсутствием local control-plane пакетов и
content-addressed source-state/canonical-bootstrap fixtures.

В ходе local image gate обнаружены недоступные UID `10001` permissions fixture,
созданных через `mktemp`; fixture builder теперь безопасно делает только
нечувствительные тестовые bundles доступными для read-only mount.

## Проверки

- `uv run pytest tests/test_release_version_contract.py tests/test_canonical_bootstrap.py tests/test_source_state.py tests/test_production_topology.py -q` — 33 passed.
- `make pre-commit` — успешно, включая Ruff, mypy и validation AI layer.
- `make ai-validate` — успешно.
- `make production-check` — успешно.
- `make docs` — успешно; 155 существующих предупреждений Sphinx.
- `docker build --target worker --tag sports-forecast-worker-v115-local .` — успешно.
- Restricted Worker fixture gate (`--read-only --network none --user 10001:10001`, bind mounts, bare `python`) — успешно; UID `10001` подтверждён.
- `uv export --locked --no-dev --no-emit-project --output-file requirements-audit.txt` и `uvx --from pip-audit pip-audit --requirement requirements-audit.txt` — `No known vulnerabilities found`.

## Границы, документация и остаточный риск

Обновлены REQ-015, TASK-012-3, production handoff, versioned operational
examples и release workflow. Immutable staged initial source-state/canonical
bootstrap artifacts не изменялись. Не выполнялись tag/push, CI publication,
GHCR scan/provenance, VPS validation, PostgreSQL, migration, bundle install или
scheduler. До release остаются независимый review, commit/evidence commit,
release tag и CI evidence четырёх immutable digests.
