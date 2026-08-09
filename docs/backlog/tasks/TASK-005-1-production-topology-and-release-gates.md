# TASK-005-1 — Production topology и release gates

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-005](../EPIC-005-production-serving-readiness.md)
> **Требование:** [REQ-005](../../product/requirements/REQ-005-production-serving-release.md)
> **ADR:** [ADR-005](../../architecture/adr/ADR-005-production-serving-boundary.md)

## Результат и границы

Production profile запускает только API, PostgreSQL, bot, Caddy и on-demand
Worker; development Compose не меняется по смыслу. Release workflow формирует
evidence для immutable digest и scans, а deployment workflow не стартует сам
после build. Реальный publish/deploy не входит.

## Критерии приёмки

- [x] `docker compose ... config` не содержит MLflow, Airflow, Prometheus,
  Grafana или node-exporter и не публикует API/metrics минуя Caddy.
- [x] Runtime image не копирует полный `data/`/`models/`; production mounts
  допускают только будущий model/runtime-data contract.
- [x] CI требует lint/tests/security/image scans до release attestation и
  сохраняет commit/tag/digest correspondence без mutable-only identifier.
- [x] Нет workflow, автоматически выполняющего production deployment.

## План реализации

1. Добавить статические/Compose tests, фиксирующие допустимые сервисы, ingress,
   image reference и отсутствие auto-deploy.
2. Разделить dev/prod Compose и Docker targets, добавить release evidence
   workflow и образный scanning без ослабления существующих gates.
3. Документировать только реализованные команды и обновить handoff.

## Проверка

- Целевые tests, `docker compose -f docker-compose.prod.yml --profile worker config`, `make lint`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-005-1](../../changes/done/TASK-005-1-production-topology-and-release-gates.md).
