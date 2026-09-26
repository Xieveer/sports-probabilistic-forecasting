# TASK-025-7 — Восстановление и итог Data Cycle

> **Статус:** backlog
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

Довести durable ingress и stage wiring TASK-025-3 до полного, устойчивого к
сбоям Data Cycle: terminal outcome, безопасное восстановление, summary, coverage
и API истории, на которые опираются админский Telegram и dispatcher. Не
подключать футбольный production pipeline.

## Критерии приёмки

- [ ] Сбой/timeout executor не оставляет вечный `running`. Повторный claim
  запрещён, пока прежний владелец не остановлен или не fenced; PostgreSQL
  concurrency test подтверждает ровно один активный цикл на pipeline/турнир.
- [ ] Каждая стадия calendar, data/odds, quality, predictions, publication,
  archive имеет фактический `success`, `partial_success`, `failed` или `skipped`,
  timestamps, safe reason code и проверяемые счётчики. Не запущенная стадия
  обозначается явно; обязательный quality failure блокирует publication.
- [ ] `failed` означает срыв обязательного результата, `partial_success` —
  достигнутый основной результат с неполным optional scope. Отсутствующий
  будущий odds acquisition до TASK-025-6 не маскируется `success`.
- [ ] Summary показывает найденные/новые/изменённые события, eligible события,
  готовые прогнозы и котировки, полностью/частично готовые, ошибки, время и
  числитель/знаменатель покрытия. При нуле eligible доля `n/a`.
- [ ] Ограниченный API отдаёт текущий и последние run со стадиями, временем,
  причиной, итогом и summary без секретов, сырых внешних ответов и персональных
  данных. Предыдущий успешный run сохраняется отдельно от последней ошибки.
- [ ] Fault injection по каждой обязательной стадии, partial failures,
  process crash/timeout и PostgreSQL race проходят; football fixture
  подтверждает общий контракт run/stage без NHL-specific полей.

## Зависимости и проверка

- Зависит от TASK-025-3. TASK-025-6 подключает calendar-first будущие odds к
  data/odds stage; TASK-025-4 использует terminal/recovery контракт для control.
- Целевые integration/PostgreSQL concurrency tests, shell/CLI regression,
  production topology dry-run и lint.

## Handoff и отчёт

- Отчёт выполнения: ожидается в `docs/changes/done/`.
- Review: ожидается независимый Reviewer.
- Commit/push: ожидается после review.
