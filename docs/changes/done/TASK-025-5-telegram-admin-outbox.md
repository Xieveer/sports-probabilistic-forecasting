# TASK-025-5 — Outbox terminal notifications

## Реализовано

- Миграция `0017_data_cycle_notification_outbox` добавляет outbox с уникальностью
  `(run_id, destination_alias)`, lease token/deadline, attempt counter и backoff.
- Success, partial success и failure terminal transitions добавляют по одной
  записи на каждый safe alias в той же транзакции. Recovery failure использует
  тот же producer после host proof.
- Защищённый Control API предоставляет claim, ack и retry. Claim берёт строки
  через `SKIP LOCKED`; ack/retry проверяют действующий lease, а retry ограничен
  кодом `telegram_send_failed`.
- Bot poller преобразует alias в один chat ID из runtime config, отправляет
  короткий escaped summary с `run_id`, затем ack; Telegram send failure вызывает
  retry. Chat IDs не хранятся в outbox и не передаются Control API.
- Production Compose требует непустой alias allowlist и монтирует destination
  secret только в Telegram bot. `sf_control_api` может читать и обновлять только
  поля outbox; insert и sequence остаются у `sf_refresh_writer`.

## Проверки

- Целевые проверки после финальной синхронизации — 117 passed, 4 skipped:
  PostgreSQL-only тесты без disposable DB URL в этой среде. Команда охватила
  bot handlers, calendar, control API, repository/outbox, migration, production
  topology и rollout contracts.
- Независимый disposable PostgreSQL 16 gate: полный Alembic upgrade до 0017 под
  NOSUPERUSER ролью `sf_migrator`, runtime grants; outbox lease race и проверки
  grants под фактическими ролями — 33 passed. PostgreSQL container удалён после
  теста. Проверки запрещённых прав покрыли terminal run UPDATE, outbox INSERT и
  sequence для `sf_control_api`, а также outbox SELECT для API reader.
- Независимый review — no P0–P2 findings.
- Общие release gates: `make test` — 1202 passed, 5 PG-gated skips; `make lint`,
  `make docs` (24 warnings), `make production-check`, `make security` (no known
  vulnerabilities) и `make ai-validate` прошли.
- Targeted pre-commit (ruff, format, mypy, YAML, AI roles) и `git diff --check`
  прошли.

## Ограничение доставки

Outbox гарантирует at-least-once. Если процесс аварийно завершится после
успешной отправки в Telegram, но до DB ack, при повторе пользователь может
получить ещё одно сообщение с тем же `run_id`; exactly-once не обещается.
Ручной запуск отправляет отдельное подтверждение с `run_id`, затем одно terminal
summary по alias; плановый запуск отправляет одно terminal summary.

## Статус

Реализация принята после независимого review и указанных release gates. TASK-025-5
закрыт. Фактическая alias destination mapping остаётся release blocker по
[TASK-025-9](../../backlog/tasks/TASK-025-9-release-readiness.md) до production
rollout; этот отчёт не утверждает, что production deployment выполнен.
