# EPIC-015 — Production first-rollout gate

> **Статус:** in_progress
> **Приоритет:** critical
> **Владелец:** главный агент
> **Требование:** [REQ-017](../product/requirements/REQ-017-production-first-rollout-contract.md)
> **ADR:** [ADR-016](../architecture/adr/ADR-016-first-rollout-runtime-contract.md)

## Цель и границы

Реализовать доказуемый первый rollout в чистом Docker project. Не выполнять
production deployment, publication или выдачу реальных credentials.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-015-1](tasks/TASK-015-1-runtime-bootstrap-and-rollout-gate.md) | Runtime commands, DB roles, local runner и tag gate | ADR-016 | targeted tests + clean Docker scenario | in_progress |

## Риски и rollout

Rollback additive migration выполняется logical restore в isolated DB; production
downgrade не выполняется. Реальные secret files и IAM остаются вне repository.

## Review remediation scope

- Worker table-level grants и catalog deny для Alembic/control tables.
- Fail-closed evidence: health, restart count, ports, resources и scrubbed logs.
- DB restore revision/content и model pointer `current → previous → current`.
- Immutable workflow inputs, tag-version/provenance и clean-tree evidence.
- Воспроизводимый green type gate для затронутого scope.

### Повторное review remediation (2026-09-06)

Исправлены build-once OCI provenance, DB restore schema/content, catalog deny,
Docker health bot, secret-bearing argv и воспроизводимый type gate. До terminal
статуса оставалось Worker RSS/disk evidence; оно добавлено, но финальное review
обнаружило P1 в clean-tree ordering, table grants, актуальности evidence и
runbook secret-file contract.

После закрытия требуется новый independent review. Required GitHub check для
release tags назначается владельцем репозитория вне Git tree.

## Полное EPIC review

Четыре P1 финального review устранены. Повторное independent review
2026-09-07 не выявило blocking findings в implementation diff; проверенный
commit: `2772b93a198573f354643b242ae9a60493020f97`. Independent gates:
mypy passed, targeted pytest — 48 passed, `make production-check`, `make lint`,
`make docs` и `git diff --check` — passed. Sphinx выдал одно существующее
warning об `_static`.

EPIC остаётся `in_progress` до tag CI с official release evidence.
После него потребуется terminal EPIC review доказательств и внешняя
проверка владельцем: required first-rollout check и tag protection в GitHub.

## Security remediation candidate v1.1.7

После перепривязки `v1.1.6` к implementation commit запуск `34093047138`
завершился ошибкой dependency audit до build, publication и first-rollout
evidence: `pyarrow 22.0.0` затронут `PYSEC-2026-113`. Ранний запуск `33961438667`
на прежнем binding `7f8b86f` публиковал образы; оба binding и все их артефакты
quarantined и запрещены для rollout. По явному одобрению владельца runtime
constraint повышен до `pyarrow>=23.0.1`, а lock обновлён полным совместимым
resolver output. Новый immutable candidate — `v1.1.7`; он ожидает независимое
review и успешный tag CI.

Security-release diff прошёл independent review 2026-09-07 без
blocking findings и зафиксирован в commit
`7ab69362a5f55a7965b7b4398b748853ed5da09d`. Reviewer проверил frozen
dependency resolution, security audit, unit/version/type gates, Operations
handoff и явный quarantine обоих исторических binding `v1.1.6`.
EPIC остаётся `in_progress` до успешного tag CI `v1.1.7` и terminal
review его release evidence.

Tag CI `v1.1.7` прошёл security и static gates, но остановился на rendered
Compose contract: workflow не включал профиль `migration`, хотя verifier
проверяет полный набор services. OCI build, first-rollout и publication не
запускались; `v1.1.7` запрещён для rollout. Исправленный immutable candidate —
`v1.1.8`; EPIC остаётся `in_progress` до его успешного tag CI и terminal review evidence.

Candidate `v1.1.8` прошёл independent code/documentation review
2026-09-07 без blocking findings. Проверенный commit:
`c6c258bf3d6f9c9cad1e33d75dd38ea9666d6648`. Exact local rendered Compose
gate с profiles `migration`, `worker`, `source-acquisition`, `operational-sync`
и verifier завершился успешно; version/docs/type/lock gates также
прошли. EPIC остаётся `in_progress` до tag CI `v1.1.8` и terminal
review release evidence.

Tag CI `v1.1.8` прошёл Compose gate, но fail-closed остановился на Worker
runtime gate: read-only container не получил writable `/tmp` для Matplotlib.
OCI build, first-rollout и publication не запускались. Candidate `v1.1.9`
добавляет tmpfs, соответствующий production Compose, и ожидает review/tag CI.
