# TASK-014-1 — отчёт о строгом контракте каталога API

> **Статус задачи:** done
> **Дата:** 2026-08-25
> **Задача:** [TASK-014-1](../../backlog/tasks/TASK-014-1-api-catalog-contract.md)

## Реализованный результат

`DataSourceRecord` различает краткую legacy-card (`partial`) и строгую карточку глубокой
разведки (`complete`). Complete-card содержит typed `ApiEndpointRecord`, `ApiParameterRecord`
и `ApiFieldRecord`; модель проверяет наличие методов и полей, а также ссылочную целостность
`field.endpoint_id`. Каждое поле получает JSON path, тип, nullable, семантику, ключевую роль,
исследовательское назначение, temporal availability, leakage risk и evidence.

Обновлены канонические документы Research Mode и Data Source Catalog. Они определяют, что
старый список имён не является схемой, а human-readable dictionary синхронизируется с
validated JSON-card.

## Изменённые и неизменённые границы

| Изменено | Не изменено |
|---|---|
| Контракт Research Mode и документация API-каталога | Ingest, service/API, DVC, Airflow и внешние запросы |
| Unit tests строгой и legacy validation | Формат существующих partial-карточек |

## Доказательство TDD и проверки

| Этап / команда | Результат |
|---|---|
| Red: `uv run pytest tests/test_research_api_catalog.py -q` | 3 expected failures: отсутствовали completeness и detailed records |
| Green: `uv run pytest tests/test_research_api_catalog.py tests/test_research_orchestrator.py -q` | 13 passed |
| `uv run ruff check sports_forecast/research/contracts.py tests/test_research_api_catalog.py` | Passed |
| `make docs` | Собрано успешно; 15 существующих Sphinx warnings вне затронутой области |

## Остаточные риски и follow-up

- Контракт ещё не доказывает схему конкретного внешнего API: это результат TASK-014-2 и
  TASK-014-3.
- `partial` сохранён ради compatibility, поэтому consumer обязан требовать `complete` для
  field-level engineering/scientific use.
- Независимый review и evidence commit не выполнены; требуются после завершения EPIC.
