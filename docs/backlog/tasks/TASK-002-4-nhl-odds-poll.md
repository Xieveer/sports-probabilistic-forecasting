# TASK-002-4 — Конфигурируемый poll коэффициентов

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-002](../EPIC-002-nhl-production-mvp.md)
> **Требование:** [REQ-002](../../product/requirements/REQ-002-nhl-production-mvp.md)
> **ADR:** [ADR-002](../../architecture/adr/ADR-002-nhl-telegram-notification-orchestration.md)

## Результат и границы

Добавить отдельный лёгкий Airflow DAG, который по расписанию notification-профиля
сравнивает live коэффициенты для materialized прогнозов в его окне с notification
state и рассылает один агрегированный delta-digest каждому allowlist-получателю.
NHL-профиль задаёт 15-минутный интервал, 48 часов и Pinnacle. Не запускаются
source refresh, ingest, feature generation или materialization.

## Критерии приёмки

- [x] Poll запускается по расписанию профиля, делает не более одного batch
  запроса ко всем релевантным матчам и не пересекается с собственным run;
  NHL-профиль запускается не реже раза в 15 минут.
- [x] Один цикл с новыми или изменёнными коэффициентами создаёт один aggregate
  digest на получателя; пустой цикл не отправляет сообщения.
- [x] Poll исключает начавшиеся матчи и прекращает работу при отсутствии
  релевантных матчей либо всех полученных линиях.
- [x] Ошибка poll отправляет краткое уведомление только admin list и не блокирует
  следующий cycle или утренний refresh.
- [x] CLI выбирает live-odds adapter из параметров профиля без runtime-ветки NHL/Pinnacle.

## План реализации

1. Написать падающие tests для empty/no-change/new/change/start/failure и
   source-level DAG contract.
2. Реализовать один orchestration CLI вокруг notification service и
   сконфигурированного batch live odds adapter; не использовать FastAPI HTTP как
   внутренний обходной путь.
3. Добавить DAG factory с расписанием, timeout, retry и отдельным ограничением
   конкуренции из профиля; связать admin failure notify.
4. Обновить эксплуатационную документацию и выполнить целевые тесты,
   `make test-unit`.

## Затрагиваемые области и зависимости

- TASK-002-2 и TASK-002-3 должны быть `done`.
- Новый DAG и orchestration CLI, live odds adapter, notification service,
  Airflow compose/env docs, tests.

## Проверка

- Целевые pytest для polling/delta/delivery и DAG contract.
- `make test-unit`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-002-4](../../changes/done/TASK-002-4-nhl-odds-poll.md).
- Follow-up / findings: нет.
