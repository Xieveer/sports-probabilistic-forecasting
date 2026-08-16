# TASK-007-5 — Production topology, scheduler и доступы

> **Статус:** done
> **Владелец:** implementer + devops-reviewer
> **Эпик:** [EPIC-007](../EPIC-007-autonomous-production-data-runtime.md)
> **Требование:** [REQ-007](../../product/requirements/REQ-007-production-data-runtime.md)
> **ADR:** [ADR-007](../../architecture/adr/ADR-007-autonomous-production-data-runtime.md)

## Результат и границы

Адаптировать production Compose/runtime contract для full-history data store и
tournament-scoped job, подготовить systemd timer/service contract и
least-privilege Object Storage access. Реальный rollout, секреты и изменение
VPS остаются Operations Agent и требуют отдельного разрешения.

## Критерии приёмки

- [ ] API/bot/read-write jobs имеют только необходимые mounts и DB/S3 права;
  training/DVC/MLflow отсутствуют из runtime images.
- [ ] Scheduler contract задаёт per-profile cadence, safe run ID, lock, timeout,
  retry, last-success signal и no-overlap policy.
- [ ] `docker compose config` и static tests проверяют immutable image/model
  inputs, persistent volumes, health/readiness и отсутствие public metrics.

## План реализации

1. Написать failing topology/scheduler/credential-boundary tests.
2. Обновить Compose, env templates, runtime images и systemd unit templates.
3. Провести devops/security review без deployment.

## Проверка

`docker compose config`, targeted topology tests, security review и dry-run
systemd command in non-production environment.
