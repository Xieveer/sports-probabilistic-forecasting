# TASK-007-6 — Measurement, DevOps handoff и готовность `1.1.0`

> **Статус:** blocked
> **Владелец:** documentation-writer + devops-reviewer
> **Эпик:** [EPIC-007](../EPIC-007-autonomous-production-data-runtime.md)
> **Требование:** [REQ-007](../../product/requirements/REQ-007-production-data-runtime.md)
> **ADR:** [ADR-007](../../architecture/adr/ADR-007-autonomous-production-data-runtime.md)

## Результат и границы

Получить воспроизводимые measurements на полном NHL history и передать DevOps
Operations Agent исчерпывающий contract: bootstrap, daily refresh, snapshot
sync, model install/rollback, alert/failure, backup/recovery, scheduler и
release acceptance. Подготовить `1.1.0`, но не создавать tag, не публиковать
образы и не выполнять deployment без отдельного разрешения владельца.

## Критерии приёмки

- [ ] Измерены CPU, peak RAM, disk growth и elapsed time полного bootstrap и
  full-history refresh; evidence содержит dataset identity, image/model/config
  provenance, но не secrets/payloads.
- [ ] Обновлены production handoff, bootstrap/sync/rollback runbooks, Compose
  env contract, observability и DevOps-first explanation data flow.
- [ ] security version bump `v1.1.1`, immutable GHCR digest/provenance и final gates
  описаны как последовательность release подготовки; реальный выпуск остаётся
  отдельным authorized action.
- [ ] Выполнены `make production-check` и минимально достаточные tests/review/
  security checks с фактическими результатами в done report.

## План реализации

1. Зафиксировать full-dataset fixture identity и запустить измерения после
   функциональных задач.
2. Написать/обновить DevOps runbook и production handoff по подтверждённому
   runtime, затем проверить команды dry-run/validation.
3. Выполнить final release readiness review и сформировать go/no-go, не делая
   deployment.

## Проверка

Full-data evidence, documentation links validation, `make production-check`,
release/security/devops review reports.

## Фактическое решение release readiness

**CONDITIONAL GO для подготовки release-candidate; NO-GO для rollout.**
Локальные full-history measurements, runbooks и production contract готовы.
2026-08-16 пройдены `make production-check`, профильные production tests и
full mypy. Владелец разрешил подготовку candidate и будущие tag/publication
images, но не deployment.

Остаются условия до фактического release-candidate artifact и rollout:

0. Закрыть [TASK-007-7](TASK-007-7-autonomous-source-and-odds.md),
   [TASK-007-8](TASK-007-8-verified-archive-sync.md) и
   [TASK-007-9](TASK-007-9-private-ingress-and-tag-release.md): feedback
   Operations Agent подтвердил, что прежние contracts не дают autonomous candidate.
1. Повторить успешный path full refresh и атомарной публикации на актуальном
   штатном provider snapshot с допустимыми upcoming матчами. NHL API уже
   возвращает будущие матчи с 2026-09-29, но профиль refresh намеренно
   ограничен текущим 48-часовым quality window; поэтому evidence можно
   получить только ближе к старту сезона без изменения runtime-контракта.
2. Operations Agent должен предоставить immutable GHCR digests/provenance,
   external image scans, production DB/S3 access evidence, backup RPO/RTO и
   scheduler/rollback owner. Подробный запрос передан в
   [devops_message.md](../../deploy/devops_message.md).
3. После выполнения пунктов 1–2 разрешены tag `v1.1.1` и публикация образов
   для итогового `main`; rollout остаётся отдельным authorized action.

Полное measurement evidence находится в
[worker-measurement-evidence.md](../../operations/worker-measurement-evidence.md).
