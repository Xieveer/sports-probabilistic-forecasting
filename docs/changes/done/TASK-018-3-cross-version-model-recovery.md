# TASK-018-3 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-09-08
> **Задача:** [TASK-018-3](../../backlog/tasks/TASK-018-3-cross-version-model-recovery.md)

## Реализованный результат

Installer проверяет новый bundle against target version, но проверяет старый `current`
только на integrity before saving `previous`. Это разблокирует cross-version activation
и сохраняет recovery artifact; worker/API по-прежнему загружают current only when its
manifest matches their version.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/deploy/model_bundle.py` | Integrity verification старого pointer. |
| `tests/test_model_bundle.py` | Cross-version recovery regression. |
| `docs/architecture/adr/ADR-018-cross-version-model-bundle-recovery.md` | Контракт recovery artifact. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_model_bundle.py -q` — 1 failed: install new version
  проверял old current against target compatibility.
- **Green:** `uv run pytest tests/test_model_bundle.py tests/test_worker.py tests/test_canonical_full_refresh.py -q` — 15 passed.
- **Refactor:** выделен private integrity verifier, чтобы не ослаблять public runtime verifier.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run ruff check sports_forecast/deploy/model_bundle.py tests/test_model_bundle.py` | passed |
| `uv run pre-commit run mypy --files sports_forecast/deploy/model_bundle.py tests/test_model_bundle.py` | passed |

## Документация, review и follow-up

- Документация: REQ-020, ADR-018 и EPIC-018.
- Review / security: ожидается для общего diff.
- Commit/push: ожидает reviewer; не выполнялся.
- Follow-up: нет.

## Остаточные риски

- Pointer rollback после cross-version activation требует rollback application release до
  compatible manifest version; это зафиксировано в ADR-018.
