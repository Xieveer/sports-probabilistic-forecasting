# TASK-014-1 — Строгий контракт каталога API

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-014](../EPIC-014-research-api-catalog.md)
> **Требование:** [REQ-014](../../product/requirements/REQ-014-research-api-catalog.md)
> **ADR:** [ADR-014](../../architecture/adr/ADR-014-versioned-api-catalog-contract.md)

## Результат и границы

Добавить typed contract endpoint/parameter/field/evidence и правила полноты карточки. Обновить
документацию Research Mode и data dictionary format. Реальные исследования NHL и Smart Tables,
ingest и API-вызовы не меняются в этой задаче.

## Критерии приёмки

- [x] `complete`-карточка требует структурированные endpoint'ы и поля с типом, семантикой,
  JSON path, temporal availability и evidence.
- [x] Неполная `complete`-карточка не проходит Pydantic validation; legacy partial-card
  продолжает быть валидной.
- [x] Документация объясняет связь endpoint → field → temporal risk и место dictionary.

## План реализации

1. Добавить падающие unit-тесты complete/partial validation.
2. Реализовать минимальные typed Pydantic records и compatibility rules.
3. Обновить Research Mode/docs catalog, запустить целевые тесты и docs.

## Затрагиваемые области и зависимости

- `sports_forecast/research/contracts.py`, `tests/test_research_orchestrator.py` либо новый
  focused test, `docs/research/`.
- Существующие DataResearchResult и JSON storage должны оставаться читаемыми для legacy data.

## Проверка

- `uv run pytest tests/test_research_orchestrator.py -q`.
- Целевой новый тест contract validation.
- `make docs`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-014-1](../../changes/done/TASK-014-1-api-catalog-contract.md).
- Follow-up / findings: [TASK-014-2](TASK-014-2-nhl-api-catalog.md) и TASK-014-3.
- Review: требуется независимый review после реализации.
- Commit/push: заполняет reviewer отдельным evidence-коммитом.
