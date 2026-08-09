# TASK-005-4 — Production materialization job

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-005](../EPIC-005-production-serving-readiness.md)
> **Требование:** [REQ-005](../../product/requirements/REQ-005-production-serving-release.md)
> **ADR:** [ADR-005](../../architecture/adr/ADR-005-production-serving-boundary.md)

## Результат и границы

Оформить Worker как единственную одноразовую команду inference/materialization
без training/Optuna/MLflow. Job принимает approved model/runtime inputs,
атомарно и идемпотентно публикует predictions и безопасный execution state.

## Критерии приёмки

- [x] Явно заданы команда, env names, input/output, timeout, memory/CPU,
  scheduler interface, success/failure/stale semantics и partial-failure path.
- [x] Повтор одного run не дублирует/не портит predictions; неуспех не заменяет
  последнюю валидную витрину.
- [x] Last-success/last-failure не содержит secrets, PII или payload источника.

## План реализации

1. Написать failing DB integration tests: validation failure, retry и atomicity.
2. Реализовать job contract/state store и production command с resource limits.
3. Измерить prod-like runtime на approved fixture и документировать scheduler/runbook.

## Критерии реализации

- Один Worker run имеет безопасный `run_id`, lifecycle `running → succeeded|failed`
  и только счётчики/коды причин в execution state.
- Новая витрина публикуется одной DB-транзакцией после validation и immutable
  bundle verification; при ошибке сохраняется последняя валидная витрина.
- Повторный `run_id` не создаёт второй publish; stale означает отсутствие
  последнего success после согласованного интервала, а не удаление prediction.

## Проверка

- Worker/PostgreSQL integration tests, repeated-run test, measured resource report.

## Блокер

Проведено разрешённое владельцем local development-like измерение legacy NHL
artifact и inference fixture; результат в
[worker-measurement-evidence.md](../../operations/worker-measurement-evidence.md).
Оно не заменяет production image/Object Storage evidence, но закрывает
измерение кода без deployment.

## Handoff и отчёт

- Блокер: TASK-005-2, TASK-005-3 и TASK-005-7.
- Отчёт выполнения: `docs/changes/done/TASK-005-4-materialization-job.md`.
