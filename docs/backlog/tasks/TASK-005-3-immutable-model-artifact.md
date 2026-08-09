# TASK-005-3 — Immutable production model artifact

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-005](../EPIC-005-production-serving-readiness.md)
> **Требование:** [REQ-005](../../product/requirements/REQ-005-production-serving-release.md)
> **ADR:** [ADR-003](../../architecture/adr/ADR-003-configured-multisport-portfolio.md), [ADR-005](../../architecture/adr/ADR-005-production-serving-boundary.md)

## Результат и границы

На основе выполненных TASK-003-1…3 добавить production bundle/manifest:
immutable ID, checksum файлов, app/model compatibility, source commit/release,
install/verify и current/previous pointer. Не обучать модель и не удалять legacy NHL artifacts.

## Критерии приёмки

- [x] Изменение production pointer возможно только явной promotion-командой;
  manifest валидируется до активации.
- [x] Worker/API fail fast на checksum или compatibility mismatch, не пишут
  predictions и не изменяют active pointer.
- [x] Rollback переключает на сохранённый previous bundle без переобучения.

## План реализации

1. После закрытия TASK-003-1…3 добавить failing manifest/install/rollback tests.
2. Реализовать minimal bundle registry и read-only loader, сохранить legacy
   NHL compatibility.
3. Документировать handoff package и проверить promotion/rollback на fixture.

## Проверка

- Manifest/promotion contract tests, `make test-unit`.

## Handoff и отчёт

- Блокер: TASK-003-1, TASK-003-2, TASK-003-3.
- Отчёт выполнения: `docs/changes/done/TASK-005-3-immutable-model-artifact.md`.
