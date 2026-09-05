# EPIC-012 — NHL source-state archive для production

> **Статус:** in_progress
> **Приоритет:** critical
> **Владелец:** главный агент
> **Требование:** [REQ-012](../product/requirements/REQ-012-nhl-source-state-archive.md)
> **ADR:** [ADR-012](../architecture/adr/ADR-012-nhl-source-state-archive.md) (`proposed`)

## Цель и границы

Закрыть blocker production rollout: добавить immutable NHL source-state bundle,
VPS→Object Storage export, read-only local import и строгую последовательность
release documentation → final commit → tag. Эпик не выдаёт IAM права, не
выполняет deployment/tag/image publication и не переносит DVC/MLflow на VPS.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-012-1](tasks/TASK-012-1-nhl-source-state-contract.md) | Bundle/install/export/import contract, orchestration и tests | ADR-012 accepted | bootstrap-refresh-sync failure tests | in_progress |
| [TASK-012-2](tasks/TASK-012-2-release-documentation-gate.md) | Runbooks, IAM/retention contract и pre-tag documentation gate | 012-1 | docs/handoff/release workflow tests | done |
| [TASK-012-3](tasks/TASK-012-3-worker-runtime-dependency-v1-1-5.md) | Worker runtime dependency и final-image fixture gate | 012-1, 012-2 | bare Python import + mounted bundle validators | done |
| [TASK-012-4](tasks/TASK-012-4-production-compose-contract-v1-1-6.md) | Model host bind mount и rendered/final-image v1.1.6 gates | 012-3, ADR-015 | rendered Compose + final Worker model mount | in_progress |

## Риски и rollout

- До `ADR-012 accepted` и IAM confirmation реализация не начинается.
- Новый release — не `v1.1.3`: version выбирается после реализации; tag создаётся
  только с финального documentation commit. Dynamic image digests остаются в
  CI/GHCR evidence, а не в post-tag Git commit.
- Rollback source-state: проверить и установить previous immutable artifact;
  partial artifact никогда не становится current.

## Полное EPIC review

Заполняет независимый reviewer после terminal-статусов всех TASK: покрытие
REQ/ADR, integration risks, документация, release evidence, незавершённый scope,
проверки и hash проверенного commit. Этот hash фиксируется отдельным
documentation-only evidence-коммитом до release tag; до этого раздела EPIC не
получает статус `done`.
