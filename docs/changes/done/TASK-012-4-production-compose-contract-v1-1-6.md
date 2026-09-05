# TASK-012-4 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-09-05
> **Задача:** [TASK-012-4](../../backlog/tasks/TASK-012-4-production-compose-contract-v1-1-6.md)

## Реализованный результат

Worker v1.1.6 читает host-owned model runtime через bind mount
`${SF_MODEL_RUNTIME_ROOT}:/app/models:ro`. До Docker publish workflow рендерит
Compose безопасным fixture и проверяет final Worker с model/source/bootstrap
artifacts. Pointer модели стал относительным, поэтому остаётся доступным после
mount host root в `/app/models`.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `docker-compose.prod.yml`, `.env.example` | Host model bind mount и runtime variable. |
| `.github/workflows/docker.yml`, `scripts/` | Rendered Compose и final-image gates. |
| `sports_forecast/deploy/model_bundle.py` | Mount-safe relative `current`/`previous` pointers. |
| `docs/` | REQ-016, ADR-015, runbooks, handoff и risk review. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_production_topology.py -q` — 2 expected failures: named `runtime_models` вместо bind mount и лишний volume.
- **Green:** `uv run pytest tests/test_model_bundle.py tests/test_production_topology.py tests/test_release_version_contract.py tests/test_production_readiness_validation.py -q` — 32 passed.
- **Refactor:** нормализованный rendered Compose mount и memory parser отделены в маленькие helpers.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| Rendered Compose fixture: `config --quiet`, `config`, validator | Успешно, включая profiles Worker/source-acquisition/archive-sync. |
| Final Worker Docker smoke (`--read-only --network none --user 10001:10001`) | Успешно: UID/GID, model `current`, checksum/compatibility, source/bootstrap validators, imports и запрет записи. |
| `make lint` | Успешно. |
| `make test-unit` | 964 passed, 8 deselected. |
| `uv run pre-commit run mypy --all-files` | Успешно. |
| `make pre-commit` | Успешно после автоматического форматирования одного нового файла. |
| `make docs` | Успешно с 155 существующими предупреждениями Sphinx вне scope. |
| `make production-check` | Успешно. |
| `make security` | Успешно: `pip-audit` завершился, временный requirements-файл удалён Makefile. CI filesystem/image scans ещё не запускались. |

## Документация, review и follow-up

- Документация: [REQ-016](../../product/requirements/REQ-016-production-compose-contract-v1-1-6.md), [ADR-015](../../architecture/adr/ADR-015-production-compose-model-bind-mount.md), [handoff](../../operations/production-handoff.md).
- Review / security: выполнен scoped self-review границ mount/fixture/secrets; независимые reviewer и security review не выполнялись.
- Commit/push: не выполнялись.
- Follow-up: DevOps server-side validation, tag `v1.1.6`, publish/scan/provenance и owner approval остаются до release.

## Остаточные риски

- Реальные host ownership/permissions, IAM separation, backup evidence, observability и 8 GiB consumption подтверждаются только на VPS.
- DB, миграции, bootstrap, scheduler и application runtime намеренно не запускались.
