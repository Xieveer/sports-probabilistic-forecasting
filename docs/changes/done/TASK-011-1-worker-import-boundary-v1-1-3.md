# TASK-011-1 — отчёт реализации

> **Статус задачи:** done
> **Дата:** 2026-08-20
> **Задача:** [TASK-011-1](../../backlog/tasks/TASK-011-1-worker-import-boundary-v1-1-3.md)

## Реализованный результат

`sports_forecast.deploy` перестал eager-import'ить MLflow-зависимый
`ModelPromoter`. Worker теперь импортирует verifier bundle без MLflow;
`ModelPromoter` остаётся доступен local control plane через lazy public API.
Docker release workflow до push собирает target `worker` и проверяет точную
команду import. Версия package/API/release contract — `1.1.3`.

v1.1.2 не изменён: его tag и published digests сохранены только как historical
evidence заблокированного релиза. Handoff требует отдельные v1.1.3 digest и
provenance, после чего Operations пересобирает тот же bundle из тех же трёх
файлов с `app_version=1.1.3`.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/deploy/__init__.py` | Lazy boundary между Worker и MLflow control plane. |
| `.github/workflows/docker.yml` | Worker import release-gate до push. |
| `tests/test_model_bundle.py`, `tests/test_deploy_promoter.py`, `tests/test_release_version_contract.py` | Regression, API compatibility и workflow contracts. |
| `pyproject.toml`, `uv.lock` | Версия v1.1.3 через `uv lock`. |
| `docs/operations/production-handoff.md`, `docs/deploy/devops_message.md` | Immutable v1.1.3 handoff и запрет изменения v1.1.2. |
| `REQ-011`, `ADR-011`, `EPIC-011`, `TASK-011-1` | Канонические требования, решение и план patch-релиза. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_model_bundle.py::test_model_bundle_import_does_not_require_mlflow tests/test_release_version_contract.py::test_release_gate_imports_model_bundle_inside_worker_image -q` — 2 failed: первый тест получил `ModuleNotFoundError: No module named 'mlflow'` из eager `deploy.__init__`, второй не нашёл release-gate.
- **Green:** та же команда после реализации — 7 passed (включая весь `test_release_version_contract.py`).
- **Refactor:** API сохранён через минимальный module `__getattr__`; дополнительные abstraction не вводились.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest -q` | 914 passed, 35 warnings. |
| `make lint` | Успешно. |
| `uv run pre-commit run mypy --all-files` | Успешно. |
| `make security` | Успешно: `No known vulnerabilities found`. |
| `make docs` | Успешно; один существующий warning Sphinx о отсутствующем `_static`. |
| `make ai-validate` | Успешно. |
| `make production-check` | Успешно. |
| `docker build --target worker --tag sports-forecast-worker-import-gate .` | Локально не выполнен из-за DNS Docker Hub; GitHub tag pipeline успешно выполнил тот же gate внутри Worker image. |
| GitHub Actions run `32395043783` | Успешно: release gates, четыре build/push, image scans и provenance v1.1.3. |
| Review diff | P2 о stale `1.1.0` в Operations исправлен до merge; blocking findings нет. |

## Документация, review и follow-up

- Документация: [REQ-011](../../product/requirements/REQ-011-worker-import-boundary-v1-1-3.md), [ADR-011](../../architecture/adr/ADR-011-lazy-deploy-control-plane-import.md), [handoff](../../operations/production-handoff.md), [сообщение Operations](../../deploy/devops_message.md).
- Review / security: P2 в [devops_message.md](../../deploy/devops_message.md) исправлен до merge; PR [#26](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/26) прошёл CI/security checks.
- Commit/push: `47974f6` слит в `main` как `3f67aa8c8e28bc4311b2c1146662b12f9a9e8055`; annotated tag `v1.1.3` опубликован на этом exact commit.
- Follow-up: Operations получает digests/provenance из [production handoff](../../operations/production-handoff.md) и пересобирает bundle из тех же трёх файлов с `app_version=1.1.3`; rollout требует отдельного разрешения владельца.

## Остаточные риски

- Локальная Docker-проверка не состоялась из-за DNS Docker Hub, но mandatory tag CI успешно выполнил container gate до publication.
- v1.1.3 images/digests/provenance опубликованы; Operations ещё должен пересобрать и опубликовать compatible bundle. Rollout не выполнялся и требует отдельного разрешения владельца.
