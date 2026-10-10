# TASK-028-2 — Проверенная активация managed bundle

> **Статус:** backlog
> **Владелец:** Developer
> **Эпик:** [EPIC-028](../EPIC-028-production-model-contract.md)
> **Требование:** [REQ-028](../../product/requirements/REQ-028-production-model-contract.md)
> **ADR:** [ADR-030](../../architecture/adr/ADR-030-production-model-contract.md), accepted

## Результат и границы

Для одной managed-пары `model_pool / market_spec` ручная активация после проверки
bundle v2 меняет единственный DB pointer. Worker, canonical refresh и прямой
materialize получают один pinned contract и не читают файловый `current` как
fallback. При смене pointer во время inference публикация останавливается.
Legacy-профиль manifest v1 остаётся явно выбираемым и совместимым.

В этом срезе нет истории revisions, реального двухалгоритмового прогона и
production-активации.

## Критерии приёмки

- [ ] Manifest v2 content hash охватывает `model_pool`, `market_spec`, правила
  рынка/outcomes, `feature_contract_id`, описание порядка/типов признаков,
  algorithm и точный относительный entrypoint. Verifier отвергает повреждение,
  path traversal, mismatch `deploy.yaml`/`features.txt`, неизвестный алгоритм,
  несовместимый runtime и неоднозначный model file до активации.
- [ ] Для одной пары в БД не более одной active deployment; новая managed-запись
  без проверенного `bundle_id` запрещена. Старые записи не получают выдуманный
  bundle ID и требуют явного bind перед managed resolver.
- [ ] Ручной promote/rollback предварительно проверяет доверенный bundle внутри
  разрешённого root и переключает DB pointer атомарно. Ошибка не меняет active
  запись. Повторное использование `model_identity` с другими байтами запрещено.
- [ ] Все production entrypoints используют pinned managed contract. Проверка
  перед DB publish и publish идут одной короткой транзакцией; конкурентный
  promote/rollback во время inference не публикует устаревший результат.
- [ ] Для `winner_withOT` проверяются два outcome `home_win / away_win`, finite,
  диапазон и сумма вероятностей. Manifest v1 и legacy loader сохраняют
  прежние тесты; managed ошибка не вызывает legacy fallback.

## План реализации

1. **Red:** unit-тесты manifest v2, отказов активации и mismatch признаков;
   PostgreSQL integration test переключает active deployment во время inference
   и проверяет неизменность витрины.
2. **Green:** аддитивная миграция registry с уникальностью active-пары,
   manifest v2 verifier, ручная activation API/repository и общий resolver для
   Worker, canonical refresh и прямого materialize.
3. **Refactor и gate:** оставить manifest v1 в явном legacy-профиле, убрать
   дубли выбора модели в затронутом коде, обновить model bundle/registry runbooks.

## Затрагиваемые области и зависимости

- Ownership Developer: `sports_forecast/deploy/model_bundle.py`,
  `sports_forecast/service/db/models.py`, `sports_forecast/service/db/repository.py`,
  новая Alembic revision, `sports_forecast/materialize.py`, `sports_forecast/worker.py`,
  `sports_forecast/orchestration/canonical_full_refresh.py` и прямые тесты этих
  границ. Не менять файлы EPIC-027; согласовать Alembic head перед миграцией.
- Использовать [TASK-028-1](TASK-028-1-bundle-registry-guard.md) как защитный
  baseline и [ADR-030](../../architecture/adr/ADR-030-production-model-contract.md)
  как контракт. PostgreSQL concurrency нельзя заменить SQLite-тестом.
- Обратимость: до активации прежний pointer и serving-витрина доступны;
  rollback выбирает только проверенную прежнюю deployment identity.

## Проверка

- `uv run pytest -q tests/test_model_bundle.py tests/test_model_registry.py tests/test_materialize.py tests/test_worker.py tests/test_canonical_full_refresh.py` и новый PostgreSQL concurrency test — ожидается success.
- `make lint`, `make test-unit` и независимый review после реализации.
- Наблюдение: при mismatch/pointer race нет новой публикации; при валидном
  bundle v2 active identity совпадает с загружаемыми байтами.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-028-2-managed-bundle-activation.md`.
- Следующий TASK: [TASK-028-3](TASK-028-3-immutable-prediction-revisions.md)
  после независимого review и согласования общей схемы с EPIC-027.
