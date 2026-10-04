# TASK-026-5 — Публикация и установленная серверная версия registry

> **Статус:** реализация и независимый review завершены; эксплуатационный gate открыт
> **Задача:** [TASK-026-5](../../backlog/tasks/TASK-026-5-registry-publication.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **Решение:** [ADR-027](../../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md)

## Изменения

- Локальный publisher загружает immutable content-addressed snapshot и publication,
  перечитывает удалённые bytes перед условной сменой `current.json`. CAS, потерянный
  ответ и durable pending intent исключают тихую перезапись конкурирующей версии.
- Отдельный server sync однократно закрепляет удалённый current, проверяет цепочку
  публикаций и пакеты, затем устанавливает их одной PostgreSQL транзакцией. При
  ошибке сохраняется прежняя active publication; rollback оформляется новой
  последовательной публикацией уже проверенного snapshot.
- Миграция `0019` добавляет immutable projection `ir1`, publication history,
  active pointer, lock и версионированный event bridge. Reader закрепляет
  установленную версию и использует bounded cache; runtime не читает storage.
- Добавлены CLI, пример настроек и
  [runbook](../../operations/entity-registry-publication.md) с разделением
  credentials, ограничениями sync, восстановлением и требуемыми grants.

## Проверки

- Целевой запуск шести suites: **77 passed, 3 warnings**.
- `make lint` — passed; scoped `mypy --follow-imports=silent` по десяти файлам —
  passed; `ruff format --check` по затронутым файлам и `git diff --check` — passed.
- Независимый holistic review: P0–P2 нет после исправления инструкции по
  `INSERT` первой строки active pointer. Reviewer запустил 59 combined tests,
  Ruff, scoped mypy и `git diff --check`.
- Изолированный PostgreSQL 16 fixture: 11 installation tests и migration
  upgrade/check прошли. Fixture, схема и контейнер удалены после проверки.
- Conditional-write probe на изолированном локальном S3-compatible MinIO
  endpoint вернул `supported`; fixture удалён. Этот результат подтверждает
  исполнимость probe, но не возможности рабочего endpoint.
- На синтетической проекции (100 турниров, 100 событий, 700 обозначений,
  1100 records, 391200 bytes) cold pin занял 29,150 мс, cache pin 0,583 мс;
  это локальное измерение, не оценка производительности для сотен турниров.

## Открытый эксплуатационный gate

В рабочем окружении нет Object Storage credentials и отдельной sync DB role.
Live probe текущего endpoint/bucket, фактические IAM/DB grants, retention prefix
и расписание sync не проверялись. Поэтому [TASK-026-5](../../backlog/tasks/TASK-026-5-registry-publication.md)
остаётся `blocked`, production registry mode не включён. Разработка
[TASK-026-6](../../backlog/tasks/TASK-026-6-registry-candidate-feedback.md)
продолжается на проверенном локальном контракте.
