# TASK-028-1 — Проверка соответствия bundle и registry до публикации

> **Статус:** backlog
> **Владелец:** Developer
> **Эпик:** [EPIC-028](../EPIC-028-production-model-contract.md)
> **Требование:** [REQ-028](../../product/requirements/REQ-028-production-model-contract.md)
> **ADR:** [ADR-030](../../architecture/adr/ADR-030-production-model-contract.md), proposed

## Результат и границы

Первый защитный срез: materialize не приписывает загруженному verified bundle
identity другой модели из registry. Проверка проходит до inference и любых
изменений публикации, включая путь пустого input. Это промежуточная защита
status quo; единственный pointer и immutable revisions выполняются далее.

Затронуть bundle metadata contract и production materialize gate с unit/integration
тестами. Существующий Worker передаёт resolved immutable bundle path; не добавлять
ветвей под алгоритмы. Не менять schema БД, runtime pointer, legacy NHL payload
или API. Guard применяется также при прямом managed materialize; отсутствие
verified bundle у managed production run блокирует публикацию.

## Критерии приёмки

- [ ] Managed run с active registry identity A и manifest identity B отвергается
  до загрузки модели/inference; существующая DB-витрина полностью сохраняется.
- [ ] То же верно для пустого inference, отсутствующего active deployment,
  отсутствующего/повреждённого bundle и неподходящей app version.
- [ ] При совпадении manifest и registry run сохраняет именно проверенную
  identity; она не подменяется вторым независимым чтением после inference.
- [ ] Legacy-профиль без model_pool сохраняет существующий путь; ошибка managed
  run не включает legacy fallback.
- [ ] Existing bundle integrity/cross-version recovery и publication tests зелёные.

## Red → green → refactor

1. Red: integration test заранее публикует валидную витрину, подставляет
   несовпадающий manifest и registry, вызывает production materialize и
   доказывает отказ, отсутствие inference и неизменность прежних строк.
   Отдельно параметризовать пустой input, чтобы guard не обходился ранним return.
2. Green: вернуть проверенную identity из bundle verifier и сопоставить с
   active deployment перед inference; переносить pinned provenance в publication.
   Использовать общий helper для managed входов, без повторной реализации verifier.
3. Refactor: убрать только дублирование внутри затронутого пути; сохранить
   публичные существующие legacy signatures либо совместимые default arguments.

## Проверка и handoff

Developer фактически запускает новый падающий тест, затем целевые тесты
`tests/test_model_bundle.py`, `tests/test_materialize.py`,
`tests/test_prediction_publication.py` и связанные Worker-тесты, если их путь
затронут. Записывает точные команды и результаты в
`docs/changes/done/TASK-028-1-bundle-registry-guard.md`; до реализации отчёта нет.
Независимый Reviewer проверяет также прямой materialize и empty-input bypass.

Входной gate: Product Owner принимает ADR-030 или возвращает архитектурное
противоречие. Для этого среза реальные legacy веса и EPIC-027 не нужны;
истинный двухалгоритмовый прогон и история revisions остаются gates EPIC-028.
