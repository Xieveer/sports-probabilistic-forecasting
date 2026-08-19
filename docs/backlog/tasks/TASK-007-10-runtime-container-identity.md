# TASK-007-10 — Выделенная runtime-идентичность контейнеров

> **Статус:** done
> **Владелец:** implementer + security-reviewer + devops-reviewer
> **Эпик:** [EPIC-007](../EPIC-007-autonomous-production-data-runtime.md)
> **Требование:** [REQ-010](../../product/requirements/REQ-010-runtime-container-identity.md)
> **ADR:** не требуется: это точечная security remediation по явно заданному владельцем UID/GID.

## Результат и границы

Устранить коллизию runtime UID/GID `999:999` с host `zabbix:systemd-journal`:
все runtime targets используют `sf` с UID/GID `10001:10001`. Не меняются
VPS, host users, mounts, release tag, registry или deployment.

## Критерии приёмки

- [x] Dockerfile создаёт `sf` с UID/GID `10001:10001`.
- [x] API, Worker, Telegram bot и archive-sync запускаются как `sf`.
- [x] Static test фиксирует numeric UID/GID и все четыре runtime stages.
- [x] Handoff описывает prerequisite Operations и release evidence.

## План реализации

1. Добавить падающий static test Dockerfile для fixed runtime identity.
2. Минимально изменить команду создания пользователя/группы.
3. Выполнить профильные tests, lint/type checks и security/release review без
   публикации или deployment.

## Затрагиваемые области и зависимости

- `Dockerfile`, `Makefile`, production/release contract tests, production handoff и
  артефакты REQ/EPIC/TASK/done.
- Новые tag, published digest, scan и provenance зависят от успешного CI на
  итоговом commit и отдельной release-авторизации.

## Проверка

`uv run pytest tests/test_production_topology.py -q`, `make lint`, релевантный
`mypy` hook и `make production-check`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-007-10](../../changes/done/TASK-007-10-runtime-container-identity.md).
- Follow-up / findings: security-выпуск `v1.1.1` и VPS mount ownership — Operations.
- Review: PR [#22](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/22)
  готов к независимому review; merge и tag требуют его одобрения.
- Commit/push: `57b683a` опубликован в `agent/release-1-0-1`; не входит
  несвязанное изменение `main.py`.
