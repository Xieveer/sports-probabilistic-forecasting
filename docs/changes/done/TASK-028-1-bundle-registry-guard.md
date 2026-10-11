# TASK-028-1 — Проверка bundle и registry до публикации

## Результат

Managed materialize теперь до загрузки модели и inference input проверяет immutable
bundle с ожидаемой версией приложения и сверяет его `model_identity` с active
deployment. Отсутствующий deployment, путь к bundle, повреждённые байты,
несовместимый app version или несовпадение identity блокируют run до inference и
публикации, в том числе при пустом inference input. Успешный run сохраняет
identity, считанную из проверенного bundle, без повторного запроса registry после
inference. Legacy-конфигурация без `model_pool` оставляет прежний путь.

`ModelBundle` теперь возвращает проверенную identity. Worker и canonical full
refresh передают в materialize путь и app version уже проверенного bundle.

После первоначальной реализации исправлен review finding P2: ошибка чтения
artifact после `is_file()` теперь нормализуется verifier-ом в
`BundleVerificationError`. Direct materialize возвращает отказ, а Worker
фиксирует `bundle_verification_failed` вместо оставления execution в состоянии
started.

## Red → green → refactor

- Red: `uv run pytest -q tests/test_materialize.py -k managed_materialize_rejects_registry_bundle_identity_mismatch_before_model_load` — оба варианта (непустой и пустой input) завершились падением assertion `result is False`: прежний код принимал identity из registry и публиковал результат/очищал витрину.
- Green: после guard тот же тест прошёл. Итоговый параметризованный сценарий расширен проверками mismatch, отсутствующего active deployment, отсутствующего/повреждённого bundle и несовместимого app version на пустом и непустом input.
- Refactor: единый resolver проверяет managed provenance до inference; удалён прежний несверенный resolver. Worker и canonical full refresh передают app version явно.
- Red (review finding P2): `uv run pytest -q tests/test_model_bundle.py::test_verifier_normalizes_artifact_read_io_error tests/test_worker.py::test_worker_records_failure_when_bundle_file_read_raises_os_error` — оба теста падали с исходным `OSError`, который обходил обработчик Worker.
- Green: повтор того же адресного запуска — 2 passed после нормализации ошибки в verifier.

## Проверки

- `uv run pytest -q tests/test_model_bundle.py tests/test_worker.py tests/test_materialize.py tests/test_canonical_full_refresh.py tests/test_prediction_publication.py` — 49 passed, 3 warnings.
- `uv run ruff check sports_forecast/deploy/model_bundle.py sports_forecast/materialize.py sports_forecast/worker.py sports_forecast/orchestration/canonical_full_refresh.py tests/test_model_bundle.py tests/test_materialize.py tests/test_worker.py tests/test_canonical_full_refresh.py` — All checks passed.

## Границы и риски

- Изменены bundle metadata verifier, materialize gate, передача версии в Worker и
  canonical full refresh, адресные тесты и TASK.
- Не изменялись схема БД, pointers, API, история revisions, модельные артефакты и
  production activation. Фактический прогон NHL CatBoost/LightGBM и PostgreSQL
  concurrency остаются последующими gates EPIC-028.
- Независимый повторный review ожидается; PR не открывался.
