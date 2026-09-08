# TASK-016-1 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-09-08
> **Задача:** [TASK-016-1](../../backlog/tasks/TASK-016-1-release-evidence-gate.md)

## Реализованный результат

Добавлен двухфазный release contract `v1.1.14`: application source не содержит
self-referential/dynamic evidence, а отдельный evidence commit до своего immutable tag
проверяется по source binding, manifest, candidate handoff и rendered private Compose.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `scripts/verify_release_evidence.py` | Fail-closed evidence validator. |
| `.github/workflows/release-evidence.yml` | Manual evidence gate. |
| `docs/operations/production-handoff.md` | Static application contract и порядок evidence handoff. |
| `pyproject.toml`, `uv.lock` | Application version `1.1.14`. |
| `tests/test_release_evidence.py` | Contract tests validator-а. |
| `REQ-018`, `ADR-017`, `EPIC-016`, `TASK-016-1` | Канонические артефакты решения и реализации. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_release_evidence.py -q` — import error
  `scripts.verify_release_evidence` до реализации validator-а.
- **Green:** `uv run pytest tests/test_release_evidence.py -q` — 4 passed.
- **Refactor:** validation собрана в standalone script, используемый локально и GitHub workflow.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_release_evidence.py tests/test_release_version_contract.py tests/test_production_readiness_validation.py -q` | 17 passed. |
| `make production-check` | passed. |
| `make lint` | passed. |
| `make type-check` | passed (pinned pre-commit mypy 1.11.2). |
| `make docs` | build succeeded; существующие warnings. |
| `make ai-validate` | passed. |
| `git diff --check` | passed. |

## Документация, review и follow-up

- Документация: [handoff](../../operations/production-handoff.md),
  [REQ-018](../../product/requirements/REQ-018-immutable-release-evidence-v1-1-14.md),
  [ADR-017](../../architecture/adr/ADR-017-two-phase-release-evidence.md).
- Review / security: не выполнялось независимо.
- Commit/push: ожидает reviewer; tags не создавались.
- Follow-up: successful application tag pipeline, protected tag policy, evidence commit/tag и
  independent review EPIC-016.

## Остаточные риски

- Не подтверждены external CI/Security/Docker/first-rollout runs, publication, image scans,
  provenance, Linux/amd64 platform и tag protection.
- Production deployment, migrations, scheduler, bootstrap import и Telegram delivery не выполнялись.
