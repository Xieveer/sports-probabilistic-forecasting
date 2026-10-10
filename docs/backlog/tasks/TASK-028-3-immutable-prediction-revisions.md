# TASK-028-3 — Неизменяемые версии опубликованного прогноза

> **Статус:** backlog
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

- [ ] Revision хранит точный `bundle_id`, `model_identity`, `model_pool`,
  `feature_contract_id`, UTC время расчёта, run/input reference, canonical event
  ID либо tournament + source namespace + source event ID, `market_spec`,
  явные outcomes и полный набор вероятностей.
- [ ] Повтор того же run/event/market с тем же payload возвращает тот же
  revision ID; иной payload под тем же ключом отвергается. Новый run создаёт
  новую revision даже при тех же вероятностях.
- [ ] Revision и `predictions.current_revision_id` с текущими значениями
  сохраняются атомарно. Ошибка после создания revision, empty input и stale
  transition не оставляют частичной публикации и не стирают прежние revisions.
- [ ] Ключ текущей витрины включает tournament; совпадающий source match ID в
  разных турнирах не перезаписывает чужой прогноз. Старые строки без доказанного
  bundle имеют nullable revision reference и не получают фиктивную историю.
- [ ] Внутреннее чтение по revision ID возвращает прежние вероятности и
  provenance после новых materialize; API продолжает выдавать актуальную строку.

## План реализации

1. **Schema gate:** с EPIC-027 согласовать Alembic head, event namespace,
   стабильный ID revision и nullable будущую связь odds observation; зафиксировать
   совместимые типы до миграции. Связь с odds при отсутствии наблюдения не
   обязательна; поздняя связь оформляется отдельной записью.
2. **Red:** DB integration tests для повторного run, нового run, двух турниров
   с одним source ID, rollback транзакции между revision и витриной, legacy row
   без bundle и чтения прежней revision.
3. **Green:** аддитивная миграция, append-only repository и атомарный
   `publish_showcase`; сохранить API/бот contract текущей витрины.
4. **Refactor:** убрать только затронутое дублирование записи, обновить
   документацию витрины и migration/recovery notes.

## Затрагиваемые области и зависимости

- Ownership Developer: `sports_forecast/service/db/models.py`,
  `sports_forecast/service/db/repository.py`, новая Alembic revision,
  `sports_forecast/materialize.py`, адресные DB/API tests и документация.
  Не изменять EPIC-027 schema и не выбирать odds as-of за него.
- Вход: reviewed [TASK-028-2](TASK-028-2-managed-bundle-activation.md).
  PostgreSQL-проверка миграции обязательна; nullable поля и forward-fix
  сохраняют старую витрину и legacy rows.

## Проверка

- Адресные тесты `tests/test_prediction_publication.py`,
  `tests/test_materialize.py`, новые DB revision tests и API regression tests —
  ожидается success на SQLite; миграция и атомарность проверяются на PostgreSQL.
- `make lint`, `make test-unit` и независимый review после реализации.
- Наблюдение: два разных revision ID для двух run одного события, прежняя
  версия читается, API возвращает последнюю.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-028-3-immutable-prediction-revisions.md`.
- Следующий TASK: [TASK-028-4](TASK-028-4-two-algorithm-local-cycle.md)
  после независимого review.
