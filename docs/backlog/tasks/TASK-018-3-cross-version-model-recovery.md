# TASK-018-3 — Cross-version model bundle recovery

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-018](../EPIC-018-post-rollout-runtime-corrections.md)
> **Требование:** [REQ-020](../../product/requirements/REQ-020-post-rollout-runtime-corrections.md)
> **ADR:** [ADR-018](../../architecture/adr/ADR-018-cross-version-model-bundle-recovery.md)

## Результат и границы

Installer сохраняет integrity-verified старый `current` как `previous`, even when its
manifest app version differs from target. Candidate/current loading and rollback retain
explicit runtime compatibility validation.

## Критерии приёмки

- [ ] New target bundle проходит target compatibility check.
- [ ] Verified old bundle остаётся `previous` after cross-version install.
- [ ] Повреждённый old current не сохраняется как recovery pointer.

## План реализации

1. Добавить failing cross-version installation test.
2. Выделить integrity verifier и применить его только к сохранению previous.

## Проверка

- `uv run pytest tests/test_model_bundle.py`

## Handoff и отчёт

- Отчёт выполнения: [TASK-018-3](../../changes/done/TASK-018-3-cross-version-model-recovery.md).
- Follow-up / findings: нет.
- Review: ожидает независимого reviewer.
- Commit/push: ожидает reviewer.
