# TASK-007-3 — NHL full-history refresh, inference и publish

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-007](../EPIC-007-autonomous-production-data-runtime.md)
> **Требование:** [REQ-007](../../product/requirements/REQ-007-production-data-runtime.md)
> **ADR:** [ADR-007](../../architecture/adr/ADR-007-autonomous-production-data-runtime.md)

## Результат и границы

Реализовать для NHL один bounded refresh job: canonical data snapshot → полный
features/EWM rebuild → immutable model verification → materialization →
transactional publication. При failed/stale gate affected tournament не
появляется в public API/Telegram; прежняя витрина сохраняется для audit/recovery.

## Критерии приёмки

- [x] Job не зависит от prebuilt `processed/inference_long.parquet` и не
  запускает DVC, MLflow или training.
- [x] Полный rebuild использует согласованный canonical snapshot и создаёт
  predictions с run/data/model/feature provenance.
- [x] Успешный run atomically публикует витрину; failure, timeout или duplicate
  run не выдаёт outdated/empty prediction пользователю и не портит audit state.
- [x] Existing immutable NHL model bundle проверяется и может быть активирован
  для первого production run/rollback.

## План реализации

1. Написать end-to-end failing fixture: bootstrap → source update → full
   rebuild → publish; отдельно failure visibility и same-run retry.
2. Вынести generic tournament-scoped runner из serving-only Worker и подключить
   canonical store, quality gate, full feature build и model loader.
3. Добавить API/bot eligibility boundary и защищённый admin failure notification.

## Итог

Выполнено; отчёт: [TASK-007-3](../../changes/done/TASK-007-3-full-history-refresh-and-publish.md).

## Проверка

PostgreSQL integration tests, end-to-end NHL fixture, API contract tests,
repeated-run/timeout negative tests.
