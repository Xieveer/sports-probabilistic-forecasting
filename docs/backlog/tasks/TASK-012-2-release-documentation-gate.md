# TASK-012-2 — Release documentation gate и recovery runbook

> **Статус:** done
> **Владелец:** documentation-writer + devops-reviewer
> **Эпик:** [EPIC-012](../EPIC-012-nhl-source-state-archive.md)
> **Требование:** [REQ-012](../../product/requirements/REQ-012-nhl-source-state-archive.md)
> **ADR:** [ADR-012](../../architecture/adr/ADR-012-nhl-source-state-archive.md) (`accepted`)

## Результат и границы

Операционный контракт prefix/IAM/retention и точные initial bootstrap, restore,
local import и release-evidence инструкции. Dynamic output release pipeline не
коммитится после tag.

## Критерии приёмки

- [x] Handoff, Compose/systemd topology и runbooks отражают source-state
  lifecycle, restore и проверяемые команды.
- [x] Документ определяет new prefix, account/action matrix и retention.
- [x] Workflow/test запрещает процесс release-evidence commit после tag и
  проверяет pre-tag documentation contract.

## План реализации

1. Добавить failing documentation/release-contract test.
2. Обновить канонические docs, `.env.example` и workflow only as needed.
3. Проверить docs, production handoff и release gate; передать DevOps точные
   IAM requests и no-go external evidence.

## Затрагиваемые области и зависимости

- `docs/operations/`, `.env.example`, release workflow/tests.
- Зависит от stable TASK-012-1 contract; actual IAM/lifecycle configuration —
  внешняя ответственность DevOps.

## Проверка

- Targeted tests, `make docs`, `make production-check` и Compose config.

## Handoff и отчёт

- Отчёт выполнения: [TASK-012-2 report](../../changes/done/TASK-012-2-release-documentation-gate.md).
- Follow-up / findings: нет.
- Review: independent DevOps/security/reviewer gates before release.
- Commit/push: reviewer фиксирует evidence до release tag.
