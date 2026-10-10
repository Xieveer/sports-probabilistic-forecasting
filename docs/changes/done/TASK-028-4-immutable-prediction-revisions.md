# TASK-028-4 — Immutable prediction revisions

> **Статус:** implementation complete, независимый review ожидается
> **Ветка:** `initiative/epic-028-production-model-contract`
> **TASK:** [TASK-028-4](../../backlog/tasks/TASK-028-4-immutable-prediction-revisions.md)

## Результат

Managed publication создаёт immutable `prediction_revisions` с UUID, run ID,
tournament, source namespace/event ID, рынком/outcomes, вероятностями, bundle и
model provenance, UTC временем расчёта и input snapshot reference. Затем запись
витрины получает `current_revision_id` в той же транзакции. Повтор run с тем же
payload возвращает существующий ID; другой payload под тем же idempotency key
отклоняется. Новый run создаёт новую revision.

Revision включает source namespace и source event ID. Namespace берётся из
канонического registry по точному ключу события либо из явно переданной
конфигурации. Неоднозначное сопоставление блокирует managed publication. Odds
namespace и ссылка на odds observation не добавлялись: это отдельный контракт
EPIC-027.

Mutable showcase upsert теперь включает tournament в ключ, поэтому совпадающий
source match ID разных турниров или source namespace больше не перезаписывает
соседнюю витрину. Migration `0024_prediction_source_namespace` добавляет
nullable namespace и индекс; repository readers и API принимают namespace filter,
а stale transition ограничен источником managed-публикации. Legacy publication
сохраняет nullable `source_namespace` и `current_revision_id`.
Revision защищена от UPDATE/DELETE триггерами в PostgreSQL и SQLite migrations.
API продолжает отдавать актуальную строку витрины; добавлен API regression test.

После независимого review устранены два P2: showcase был разделён по
`source_namespace`, а model probabilities теперь проверяются на конечность,
диапазон [0, 1] и сумму до создания любых записей публикации.

## Red → green → refactor

- **Red:** `uv run pytest -q tests/test_prediction_revisions.py` сначала завершился
  ожидаемой ошибкой импорта: класса `PredictionRevision` не существовало.
- **Green:** после добавления схемы и repository поведения тесты прошли для
  idempotency, отказа при изменении payload, двух run, двух tournaments,
  rollback, пустой витрины, legacy rows, чтения старой revision и API.
- **PostgreSQL gate:** миграционная цепочка была применена в изолированной схеме
  `epic028_task4_20261010` базы `sports_db`. Integration test подтвердил rollback
  revision вместе с showcase и отказ на UPDATE append-only revision.
- **Refactor:** сохранён legacy `bulk_upsert` путь; managed provenance извлекается
  до записи текущей строки. Документация миграций и Worker синхронизирована.

## Проверки

- `make lint` — passed.
- `make test-unit` — 1502 passed, 15 deselected, 40 warnings.
- `uv run pytest -q tests/test_prediction_revisions.py tests/test_prediction_publication.py tests/test_materialize.py` — 29 passed, 1 PostgreSQL-only test skipped, 3 warnings.
- `SF_TEST_PREDICTION_REVISION_DATABASE_URL=<disposable-schema-url> uv run pytest -q tests/test_prediction_revisions.py -m integration` — 1 passed.
- `uv run pytest -q tests/test_prediction_revisions.py tests/test_materialize.py -k 'same_event_id_from_two_sources or prediction_api_continues_to_return_current_showcase or aggregate_rejects_invalid_model_probabilities'` — 5 passed.
- `DATABASE_URL=<disposable-schema-url> uv run alembic -c alembic.ini upgrade head` — успешно; `alembic current` и `alembic heads` показали один head `0024_prediction_source_namespace`.
- `SF_TEST_PREDICTION_REVISION_DATABASE_URL=<disposable-schema-url> uv run pytest -q tests/test_prediction_revisions.py -m integration` — 1 passed на схеме с revision `0024`.
- `uv run ruff check` по затронутым исходникам, migration и tests — passed;
  `git diff --check` — passed.

## Риски и handoff

- Одновременные конкурентные попытки создать один новый idempotency key могут
  получить конфликт уникального ограничения; повтор транзакции caller должен
  перечитать существующую revision. Последовательные повторы покрыты тестом.
- Вызов managed materialize без стабильного `refresh_run_id` или
  `SF_WORKER_RUN_ID` создаёт локальный UUID на попытку; обычный Worker передаёт
  стабильный `SF_WORKER_RUN_ID` из scheduler contract.
- Прямой широкий mypy запуск не является зелёным: он обнаружил 463 ошибки в 40
  файлах, включая текущие проблемы stubs pandas и многочисленные существующие
  ORM annotation errors. Ruff, адресные тесты и полный unit suite зелёные.
- PostgreSQL integration использовал disposable schema; она удаляется после
  завершения проверки. Production DB и модели не изменялись.

Следующий gate — независимый Reviewer, затем Product Owner синхронизирует статус
EPIC-028 и выбирает следующий TASK.
