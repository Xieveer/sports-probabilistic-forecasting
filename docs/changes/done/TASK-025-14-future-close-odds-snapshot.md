# TASK-025-14 — отчёт об исправлении source snapshot

> **Статус:** реализация, локальные проверки и независимый review завершены
> **Задача:** [TASK-025-14](../../backlog/tasks/TASK-025-14-future-close-odds-snapshot.md)

## Результат

Валидация merged source проверяет наличие odds-колонки, но не требует
исторической closing line у будущего события. Календарный snapshot можно
опубликовать до сбора текущих future odds стадией `data_odds`.

## Доказательство red → green

- **Red:** `uv run pytest tests/test_source_snapshot.py::test_refresh_and_publish_keeps_future_calendar_event_without_close_odds -q` — `ValueError: source CSV содержит будущие события без обязательных odds`.
- **Green:** `uv run pytest tests/test_source_snapshot.py -q` — 8 passed.
- Соседний набор `test_source_snapshot_cli.py`, `test_source_refresh_odds.py`,
  `test_canonical_full_refresh.py`, `test_canonical_full_refresh_cli.py` —
  вместе с snapshot 24 passed.
- `uv run pytest -m unit -q --tb=short` — 1200 passed, 13 deselected.
- `make lint`, `make production-check`, `git diff --check` — passed.
- `make pre-commit` — все hooks passed; `make docs` — сборка завершилась,
  155 предупреждений Sphinx.
- Независимый Reviewer выполнил 37 целевых тестов, проверил code/test/docs
  и не нашёл P0–P2 findings.

## Остаточный gate

Исправление ещё не подтверждено production Data Cycle. Проверить календарное
покрытие, future odds и прогнозы после immutable v1.2.3 release; таймер
включать только после успешного ручного цикла.
