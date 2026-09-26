# TASK-025-10 — Полные счётчики и покрытие Data Cycle

> **Статус:** backlog
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат

Подключить фактические producers к безопасному summary DTO/query TASK-025-7,
чтобы бот и история показывали проверяемые числа по календарю, прогнозам и
котировкам для каждого завершённого цикла.

## Критерии приёмки

- [ ] Summary считает найденные, новые и изменённые canonical события из
  конкретной попытки календаря; не использует общее число записей БД как
  результат одного запуска.
- [ ] Eligible для прогноза и котировок задаётся явной policy/окном;
  ready/full/partial/errors считаются на том же множестве и на дату run.
- [ ] Для каждого покрытия сохранены numerator, denominator и доля;
  denominator 0 даёт `n/a`, а не `0%` или `100%`. Отсутствующий producer
  обозначается `unknown` с причиной, не синтезируется нулём.
- [ ] `success`, `partial_success` и `failed` summary не скрывают последнее
  успешное обновление каждого компонента; history API из TASK-025-4 читает
  ту же сохранённую итоговую запись.
- [ ] NHL и контрольный football fixture используют общий summary контракт,
  разные рынки и policy; fault tests проверяют отказ одной стадии и
  идемпотентный повтор без удвоения счётчиков.

## Зависимости и проверка

- После TASK-025-3/6/7. TASK-025-5 использует эти поля в Telegram.
- Unit/integration с фиксированным временем и идентификатором run;
  независимый Reviewer и отчёт `docs/changes/done/` до release.
