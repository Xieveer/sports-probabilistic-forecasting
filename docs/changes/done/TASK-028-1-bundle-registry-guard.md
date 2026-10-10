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

## Red → green → refactor

- Red: `uv run pytest -q tests/test_materialize.py -k managed_materialize_rejects_registry_bundle_identity_mismatch_before_model_load` — оба варианта (непустой и пустой input) завершились падением assertion `result is False`: прежний код принимал identity из registry и публиковал результат/очищал витрину.
- Green: после guard тот же тест прошёл. Итоговый параметризованный сценарий расширен проверками mismatch, отсутствующего active deployment, отсутствующего/повреждённого bundle и несовместимого app version на пустом и непустом input.
- Refactor: единый resolver проверяет managed provenance до inference; удалён прежний несверенный resolver. Worker и canonical full refresh передают app version явно.

## Проверки

- `uv run pytest -q tests/test_materialize.py tests/test_model_bundle.py tests/test_worker.py tests/test_canonical_full_refresh.py tests/test_prediction_publication.py` — 47 passed, 3 warnings.
- `uv run ruff check sports_forecast/deploy/model_bundle.py sports_forecast/materialize.py sports_forecast/worker.py sports_forecast/orchestration/canonical_full_refresh.py tests/test_materialize.py tests/test_worker.py tests/test_canonical_full_refresh.py` — All checks passed.

## Границы и риски

- Изменены bundle metadata verifier, materialize gate, передача версии в Worker и
  canonical full refresh, адресные тесты и TASK.
- Не изменялись схема БД, pointers, API, история revisions, модельные артефакты и
  production activation. Фактический прогон NHL CatBoost/LightGBM и PostgreSQL
  concurrency остаются последующими gates EPIC-028.
- Независимый review ещё не выполнен; PR не открывался.
