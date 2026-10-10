# TASK-028-3 — DB pointer и безопасная активация managed-модели

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-028](../EPIC-028-production-model-contract.md)
> **Требование:** [REQ-028](../../product/requirements/REQ-028-production-model-contract.md)
> **ADR:** [ADR-030](../../architecture/adr/ADR-030-production-model-contract.md), accepted

## Результат и границы

Для одной managed-пары `model_pool / market_spec` активная запись registry —
единственный pointer. Ручной promote/rollback выбирает только проверенный
immutable bundle v2, а Worker, canonical refresh и прямой materialize получают
один pinned contract. Если pointer изменился во время inference, публикация
останавливается без изменения прежней витрины. Legacy v1 остаётся отдельным
явным профилем.

Не создавать prediction revisions, не проводить реальный двухалгоритмовый
прогон, не менять production pointer и не добавлять отдельный сервис.

## Критерии приёмки

- [x] Аддитивная миграция хранит `bundle_id` и разрешённый immutable artifact
  location у managed deployment. DB constraint/index запрещает две active
  записи одной пары и active managed-запись без bundle. Старые записи остаются
  без придуманного ID и требуют явного bind.
- [x] Активация проверяет checksum, v2 manifest, соответствие пары и признаков,
  runtime и загрузку доверенного model entrypoint внутри bundle root до DB
  commit. Identity нельзя повторно привязать к другим байтам; ошибка оставляет
  прежний active pointer.
- [x] Все production managed entrypoints используют pinned deployment и bundle;
  файловый `current` не выбирает managed-модель и не используется как fallback.
  Legacy-профиль сохраняет v1-путь.
- [x] Повторная проверка pinned identity и DB publication находятся в одной
  короткой транзакции с совместимым протоколом блокировок promote/rollback.
  Promotion во время inference не публикует результат старой версии.
- [x] Текущие API/бот продолжают читать прежнюю валидную витрину при отказе
  активации или publication race.

## Red → green → refactor

1. **Red:** DB tests проверяют две active записи, unbound legacy deployment,
   reuse identity с другими байтами и отказ до смены pointer. PostgreSQL
   concurrency test переключает модель между pin и publish; ожидает rollback
   витрины. Отдельный тест проверяет прямой materialize и legacy без fallback.
2. **Green:** миграция registry, activation repository и общий resolver/pinned
   contract для Worker, canonical refresh и materialize. Проверку актуальности
   под блокировкой выполнить только в короткой publication-транзакции.
3. **Refactor:** убрать затронутые дубли чтения pointer, обновить runbooks
   model registry/materialization и migration notes; сохранить v1 legacy API.

## Исправления после review

- [x] Legacy `promote()` отклоняет попытку снять активный managed pointer;
  общий legacy `rollback()` не переключает pointer на managed target.
- [x] Managed rollback проверяет checksum/manifest и загрузку entrypoint до
  переключения на ранее зарегистрированный bundle.
- [x] Parquet пишется во временный файл и заменяет production файл только после
  успешного DB publication gate; stale pin сохраняет предыдущий parquet.

## Затрагиваемые области и зависимости

- Ownership Developer: `sports_forecast/service/db/models.py`,
  `sports_forecast/service/db/repository.py`, одна новая Alembic revision,
  `sports_forecast/materialize.py`, `sports_forecast/worker.py`,
  `sports_forecast/orchestration/canonical_full_refresh.py`, нужный activation
  module внутри `sports_forecast/deploy/`, целевые tests и runbooks.
- Вход: reviewed [TASK-028-2](TASK-028-2-bundle-manifest-v2.md). Перед
  миграцией проверить текущий Alembic head в общей ветке с EPIC-027;
  не изменять его schema или файлы инициативы.
- Bundle root read-only для Worker; только локальная ручная activation
  операция меняет pointer. Rollback выбирает ранее проверенную identity.

## Red → green → refactor

- **Red — DB:** `uv run pytest -q tests/test_model_registry.py -k managed_deployment_requires`
  упал ожидаемо: отсутствовал `promote_managed`. Тест затем проверил active pair
  index, запрет active unbound deployment и one-time bind существующего legacy
  identity.
- **Green — activation/resolver:** `uv run pytest -q tests/test_managed_model_activation.py -m 'not integration'`
  — 2 passed. Проверены bundle binding, точный entrypoint, загрузочный callback,
  проверка feature contract и сохранение pointer при ошибке загрузки.
- **Red → green — publication race:** временное удаление guard перед
  `publish_showcase` дало ожидаемый failure:
  `test_managed_materialize_rejects_pointer_changed_during_inference` вернул
  `True` и изменил витрину. После возврата проверки active row тот же тест прошёл
  и прежняя строка осталась нетронутой.
- **Green — PostgreSQL concurrency:** `SF_TEST_MANAGED_MODEL_DATABASE_URL=… uv run pytest -q tests/test_managed_model_activation.py -m integration`
  — 1 passed на PostgreSQL 15 в отдельной схеме `sf_task0283_ephemeral`.
  Конкурирующая активация после pin приводит к несовпадению перед publish.
- **Migration:** `DATABASE_URL=… uv run alembic upgrade head` завершилась на
  `0022_managed_model_pointer`; `alembic current` и `alembic heads` показали
  этот единственный head. Проверено на PostgreSQL в отдельной схеме
  `sf_task0283_migration`.
- **Релевантный suite:**
  `uv run pytest -q tests/test_model_bundle.py tests/test_model_registry.py tests/test_managed_model_activation.py tests/test_materialize.py tests/test_worker.py tests/test_canonical_full_refresh.py`
  — 64 passed, 1 integration test пропущен без URL (запущен отдельно и прошёл).
- `make lint` — Ruff: All checks passed.
- `make test-unit` — 1491 passed, 14 deselected, 40 warnings.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-028-3-managed-pointer-activation.md`.
- Независимый review остаётся следующим gate. Production pointer, production
  bundle и артефакты модели не менялись. Полный двухалгоритмовый прогон и
  migration gate с EPIC-027 остаются последующими задачами.
- Следующий TASK: [TASK-028-4](TASK-028-4-immutable-prediction-revisions.md)
  после независимого review и schema gate с EPIC-027.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-028-3-managed-pointer-activation.md`.
- Следующий TASK: [TASK-028-4](TASK-028-4-immutable-prediction-revisions.md)
  после независимого review и schema gate с EPIC-027.
