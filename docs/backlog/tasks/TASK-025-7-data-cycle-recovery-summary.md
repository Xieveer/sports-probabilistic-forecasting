# TASK-025-7 — Итог и query-контракт Data Cycle

> **Статус:** blocked — terminal/query DTO reviewed; полный summary и endpoint в TASK-025-10/4
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

Усилить terminal lifecycle TASK-025-3 и добавить безопасные summary/history
query DTO, которые могут использовать admin API и dispatcher. Не подключать
футбольный production pipeline.

## Критерии приёмки

- [ ] Сбой/timeout executor не оставляет вечный `running`. Повторный claim
  запрещён, пока прежний владелец не остановлен или не fenced; PostgreSQL
  concurrency test подтверждает ровно один активный цикл на pipeline/турнир.
- [x] Quality failure блокирует старт publication и не может быть скрыт итогом
  `success`/`partial_success`. Счётчики history DTO проходят allowlist и не
  раскрывают неожиданные поля.
- [x] Итог policy-driven: configured required stages должны реально завершиться;
  `success` требует success всех стадий, partial не скрывает failed mandatory.
  Required stage set приходит из tournament profile
  (`conf/tournament/nhl.yaml`), не задаётся в боте.
- [ ] Каждая стадия calendar, data/odds, quality, predictions, publication,
  archive имеет фактический `success`, `partial_success`, `failed` или `skipped`,
  timestamps, safe reason code и проверяемые счётчики. Не запущенная стадия
  обозначается явно; обязательный quality failure блокирует publication.
- [ ] `failed` означает срыв обязательного результата, `partial_success` —
  достигнутый основной результат с неполным optional scope. Отсутствующий
  будущий odds acquisition до TASK-025-6 не маскируется `success`.
- [ ] Summary формирует найденные/новые/изменённые события, eligible события,
  готовые прогнозы и котировки, полностью/частично готовые, ошибки, время и
  числитель/знаменатель покрытия из сохранённых stage counters. Отсутствующие
  источники остаются unknown, нулевой знаменатель сериализуется как `null` (`n/a`).
- [x] Query summary оставляет ещё не измеренные producer counters nullable и
  рассчитывает дробь покрытия только при наличии числителя и ненулевого знаменателя.
- [ ] Ограниченный API отдаёт текущий и последние run со стадиями, временем,
  причиной, итогом и summary без секретов, сырых внешних ответов и персональных
  данных. Предыдущий успешный run сохраняется отдельно от последней ошибки.
- [x] Generic current/history query для любого tournament отдаёт ограниченный
  список safe DTO; предыдущие терминальные результаты сохраняются вместе с
  активным run.
- [ ] Fault injection по каждой обязательной стадии, partial failures,
  process crash/timeout и PostgreSQL race проходят; football fixture
  подтверждает общий контракт run/stage без NHL-specific полей.

## Текущий согласованный срез

Реализованы terminal invariants и generic history/query DTO. HTTP admin auth и
control-reader routes принадлежат TASK-025-4, поэтому TASK-025-7 не публикует
неаутентифицированные endpoints и не использует `sf_api_reader` для control
history. Crash recovery, owner fencing и PostgreSQL concurrency вынесены
Product Owner в [TASK-025-8](TASK-025-8-executor-fencing.md): TTL или
непроверяемый `owner_stopped` не разрешают повторный запуск.

## Зависимости и проверка

- Зависит от TASK-025-3. TASK-025-6 подключает calendar-first будущие odds к
  data/odds stage; TASK-025-4 использует terminal/recovery контракт для control.
- Целевые lifecycle/history tests и lint выполнены; recovery tests и PostgreSQL
  concurrency перенесены в TASK-025-8. HTTP auth/control-reader API в TASK-025-4.
- Продуценты new/changed/eligible/fully-ready и exact run-scoped denominator
  выделены в [TASK-025-10](TASK-025-10-run-summary-producers.md): calendar
  import, prediction preparation/materializer и event-readiness aggregation;
  ready odds producer принадлежит TASK-025-6. Все поля nullable до фактического
  наблюдения.

## Handoff и отчёт

- [Отчёт выполнения и проверки](../../changes/done/TASK-025-7-data-cycle-summary.md).
- Review: после correction cycle повторный независимый Reviewer не нашёл
  блокирующих findings; 22 целевых теста прошли при re-review.
- Commit/push: ожидается после review.
