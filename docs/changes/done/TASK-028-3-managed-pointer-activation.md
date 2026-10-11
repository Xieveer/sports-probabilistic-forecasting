# TASK-028-3 — DB pointer и безопасная активация managed-модели

## Результат

Managed activation теперь проверяет v2 bundle до изменения DB pointer и сохраняет
`bundle_id` с разрешённым путём до model entrypoint. Старую registry identity
можно один раз явно bind-ить к проверенному bundle; уже managed identity нельзя
перепривязать. Active pointer уникален по паре `model_pool/market_spec`, а active
managed row без bundle блокируется DB constraint.

Worker, canonical refresh и прямой materialize для managed deployment используют
общий resolver. Materialize загружает точный entrypoint и признаки из pinned
bundle. Перед публикацией он блокирует active registry row и сравнивает pin с
текущим deployment в той же транзакции, что и публикация. Если identity поменялась
во время inference, предыдущая витрина сохраняется. Legacy deployment продолжает
явный v1 путь через `current`.

## Red → green → refactor

- **DB red:** новый repository test упал ожидаемо из-за отсутствующего
  `promote_managed`. После реализации registry tests проверяют единственный
  active pair, запрет managed deployment без binding и разовый legacy bind.
- **Activation green:** tests проверяют bundle checksum/manifest через verifier,
  пару, runtime, feature contract, loader callback и отсутствие pointer change
  при ошибке loader.
- **Publication red:** при временно удалённой проверке active pin
  `test_managed_materialize_rejects_pointer_changed_during_inference` опубликовал
  результат старой модели и заменил витрину. После возврата guard тест стал зелёным;
  прежний `old-match` остался `ok` с прежними вероятностями.
- **PostgreSQL concurrency green:** disposable PostgreSQL test подтвердил, что
  promotion между pin и publication приводит к отклонению stale pin.
- **Refactor:** общий managed resolver используется Worker, canonical refresh и
  materialize; обновлены runbooks registry, Worker и миграций.

## Проверки

- `uv run pytest -q tests/test_model_registry.py -k managed_deployment_requires` —
  сначала ожидаемый red из-за отсутствующего метода, затем passed после реализации.
- `uv run pytest -q tests/test_managed_model_activation.py -m 'not integration'` —
  2 passed.
- `SF_TEST_MANAGED_MODEL_DATABASE_URL=... uv run pytest -q tests/test_managed_model_activation.py -m integration` —
  1 passed на локальном PostgreSQL в изолированной схеме.
- `uv run pytest -q tests/test_materialize.py -k managed_materialize_rejects_pointer_changed` —
  red без publication guard, затем 1 passed с guard.
- `uv run pytest -q tests/test_model_bundle.py tests/test_model_registry.py tests/test_managed_model_activation.py tests/test_materialize.py tests/test_worker.py tests/test_canonical_full_refresh.py` —
  64 passed; PostgreSQL test отдельно passed.
- `make lint` — Ruff: All checks passed.
- `make test-unit` — после исправления test-only regex: 1491 passed,
  14 deselected, 40 warnings.
- `DATABASE_URL=... uv run alembic upgrade head` — успешно на PostgreSQL, revision
  `0022_managed_model_pointer`; `alembic current` и `alembic heads` показали один
  head. Проверка выполнялась в выделенной временной схеме. Прямой SQL подтвердил
  отказ на active managed row без binding, отказ на попытку перепривязать managed
  `bundle_id` и legacy defaults (`is_managed=false`, `bundle_id=NULL`).
- После последней правки fail-closed загрузки algorithm config:
  `uv run pytest -q tests/test_materialize.py tests/test_managed_model_activation.py -m 'not integration'`
  — 21 passed; `make lint` — All checks passed.

## Границы и риски

- Production pointer, production bundle и веса моделей не менялись. Реальный
  двухалгоритмовый прогон остаётся за следующим gate EPIC-028.
- Worker read-only mount использует bundle root. Только контролируемый локальный
  activation caller может менять DB pointer; артефакты должны быть одобренными
  доверенными входами до загрузки сериализованной модели.
- Проверка Alembic выполнена на отдельном PostgreSQL schema поверх полной цепочки
  текущего head `0021`; серверное EPIC-026 release gate остаётся вне этого TASK.
- Независимый review остаётся следующим gate перед PR.

## Изменённые файлы

- DB model/repository, Alembic revision `0022_managed_model_pointer` и новый
  `sports_forecast/deploy/managed_model.py`.
- Materialize, Worker, canonical refresh и относящиеся tests.
- Runbooks `model-registry.md`, `materialization-worker.md`,
  `database-migrations.md`; TASK-028-3.

## Handoff

Следующая роль: независимый Reviewer. После review исправить findings, затем
Product Owner синхронизирует статус EPIC-028 и выполнит последующие release gates.

## Исправления по повторному review

- Managed rollback теперь отдельно проверяет зарегистрированный bundle v2,
  checksum и успешную загрузку entrypoint; только затем под advisory lock
  переключает указатель на точную проверенную запись.
- Legacy `promote()` не может деактивировать active managed pointer. Legacy
  `rollback()` также отказывает для managed target без managed verification.
- Materialize сначала формирует временный parquet, проверяет pin и пишет DB
  витрину, затем заменяет production parquet. Stale pin удаляет временный файл
  и оставляет существующий parquet и DB витрину нетронутыми.

Проверки после review:

- `uv run pytest -q tests/test_managed_model_activation.py -k 'managed_rollback or legacy_promote'` — 2 passed.
- `uv run pytest -q tests/test_materialize.py -k managed_materialize_rejects_pointer_changed` — 1 passed; дополнительно проверено сохранение parquet и отсутствие staging-файла.
- `SF_TEST_MANAGED_MODEL_DATABASE_URL='postgresql+psycopg2://…?options=-csearch_path%3Depic028_review_fix_test' uv run pytest -q tests/test_managed_model_activation.py -m integration` — 1 passed на PostgreSQL 14.24 в выделенной схеме; конкурентный promotion после pin отклоняет stale publication.
- `uv run pytest -q tests/test_model_registry.py tests/test_managed_model_activation.py -m 'not integration' tests/test_materialize.py tests/test_worker.py tests/test_canonical_full_refresh.py` — 49 passed, 1 deselected, 3 warnings.

## Повторный review: rollback и граница публикации

Legacy rollback теперь берёт advisory pair lock до чтения target и проверяет
active deployment под row lock. Если target legacy, а active pointer managed,
rollback отклоняется до любых изменений.

DB showcase остаётся единственной опубликованной витриной для API/бота; parquet
является локальным артефактом. Для внешнего `Session` materialize очищает staging
файл и оставляет прежний parquet, поскольку commit принадлежит caller. Для
внутренней сессии parquet заменяется только после DB commit. Ошибка `replace`
логируется отдельно и не меняет успех уже committed DB публикации.

Red → green и проверки после повторного review:

- До fix `test_legacy_promote_cannot_replace_active_managed_pointer` упал:
  legacy rollback на inactive target переключил active managed pointer.
- До fix параметр `parquet_replace` упал: materialize вернул `False` после
  успешного DB commit; external-session success заменил файл до caller rollback.
- `uv run pytest -q tests/test_managed_model_activation.py -k legacy_promote` — 1 passed.
- `uv run pytest -q tests/test_materialize.py -k 'preserves_publication_boundaries or preserves_file_until_caller_commit'` — 5 passed: stale pin, DB publication failure, replace failure, external caller rollback и внешний DB failure сохраняют нужные границы; tmp очищаются.
- Затронутый набор registry/activation/materialize/worker/canonical refresh — 52 passed, 1 deselected, 3 warnings.
- Disposable PostgreSQL 14.24 concurrency test — 1 passed; временная схема удалена.
