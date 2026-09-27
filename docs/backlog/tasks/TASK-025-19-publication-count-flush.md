# TASK-025-19 — Счётчики публикации после записи прогнозов

> **Статус:** in_progress — код и review прошли; CI/runtime gate открыт
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Наблюдаемый дефект

Изолированный replay v1.2.5 на копии production данных создал 1 834
prediction rows, включая 213 будущих матчей; ровно 187 совпали с
eligible NHL событиями 30-дневного календаря. Но внутри той же DB
transaction publication сохранила `predictions_count=0` и
`predictions_ready=0`. У SessionFactory `autoflush=False`, а код делает
SQL count/readiness до явного `flush`. После commit повторное read-only
измерение дало `eligible=187`, `predictions_ready=187`.

## Критерии исправления

- [x] После успешной записи прогнозов SQL counts/readiness видят их в той
  же атомарной транзакции; ошибка flush не публикует частичный результат.
- [x] Red→green тест с `autoflush=False` проверяет ненулевые counters и
  соответствие committed rows, а не повторяет внутреннюю реализацию.
- [x] Failed materialization/rollback сохраняют прежнюю витрину и
  безопасный terminal outcome.
- [x] Независимый review не выявил блокирующих замечаний к исправлению.
- [ ] CI и production manual run подтверждают точные
  `predictions_count`/`readiness` и одно уведомление.

## Handoff

[Отчёт выполнения](../../changes/done/TASK-025-19-publication-count-flush.md)
заполняется фактически выполненными проверками.
