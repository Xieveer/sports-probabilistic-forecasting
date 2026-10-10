# TASK-028-4 — Неизменяемые версии опубликованного прогноза

> **Статус:** in_review
> **Владелец:** Developer
> **Эпик:** [EPIC-028](../EPIC-028-production-model-contract.md)
> **Требование:** [REQ-028](../../product/requirements/REQ-028-production-model-contract.md)
> **ADR:** [ADR-030](../../architecture/adr/ADR-030-production-model-contract.md), accepted

## Результат и границы

Каждая успешная managed-публикация создаёт append-only `prediction_revision`
со стабильным ID и обновляет текущую витрину одной DB-транзакцией. API и бот
продолжают читать актуальную витрину; прежняя версия читается внутренним
repository по ID после повторной материализации и rollback.

EPIC-027 владеет наблюдениями коэффициентов: этот TASK не создаёт их таблиц и
не дописывает поздний odds reference в неизменяемую revision.

## Критерии приёмки

- [x] Revision хранит точный `bundle_id`, `model_identity`, `model_pool`,
  `feature_contract_id`, UTC время расчёта, run/input reference, canonical event
  ID либо tournament + source namespace + source event ID, `market_spec`,
  явные outcomes и полный набор вероятностей.
- [x] Повтор того же run/event/market с тем же payload возвращает тот же
  revision ID; иной payload под тем же ключом отвергается. Новый run создаёт
  новую revision даже при тех же вероятностях.
- [x] Revision и `predictions.current_revision_id` с текущими значениями
  сохраняются атомарно. Ошибка после создания revision, empty input и stale
  transition не оставляют частичной публикации и не стирают прежние revisions.
- [x] Ключ текущей витрины включает tournament; совпадающий source match ID в
  разных турнирах или source namespace не перезаписывает чужой прогноз. Старые
  строки без доказанного bundle имеют nullable revision reference и не получают
  фиктивную историю.
- [x] Вероятности winner проверяются на конечность, диапазон [0, 1] и сумму до
  записи showcase/revision.
- [x] Внутреннее чтение по revision ID возвращает прежние вероятности и
  provenance после новых materialize; API продолжает выдавать актуальную строку.

## План реализации

1. **Schema gate:** Alembic revision `0023` следует за `0022`; revision использует
   namespace `source` канонического события либо явно заданный namespace вместе с
   source event ID. Odds observation не добавлялась: namespace `ho1` принадлежит
   EPIC-027, а будущая связь оформляется отдельно.
2. **Red:** новый DB test сначала упал на отсутствующем `PredictionRevision`.
   Дополнительно проверены повтор run с тем же payload и отказ на изменённый
   payload; новый run и tournament создают отдельные revisions.
3. **Green:** добавлены аддитивная миграция, append-only repository и атомарный
   `publish_showcase`; SQLite проверяет rollback после создания revision,
   сохранение истории при пустой витрине, legacy без bundle и API response.
4. **Refactor:** managed payload отделён от legacy `bulk_upsert`, ключ mutable
   витрины включает tournament; обновлены migration и materialization runbooks.
5. **Review fixes:** после P2 добавлена nullable source namespace в mutable
   showcase, фильтры repository/API и stale scope по источнику. Вероятности
   валидируются до любой materialize публикации. Новая migration `0024` аддитивно
   добавляет namespace; legacy rows сохраняют `NULL`.

## Затрагиваемые области и зависимости

- Ownership Developer: `sports_forecast/service/db/models.py`,
  `sports_forecast/service/db/repository.py`, новая Alembic revision,
  `sports_forecast/materialize.py`, адресные DB/API tests и документация.
  Не изменять EPIC-027 schema и не выбирать odds as-of за него.
- Вход: reviewed [TASK-028-3](TASK-028-3-managed-pointer-activation.md).
  PostgreSQL-проверка миграции обязательна; nullable поля и forward-fix
  сохраняют старую витрину и legacy rows.

## Проверка

- `make lint` — passed.
- `make test-unit` — 1502 passed, 15 deselected, 40 warnings.
- `uv run pytest -q tests/test_prediction_revisions.py tests/test_prediction_publication.py tests/test_materialize.py` — 29 passed, 1 PostgreSQL-only test deselected/skipped, 3 warnings.
- PostgreSQL disposable schema: Alembic upgrade с `0001` по `0024` прошёл;
  `current` и `heads` указывают на единственный `0024_prediction_source_namespace`.
- PostgreSQL integration rollback/append-only gate — 1 passed; API regression
  входит в SQLite адресный набор. После review fixes: `tests/test_prediction_revisions.py`
  и `tests/test_materialize.py` адресный набор — 5 passed; PostgreSQL integration — 1 passed.
- Независимый review остаётся следующим gate.
- Наблюдение: два разных revision ID для двух run одного события, прежняя
  версия читается, API возвращает последнюю.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-028-4-immutable-prediction-revisions.md`.
- Следующий TASK: [TASK-028-5](TASK-028-5-two-algorithm-local-cycle.md)
  после независимого review.
