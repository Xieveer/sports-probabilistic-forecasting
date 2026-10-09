# TASK-026-5 — Публикация и установленная серверная версия registry

> **Статус:** реализация и независимый review завершены; эксплуатационный gate открыт
> **Задача:** [TASK-026-5](../../backlog/tasks/TASK-026-5-registry-publication.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **Решение:** [ADR-029](../../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md)

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

### Повторная локальная проверка 2026-10-04

- Изолированные PostgreSQL 16 и MinIO из локальных Docker-образов: endpoint
  probe вернул `supported` для `If-None-Match` и `If-Match`; 12 тестов установки
  registry прошли на PostgreSQL.
- Сквозной цикл с реальным S3 transport и PostgreSQL projection прошёл:
  публикации с sequence 1 → 2 → 3, сохранение project ID после переименования,
  идемпотентный повтор sync и откат к прежнему snapshot новой публикацией.
- На отдельной пустой PostgreSQL БД `alembic upgrade head` применил миграции
  до `0021`, `alembic check` не обнаружил новых операций.
- Шесть целевых suites публикации, sync и обратной очереди: **51 passed**.
  `make test` с тестовой PostgreSQL: **1475 passed, 2 skipped, 40 warnings**.
  Два пропуска относятся к тестам прав отдельных runtime DB roles, URL которых
  не были настроены в локальной среде.
- Использованы только локальные тестовые bucket, prefix и БД. Рабочий Object
  Storage endpoint и фактические IAM/DB grants этой проверкой не охвачены.

## Открытый эксплуатационный gate

### Live Object Storage gate 2026-10-09

- На существующем bucket `sports-probabilistic-forecasting` сохранены 14 прежних
  правил policy и добавлены семь правил для четырёх отдельных registry service
  accounts. IAM роли назначены только на этот bucket; публичный доступ закрыт.
- Для `entity-registry-contract-probe/` добавлено единственное lifecycle правило
  удаления через семь дней. `entity-registry/v1/` не охвачен автоматическим
  удалением; `DeleteObject` новым accounts не предоставлен.
- Live endpoint probe приложения подтвердил `If-None-Match`, `If-Match`,
  сохранность bytes после конфликтов и отказ устаревшего ETag. Проверены 14
  разрешённых и запрещённых IAM операций, включая запрет чужого prefix.
  Policy и lifecycle перечитаны после применения.
- Значения ключей не выводились и не попали в Git. Секретные файлы размещены
  вне репозитория с правами `0600`; на VPS ключи пока не доставлены. Подробные
  идентификаторы, схема доступа и rollback записаны Operations Agent в
  `docs/changes/2026-10-09-epic026-object-storage-access.md` и
  `docs/runbooks/sports-forecast-epic026-object-storage.md` отдельного
  репозитория `operations-agent`.

Отдельная sync DB role, фактические PostgreSQL grants, server sync/feedback и
расписание не проверялись. Поэтому [TASK-026-5](../../backlog/tasks/TASK-026-5-registry-publication.md)
остаётся `blocked`; production registry mode не включён.
