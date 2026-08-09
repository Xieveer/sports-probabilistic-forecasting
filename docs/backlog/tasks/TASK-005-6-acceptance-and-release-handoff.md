# TASK-005-6 — Acceptance test и release handoff

> **Статус:** done
> **Владелец:** devops-reviewer
> **Эпик:** [EPIC-005](../EPIC-005-production-serving-readiness.md)
> **Требование:** [REQ-005](../../product/requirements/REQ-005-production-serving-release.md)
> **ADR:** [ADR-005](../../architecture/adr/ADR-005-production-serving-boundary.md)

## Результат и границы

Создать non-mutating acceptance command и заполнить `production-handoff.md`
фактическими контрактами. Сформировать release evidence package, но не создавать
tag, не публиковать images и не выполнять rollout.

## Критерии приёмки

- [x] Acceptance test проверяет liveness/readiness/DB, known test prediction,
  API/model version, bot connectivity, safe logs и обновление Worker success
  без user mutation, message или training.
- [x] Handoff содержит exact production command, migration/recovery, model
  bundle, env names, resource measurement, retention assumptions, signals,
  rollback/stopping criteria и evidence locations.
- [x] `make production-check` расширен до реальных обязательных инвариантов и
  пройден; CI/security/image-scan результаты отмечены только после их запуска.

## План реализации

1. Написать failing acceptance/readiness-validator tests.
2. Реализовать read-only acceptance runner и stricter production-check.
3. Провести prod-like run, внести исключительно фактические evidence в handoff
   и выполнить release review `GO/NO-GO`.

## Проверка

- Acceptance test на disposable/prod-like stack, `make production-check`,
  `make lint`, `make test-unit`; GitHub results добавляются после remote run.

## Handoff и отчёт

- Отчёт выполнения: [TASK-005-6](../../changes/done/TASK-005-6-acceptance-and-release-handoff.md).
- Следующий этап получает [production handoff](../../operations/production-handoff.md).
  Реальные GitHub/GHCR/VPS evidence остаются release blockers, но не блокируют
  завершение локальной implementation-задачи.
