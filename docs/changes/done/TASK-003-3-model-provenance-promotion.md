# TASK-003-3 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-003-3](../../backlog/tasks/TASK-003-3-model-provenance-promotion.md)

## Подтверждённый результат

Добавлены аддитивная миграция `0002_model_registry_provenance` и registry
immutable model versions. Явные `promote()` и `rollback()` переключают active
pointer только для заданной пары `model_pool/market_spec`, сохраняя все прежние
версии и ссылки на candidate report и artifact. Обучение этот pointer не меняет.

Витрина `predictions` хранит `tournament`, `model_pool` и
`immutable_model_version`. При явном `model_pool` materialize отказывается
работать без active registry pointer и записывает его identity; legacy маршрут
без пула сохранён.

`conf/legacy/nhl-model-manifest.yaml` и `load_legacy_manifest()` дают
read-only путь к старому NHL-артефакту: проверяются обязательные provenance
поля, безопасный относительный путь и наличие артефакта, без переобучения.
Операционная процедура описана в
[model-registry.md](../../operations/model-registry.md).

## Доказательства

- Red: `tests/test_model_registry.py` первоначально не импортировал отсутствующий `ModelRegistryRepository`; rollback-тест — отсутствующий метод `rollback`; legacy-тест — отсутствующий модуль manifest; materialize-тест — отсутствующий resolver provenance.
- `uv run pytest tests/test_model_registry.py tests/test_legacy_model_manifest.py tests/test_materialize.py tests/test_readiness_and_migrations.py -q` — 15 passed.
- `uv run pre-commit run mypy --all-files` — успешно.
- `make lint` — успешно.
- `make test-unit` — 816 passed, 8 deselected.

## Остаточные риски и handoff

Legacy manifest помечен `legacy-unpinned`: полные исторические refs недоступны
и не должны служить основанием для новой версии. Immutable deployment bundle,
checksum, install и runtime rollback остаются задачей
[TASK-005-3](../../backlog/tasks/TASK-005-3-immutable-model-artifact.md).
Следующий этап EPIC-003 — [TASK-003-4](../../backlog/tasks/TASK-003-4-portfolio-orchestration.md).
