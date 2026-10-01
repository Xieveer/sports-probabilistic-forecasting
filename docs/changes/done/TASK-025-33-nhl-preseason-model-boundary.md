# TASK-025-33 — Отчёт Developer: граница предсезонки NHL

> **Статус среза:** реализация и адресные проверки завершены; задача ожидает
> независимого review и проверки остальных критериев.
> **Дата:** 2026-10-01
> **Задача:** [TASK-025-33](../../backlog/tasks/TASK-025-33-nhl-preseason-model-boundary.md)

## Реализованный результат

В `sports_forecast.data.clean` добавлена модельная граница NHL по `game_type`.
Она применяется после column mapping и до определения статуса, derived
columns и FeaturePipeline. Строки с `game_type=preseason` удаляются только из
модельного interim; источник raw/source и canonical эта стадия не изменяет.
Regular и playoffs сохраняются. Для NHL разрешены только значения
`preseason`, `regular`, `playoffs` без учёта регистра и окружающих пробелов.
Отсутствующая, пустая или неизвестная метка останавливает clean до выдачи
модельного входа.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/data/clean.py` | Фильтр NHL preseason перед подготовкой interim и признаков. |
| `tests/test_data_clean.py` | Регрессии по статусу/счёту, regular/playoffs, другим турнирам и отсутствующей метке. |
| `docs/backlog/tasks/TASK-025-33-nhl-preseason-model-boundary.md` | Результат среза, ограничения и handoff. |

## Доказательство TDD

- **Red:** `uv run pytest -q tests/test_data_clean.py -k 'preseason' --no-cov` — сборка теста упала с `ImportError`, так как фильтра не существовало.
- **Red (review P2):** `uv run pytest -q tests/test_data_clean.py -k 'unknown_game_type' --no-cov` — 4 случая (`None`, пустая строка, `unknown`, `1`) не вызывали ошибку.
- **Green:** после реализации адресный набор прошёл.
- **Refactor:** `uv run ruff format sports_forecast/data/clean.py tests/test_data_clean.py`; затем весь затронутый набор тестов и lint прошли.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest -q tests/test_data_clean.py tests/test_smart_tables_provider.py tests/test_refresh_command.py --no-cov` | 32 passed, 4 warnings. |
| `uv run ruff check sports_forecast/data/clean.py tests/test_data_clean.py` | All checks passed. |
| `uv run ruff format --check sports_forecast/data/clean.py tests/test_data_clean.py` | 2 files already formatted. |
| `git diff --check` | Успешно, замечаний нет. |

## Документация, review и follow-up

- Документация: TASK дополнен результатом этого среза.
- Review / security: ожидает независимого Reviewer.
- Commit/push: не выполнялись; передано Product Owner.
- Follow-up: проверить остальные пути получения model input, отсутствие влияния
  на feature history и betting validation, изменение признаков на историческом
  срезе, затем завершить оставшиеся критерии TASK.

## Остаточные риски

- Воспроизводимые тесты подтверждают фильтрацию на clean boundary, но не
  измеряют изменение значений признаков будущих матчей на полном historical
  наборе.
- Точный состав обучения ранее выпущенной модели остаётся непроверяемым из-за
  отсутствия lineage/hash исходного training snapshot; см. аудит в TASK.
- Production release и перезапуск ежедневного цикла не выполнялись.
