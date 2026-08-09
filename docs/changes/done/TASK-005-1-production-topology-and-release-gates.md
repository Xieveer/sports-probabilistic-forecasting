# TASK-005-1 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-005-1](../../backlog/tasks/TASK-005-1-production-topology-and-release-gates.md)

## Реализованный результат

Production Compose стал самостоятельным serving-контуром из PostgreSQL, API,
Telegram bot, Caddy и profile-only Worker. Runtime images передаются только как
`image@sha256:digest`; Worker больше не включает полный `data/`/`models/`.
Deploy workflow запускается только вручную. Docker workflow требует lint, unit
tests, dependency/filesystem scans, затем image scan и GitHub provenance
attestation по digest. Caddy не публикует `/metrics`.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `docker-compose.prod.yml` | Самостоятельный минимальный production Compose. |
| `Dockerfile` | Worker без training data/model artifacts в image. |
| `.github/workflows/docker.yml` | Release gates, image scan и provenance. |
| `.github/workflows/deploy.yml` | Только ручной deployment, без auto-CD. |
| `deploy/Caddyfile` | Закрытие публичного `/metrics`. |
| `.env.example`, `docs/operations/production-handoff.md` | Immutable image и актуальная production topology. |
| `tests/test_production_topology.py`, `tests/test_release_version_contract.py` | Контракты topology, ingress и release workflow. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_production_topology.py -q` — 3 expected failures: старый merged Compose содержал `!reset`, а deploy реагировал на `workflow_run`.
- **Red:** `uv run pytest tests/test_release_version_contract.py -q` — отсутствовал job `verify`.
- **Red:** `uv run pytest tests/test_production_topology.py -q` — Caddy не блокировал `/metrics`.
- **Green:** `uv run pytest tests/test_production_topology.py tests/test_release_version_contract.py -q` — 8 passed.
- **Refactor:** production Compose перестал зависеть от development Compose; дублирование training/monitoring config удалено из production profile.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `docker compose -f docker-compose.prod.yml --profile worker config` с synthetic env | Успешно; перечислены только `api`, `caddy`, `db`, `telegram-bot`, `worker`. |
| `make lint` | Успешно. |
| `make test-unit` | Успешно: 790 passed, 8 deselected. |
| `make security` | Успешно: dependency audit завершён без ошибки. |
| `uv run pre-commit run mypy --all-files` | Успешно. |
| `docker build --target worker ...` | Не пройден: дважды TLS timeout Docker daemon при получении Docker Hub token; прямой `curl` к token endpoint вернул 200. |

## Документация, review и follow-up

- Документация: [production handoff](../../operations/production-handoff.md), [REQ-005](../../product/requirements/REQ-005-production-serving-release.md).
- Review / security: рассмотрены ingress, secrets, Docker non-root, CI permissions и provenance; новый provenance action закреплён SHA. Реальные GitHub/GHCR scan/attestation ещё не запускались.
- Follow-up: [TASK-005-2](../../backlog/tasks/TASK-005-2-readiness-and-migrations.md), [TASK-005-7](../../backlog/tasks/TASK-005-7-serving-data-sync-and-archive.md).

## Остаточные риски

- Docker build требует повторной проверки в CI или после восстановления Docker Hub connectivity локального daemon.
- `runtime_models` и `runtime_data` volumes запланированы, но их immutable install/archive protocol реализуют TASK-005-3 и TASK-005-7.
- Production handoff намеренно остаётся `draft` до закрытия всех release blockers.
