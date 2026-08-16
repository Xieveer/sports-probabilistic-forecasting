# TASK-007-5 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-15
> **Задача:** [TASK-007-5](../../backlog/tasks/TASK-007-5-production-runtime-topology.md)

## Реализованный результат

Production Compose получает immutable digest для каждого image. API использует
отдельный read-only DB URL, bot не получает DB/models/data, а canonical refresh
Worker получает отдельный write URL, immutable model/source inputs и только
локальный archive staging для записи. Worker не получает DVC, MLflow или Object
Storage credentials.

Добавлены template systemd service/timer/profile: per-profile cadence и timeout
задаются host drop-ins, run ID содержит UTC timestamp и UUID, `flock -n` и DB
lock запрещают overlap, timeout/retry заданы systemd, durable last-success —
`worker_executions`. Rollout, secrets, IAM и запуск timer не выполнялись.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `docker-compose.prod.yml` | Scoped mounts/DB URLs и immutable images runtime. |
| `Dockerfile` | API healthcheck использует DB-aware `/ready`. |
| `deploy/systemd/` | Scheduler templates и root-only profile/drop-in examples. |
| `.env.example` | Обязательные digest, scoped DB и staging inputs. |
| `tests/test_production_topology.py` | Static contracts topology, scheduler, health и public metrics. |
| `docs/operations/production-runtime-topology.md` | Runtime boundary и безопасный handoff Operations Agent. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_production_topology.py -q` — 3 failed:
  общий API DB URL и отсутствующие systemd templates.
- **Red:** `uv run pytest tests/test_production_topology.py::test_production_runtime_images_are_external_and_immutable_inputs -q` — failed: `postgres:16-alpine` не digest input.
- **Green:** `uv run pytest tests/test_production_topology.py -q` — 10 passed.
- **Refactor:** template timer защищён от случайного запуска до profile drop-in;
  timeout перенесён с неработающего для `oneshot` `RuntimeMaxSec` на
  `TimeoutStartSec`.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_production_topology.py -q` | 10 passed |
| `BOT_TOKEN=… SF_WORKER_RUN_ID=… docker compose -f docker-compose.prod.yml --env-file deploy/systemd/refresh-profile.env.example config` | успешно |
| `bash -n deploy/systemd/run-canonical-refresh.sh` | успешно |
| `systemd-analyze verify deploy/systemd/*.service deploy/systemd/*.timer` | успешно; только warnings хоста о его посторонних unit files |
| `uv run pre-commit run ruff-format --files tests/test_production_topology.py` | успешно |
| `uv run pre-commit run mypy --files tests/test_production_topology.py` | успешно |
| `uv run pre-commit run mypy --all-files` | неуспешно: существующая ошибка `repository.py:204`, вне этого среза |
| `make docs` | успешно; Sphinx warning о отсутствующем `docs/source/_static` |
| `git diff --check` | успешно |

## Документация, review и follow-up

- Документация: [runtime topology](../../operations/production-runtime-topology.md),
  [canonical full refresh](../../operations/canonical-full-refresh.md),
  [production handoff](../../operations/production-handoff.md).
- Review / security: локальный DevOps/security review выполнен по
  `agents/devops-reviewer.md`, `agents/security-reviewer.md` и
  `skills/security-review`: достижимых новых уязвимостей не найдено. Границы
  Docker, secret templates, root-only profile, trusted systemd instance и
  публичный ingress metrics проверены статически.
- Follow-up: [TASK-007-6](../../backlog/tasks/TASK-007-6-measurement-devops-handoff-and-release.md)
  измеряет full refresh и собирает внешний Operations evidence.

## Остаточные риски

- Реальные PostgreSQL grants, Object Storage IAM, systemd enable и VPS rollout
  намеренно не выполнялись и требуют Operations Agent плюс отдельное разрешение.
- Полный mypy hook остаётся красным из-за ранее существующей типизации
  `PredictionRepository.set_publication_state`; это не изменялось в TASK-007-5.
