# TASK-026-8 — Локальный веб-каталог registry

> **Статус:** done — независимый review завершён
> **Задача:** [TASK-026-8](../../backlog/tasks/TASK-026-8-local-registry-catalog.md)
> **Требование:** [REQ-026 #12](../../product/requirements/REQ-026-entity-registry.md)

## Изменения

- Локальный веб-интерфейс показывает каталог всех активных сущностей с поиском,
  фильтром по типу и ограниченной пагинацией; просмотр не зависит от очереди.
- Страница сущности показывает связанные обозначения с экранированием полей
  источника и предоставляет форму переименования и переназначения confirmed
  designation. Для цели используется UUID из карточки каталога, поэтому выбор не
  ограничен первыми 100 сущностями.
- Обе операции требуют основание и свежую revision формы. Переименование
  сохраняет UUID и пишет `entity_audit`; переназначение сохраняет исходные
  атрибуты designation, проверяет тип цели и пишет owner decision.
- Новые POST-маршруты проверяют loopback Origin, действующую session, CSRF token
  и ограниченный размер запроса. Данные остаются в локальной БД до экспорта и
  публикации нового snapshot.
- Руководство запуска и работы обновлено в
  [local-identity-review.md](../../development/local-identity-review.md).

## Проверки

- Red: `uv run pytest -q tests/test_entity_registry.py::test_registry_lists_designations_for_entity` — ожидаемо упал, поскольку до реализации отсутствовал метод просмотра обозначений.
- `uv run pytest -q tests/test_entity_registry.py tests/test_entity_review.py` — 66 passed после исправлений review и snapshot-теста.
- `uv run ruff check sports_forecast/identity/registry.py sports_forecast/identity/review_service.py sports_forecast/identity/review_app.py tests/test_entity_registry.py tests/test_entity_review.py` — passed.
- `uv run ruff format --check sports_forecast/identity/registry.py sports_forecast/identity/review_service.py sports_forecast/identity/review_app.py tests/test_entity_registry.py tests/test_entity_review.py` — passed.
- `uv run mypy sports_forecast/identity/registry.py sports_forecast/identity/review_service.py sports_forecast/identity/review_app.py` — passed.
- `git diff --check` on TASK-owned implementation, tests and docs — passed.

После замечаний review добавлены регрессии для назначения UUID сущности за
пределами первых 100 и для ссылок пагинации с `&` и `#`; обе проверки проходят.
Параметры каталога в ссылках пагинации теперь формируются через URL encoding.

## Независимое review

- Первый проход выявил два P2: ограничение выбора цели первыми 100 сущностями и
  отсутствие URL encoding параметров пагинации. Оба исправлены.
- Чистый повторный review подтвердил исправления. Reviewer запуск
  `uv run pytest -q tests/test_entity_review.py::test_registry_catalog_is_available_when_candidate_queue_is_empty_and_edits_are_audited tests/test_entity_review.py::test_registry_pagination_url_encodes_ampersand_and_fragment_characters`
  завершился результатом `2 passed`.
- Дополнительно проверено, что после переименования и переназначения новый
  экспортированный и проверенный snapshot содержит изменения, а прежний пакет
  остаётся неизменным и проходит повторную проверку.

## Остаточные проверки

- Изменения не публиковались и не устанавливались на сервер; полный цикл snapshot
  и server smoke остаются за будущим релизным окном.
