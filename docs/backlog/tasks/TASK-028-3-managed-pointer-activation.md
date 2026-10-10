# TASK-028-3 — DB pointer и безопасная активация managed-модели

> **Статус:** backlog
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

- [ ] Аддитивная миграция хранит `bundle_id` и разрешённый immutable artifact
  location у managed deployment. DB constraint/index запрещает две active
  записи одной пары и active managed-запись без bundle. Старые записи остаются
  без придуманного ID и требуют явного bind.
- [ ] Активация проверяет checksum, v2 manifest, соответствие пары и признаков,
  runtime и загрузку доверенного model entrypoint внутри bundle root до DB
  commit. Identity нельзя повторно привязать к другим байтам; ошибка оставляет
  прежний active pointer.
- [ ] Все production managed entrypoints используют pinned deployment и bundle;
  файловый `current` не выбирает managed-модель и не используется как fallback.
  Legacy-профиль сохраняет v1-путь.
- [ ] Повторная проверка pinned identity и DB publication находятся в одной
  короткой транзакции с совместимым протоколом блокировок promote/rollback.
  Promotion во время inference не публикует результат старой версии.
- [ ] Текущие API/бот продолжают читать прежнюю валидную витрину при отказе
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

## Проверка

- Red: новый PostgreSQL concurrency test падает на публикации устаревшей
  модели или на отсутствии DB constraint.
- Green: `uv run pytest -q tests/test_model_bundle.py tests/test_model_registry.py tests/test_materialize.py tests/test_worker.py tests/test_canonical_full_refresh.py` и новый PostgreSQL concurrency test — ожидается success.
- `make lint`, `make test-unit` и независимый review после реализации.
- Наблюдение: active pointer и загруженный bundle совпадают; при race прежняя
  витрина не меняется.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-028-3-managed-pointer-activation.md`.
- Следующий TASK: [TASK-028-4](TASK-028-4-immutable-prediction-revisions.md)
  после независимого review и schema gate с EPIC-027.
