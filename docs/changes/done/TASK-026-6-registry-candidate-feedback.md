# TASK-026-6 — Обратная очередь и полный цикл registry

> **Статус:** done; эксплуатационный gate EPIC-026 открыт в TASK-026-5
> **Задача:** [TASK-026-6](../../backlog/tasks/TASK-026-6-registry-candidate-feedback.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **Решение:** [ADR-029](../../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md)

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
- После слияния с актуальным `main` режим `inference_only` переносит identity
  provenance для обычного и пустого inference результата.
- Добавлены CLI, миграции 0020–0021, пример переменных окружения и
  [runbook](../../operations/entity-registry-publication.md).

## Доказательства

- Сквозные тесты NHL и EPL проходят путь server candidate → Object Storage →
  local owner decision → publication → server installation → confirmed odds.
- Тесты покрывают потерянный ack, повтор batch, cursor, атомарность создания
  event и отсутствие привязки odds до подтверждения.
- `make test` после слияния с `main`: 1472 passed, 5 skipped (требуются
  disposable PostgreSQL или отдельные runtime DB URLs), 40 warnings.
  `make test-unit` до слияния: 1386 passed,
  13 deselected, 37 warnings. `make lint`, pre-commit mypy и
  `make ai-validate` прошли. `make docs` собрал HTML с 155 warnings.
- Независимый Reviewer перепроверил найденные P1/P2 после исправления:
  итоговых P0–P2 нет. Он выполнил 84 ключевых теста после последнего CAS
  исправления, pre-commit mypy, scoped Ruff и `git diff --check`.
- [PR #61](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/61):
  CI Python 3.12, аудит зависимостей и проверка filesystem/secrets завершились
  успешно на объединённой с `main` ветке. PR остаётся draft до внешнего gate.

## Открытые gates

- Live endpoint/IAM/DB grants/retention для Object Storage из TASK-026-5 не
  проверены: credentials отсутствуют в рабочем окружении.
- Для включения строгого режима локального обучения на исторических odds
  нужен отдельный проверенный materialization по подтверждённым связям.
- Локально включённый `identity_registry.yaml` и серверный canonical full
  refresh пока нельзя совмещать: временный raw parquet этого отдельного
  entrypoint не получает локальный identity sidecar. Обычный локальный
  DVC/ingest/training путь использует свой provenance-контракт.
- Production deployment не запрошен и не выполнялся.
