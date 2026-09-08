# TASK-016-1 — Evidence gate и static application contract

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-016](../EPIC-016-immutable-release-evidence.md)
> **Требование:** [REQ-018](../../product/requirements/REQ-018-immutable-release-evidence-v1-1-14.md)
> **ADR:** [ADR-017](../../architecture/adr/ADR-017-two-phase-release-evidence.md)

## Результат и границы

Реализовать validator и инструкцию двухфазного evidence bundle; не создавать tag, не публиковать
images и не выполнять deployment.

## Критерии приёмки

- [x] Validator fail-closed проверяет identity, images, secrets boundary и rendered Compose.
- [x] Evidence workflow запускает тот же validator до evidence tag.
- [x] Static handoff и release procedure синхронизированы с v1.1.14.

## План реализации

1. Добавить reproducing tests для manifest и Compose boundary.
2. Реализовать минимальный validator и workflow.
3. Обновить version, handoff и canonical docs; выполнить targeted checks.

## Затрагиваемые области и зависимости

- `scripts/verify_release_evidence.py`, `.github/workflows/release-evidence.yml`, release docs.
- Нужны внешние successful runs и GitHub tag protection перед evidence publication.
- `make type-check` выполняет pinned pre-commit mypy 1.11.2 с repository stubs и проходит.

## Проверка

- `uv run pytest tests/test_release_evidence.py -q`
- `docker compose ... config` и `scripts/verify_release_evidence.py` на evidence commit.

## Handoff и отчёт

- Отчёт выполнения: [TASK-016-1-release-evidence-gate.md](../../changes/done/TASK-016-1-release-evidence-gate.md).
- Follow-up / findings: external pipeline evidence и tag protection.
- Review: ожидает independent reviewer.
- Commit/push: ожидает reviewer.
