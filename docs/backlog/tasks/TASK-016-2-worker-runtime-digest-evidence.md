# TASK-016-2 — Runnable Worker digest для release evidence

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-016](../EPIC-016-immutable-release-evidence.md)
> **Требование:** [REQ-018](../../product/requirements/REQ-018-immutable-release-evidence-v1-1-14.md)
> **ADR:** [ADR-017](../../architecture/adr/ADR-017-two-phase-release-evidence.md)

## Результат и границы

Зафиксировать новый evidence revision `v1.1.14-evidence.2`: заменить только Worker
reference на subject runnable manifest и не менять application tag/source commit,
остальные image references или production topology.

## Критерии приёмки

- [x] `images.worker` содержит exact runnable `linux/amd64` manifest digest.
- [x] Docker workflow получает digest tagged remote runtime manifest, не OCI referrer.
- [x] До evidence tag workflow проверяет platform для каждого application image и Worker
  pull/image-inspect/non-root read-only import smoke по exact reference.
- [x] Candidate handoff фиксирует причину, replacement digest и отсутствие deployment.
- [x] Evidence validator и rendered Compose проходят.

## План и проверки

1. Воспроизвести provenance referrer и определить его subject manifest.
2. Добавить reproducing validator test для последовательной evidence revision.
3. Изменить Docker gate и evidence/documentation bundle.
4. Выполнить targeted tests, Compose/evidence gate и exact registry Worker smoke.

## Handoff

Отчёт: [TASK-016-2-worker-runtime-digest-evidence](../../changes/done/TASK-016-2-worker-runtime-digest-evidence.md).
Evidence commit/tag и external GitHub run остаются отдельным finalization step без
production deployment.
