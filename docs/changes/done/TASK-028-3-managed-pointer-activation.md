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
