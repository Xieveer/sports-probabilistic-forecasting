# TASK-026-6 — Обратная очередь и полный цикл registry

> **Статус:** реализация и независимое review завершены; CI и эксплуатационный gate открыты
> **Задача:** [TASK-026-6](../../backlog/tasks/TASK-026-6-registry-candidate-feedback.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **Решение:** [ADR-027](../../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md)

## Изменения

- Сервер сохраняет неизвестные обозначения в durable PostgreSQL outbox без
  Object Storage credentials у runtime. Отдельный процесс публикует
  ограниченные immutable batches и собирает подтверждения доставки.
- Локальный importer проверяет порядок, схему и содержимое batch, одной
  транзакцией обновляет очередь и cursor, после commit публикует ack. Повтор
  после потерянного ack безопасен; повторные наблюдения увеличивают счётчик.
- Владелец может создать новое проектное событие прямо из очереди, выбрав
  турнир, команды и время. Сущность, relation, аудит и решение атомарны.
- При исправлении участников спортивным источником runtime обнаруживает
  устаревший bridge, блокирует новые odds и отправляет конфликт владельцу.
  Локальное действие `update_relation` сохраняет ID события и меняет relation
  вместе с аудитом и закрытием кандидата в одной транзакции.
- Строгий runtime закрепляет установленный `ir1`, разрешает коэффициенты
  через подтверждённые проектные ID, сохраняет происхождение линии и
  изолирует ранее записанные линии другой версии. Календарь и прогноз
  спортивного источника остаются доступными при неизвестной линии.
- Старый merge odds в `source.csv` пропускается при строгом режиме, чтобы
  неподтверждённые коэффициенты не попадали в обучающие данные.
- Добавлены CLI, миграции 0020–0021, пример переменных окружения и
  [runbook](../../operations/entity-registry-publication.md).

## Доказательства

- Сквозные тесты NHL и EPL проходят путь server candidate → Object Storage →
  local owner decision → publication → server installation → confirmed odds.
- Тесты покрывают потерянный ack, повтор batch, cursor, атомарность создания
  event и отсутствие привязки odds до подтверждения.
- `make test`: 1409 passed, 5 skipped (требуются disposable PostgreSQL или
  отдельные runtime DB URLs), 37 warnings. `make test-unit`: 1386 passed,
  13 deselected, 37 warnings. `make lint`, pre-commit mypy и
  `make ai-validate` прошли. `make docs` собрал HTML с 155 warnings.
- Независимый Reviewer перепроверил найденные P1/P2 после исправления:
  итоговых P0–P2 нет. Он выполнил 84 ключевых теста после последнего CAS
  исправления, pre-commit mypy, scoped Ruff и `git diff --check`.
- Внешний CI ещё не завершён.

## Открытые gates

- Live endpoint/IAM/DB grants/retention для Object Storage из TASK-026-5 не
  проверены: credentials отсутствуют в рабочем окружении.
- Для включения строгого режима локального обучения на исторических odds
  нужен отдельный проверенный materialization по подтверждённым связям.
- Production deployment не запрошен и не выполнялся.
