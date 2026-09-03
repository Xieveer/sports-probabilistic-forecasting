# TASK-012-3 — Worker runtime dependency и image gate v1.1.5

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-012](../EPIC-012-nhl-source-state-archive.md)
> **Требование:** [REQ-015](../../product/requirements/REQ-015-worker-runtime-dependency-v1-1-5.md)
> **ADR:** не требуется: исправляются состав runtime и существующий release gate без изменения границ компонентов.

## Результат и границы

Worker runtime видит минимальные зависимости через bare `python`, а CI проверяет
именно final image с immutable fixtures. Не меняются artifact contracts,
production topology, credentials и server state.

## Критерии приёмки

- [x] Bare Worker `python` импортирует operational modules как `10001:10001`.
- [x] CI validates mounted source-state и canonical bootstrap fixtures.
- [x] Runtime не получает MLflow и development tools.

## План реализации

1. Зафиксировать failing release-contract tests.
2. Обновить dependency/runtime path и добавить fixture builder + CI gate.
3. Обновить version/runbook, выполнить targeted и доступные Docker проверки.

## Затрагиваемые области и зависимости

- `pyproject.toml`, `uv.lock`, `Dockerfile`, `.github/workflows/docker.yml`,
  `sports_forecast/deploy/`, tests и operational documentation.
- Финальная image build/scan/provenance зависит от tag pipeline; VPS validation
  выполняется Operations Agent.

## Проверка

- Targeted pytest, fixture-builder smoke, lint/type checks и доступный local
  Docker final-image smoke.

## Handoff и отчёт

- Отчёт выполнения: [TASK-012-3 report](../../changes/done/TASK-012-3-worker-runtime-dependency-v1-1-5.md).
- Follow-up / findings: нет.
- Review: требуется независимый reviewer, security и DevOps review.
- Commit/push: заполняет reviewer отдельным evidence-коммитом до release tag.
