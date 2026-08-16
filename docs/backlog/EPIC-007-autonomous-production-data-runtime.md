# EPIC-007 — Автономный production data-runtime `1.1.0`

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-007](../product/requirements/REQ-007-production-data-runtime.md)
> **ADR:** [ADR-007](../architecture/adr/ADR-007-autonomous-production-data-runtime.md) и [ADR-008](../architecture/adr/ADR-008-reliable-delivery-and-private-rollout.md) (`accepted`)

## Цель и границы

Выпустить `1.1.0` как первый автономный NHL production data-runtime: VPS
однократно получает полную историю локальным bootstrap, затем сам обновляет
canonical данные, пересчитывает full-history features/EWM, материализует
прогнозы и публикует проверяемые snapshots для локального training. Эпик не
делает deployment, релизный tag/push, automatic training/promotion, drift или
stateful EWM.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-007-1](tasks/TASK-007-1-canonical-store-and-bootstrap.md) | Canonical store, schema и initial NHL bootstrap | ADR-007 accepted | migration + bootstrap round-trip | done |
| [TASK-007-2](tasks/TASK-007-2-tournament-refresh-quality-gate.md) | Configurable refresh/freshness quality gate | 007-1 | unit + DB integration failures | done |
| [TASK-007-3](tasks/TASK-007-3-full-history-refresh-and-publish.md) | NHL full-history features/inference и publication semantics | 007-1, 007-2 | end-to-end fixture + API visibility | done |
| [TASK-007-4](tasks/TASK-007-4-operational-snapshot-sync.md) | VPS-to-local immutable snapshot sync | 007-1 | archive/import contract tests | done |
| [TASK-007-5](tasks/TASK-007-5-production-runtime-topology.md) | Compose, scheduler contract и least-privilege S3 topology | 007-1…007-4 | compose/static/security tests | done |
| [TASK-007-6](tasks/TASK-007-6-measurement-devops-handoff-and-release.md) | Measurements, DevOps runbooks/handoff и `1.1.0` release readiness | 007-3…007-5, 007-7…007-9 | full-data evidence + production-check | blocked |
| [TASK-007-7](tasks/TASK-007-7-autonomous-source-and-odds.md) | Autonomous source snapshot и odds provenance | ADR-008 | provider/odds failure tests | done |
| [TASK-007-8](tasks/TASK-007-8-verified-archive-sync.md) | Verified archive sync и local import | 007-7 | upload/retry/corruption tests | done |
| [TASK-007-9](tasks/TASK-007-9-private-ingress-and-tag-release.md) | Private candidate Compose и tag-only artifacts | 007-8 | Compose/workflow tests | done |

## Критерии → задачи → доказательства

| Критерий REQ-007 | Задачи | Доказательство |
|---|---|---|
| canonical VPS history и bootstrap без backfill | 007-1 | migration, verified import round-trip |
| deadline/freshness и private failure alert | 007-2, 007-3 | negative integration/API tests |
| full-history NHL refresh и atomic visibility | 007-3 | full pipeline fixture, repeated run test |
| immutable VPS-to-local snapshot | 007-4 | manifest/hash/import/dedup tests |
| autonomous safe operations | 007-5 | Compose/scheduler/S3 permission contracts |
| full-dataset evidence и DevOps documentation | 007-6 | measurement report, runbook dry-run, handoff gate |

## Риски и rollout

- ADR-007 принят владельцем 2026-08-14; зависимые задачи выполняются строго
  последовательно.
- Для NHL сначала обязателен full-history rebuild и измерение. Stateful EWM
  запрещён как скрытая оптимизация в этом эпике.
- Любая migration additive; rollback данных — через verified backup/forward-fix,
  а не destructive schema downgrade.
- `v1.1.0`, immutable GHCR digests и production rollout создаются только после
  всех проверок и отдельного разрешения владельца.
