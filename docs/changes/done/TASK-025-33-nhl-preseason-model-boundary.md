# TASK-025-33 — Отчёт Developer: граница предсезонки NHL

> **Статус среза:** реализация и независимое review завершены; CI и
> production gate ожидаются.
> **Дата:** 2026-10-01
> **Задача:** [TASK-025-33](../../backlog/tasks/TASK-025-33-nhl-preseason-model-boundary.md)

## Реализованный результат

В `sports_forecast.data.clean` добавлена модельная граница NHL по `game_type`.
Она применяется после column mapping и до определения статуса, derived
columns и FeaturePipeline. В модельный interim проходят только `regular` и
`playoffs`; `preseason` и любые остальные непустые типы исключаются. Raw/source
и canonical эта стадия не изменяет. Отсутствующая или пустая метка останавливает
clean до выдачи модельного входа.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/data/clean.py` | Оставляет только NHL regular/playoffs перед подготовкой interim и признаков. |
| `tests/test_data_clean.py` | Регрессии по статусу/счёту, типам матчей, другим турнирам и отсутствующей метке. |
| `docs/backlog/tasks/TASK-025-33-nhl-preseason-model-boundary.md` | Результат среза, ограничения и handoff. |

## Доказательство TDD

- **Red:** `uv run pytest -q tests/test_data_clean.py -k 'preseason' --no-cov` — сборка теста упала с `ImportError`, так как фильтра не существовало.
- **Red (политика допуска):** `uv run pytest -q tests/test_data_clean.py -k 'model_boundary' --no-cov` — numeric и unknown типы вызывали ValueError вместо исключения из модельной выборки.
- **Red (review P2):** `uv run pytest -q tests/test_data_clean.py -k 'unknown_game_type' --no-cov` — до уточнения владельца 4 случая (`None`, пустая строка, `unknown`, `1`) не вызывали ошибку.
- **Green:** после реализации адресный набор прошёл.
- **Refactor:** `uv run ruff format sports_forecast/data/clean.py tests/test_data_clean.py`; затем весь затронутый набор тестов и lint прошли.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest -q tests/test_data_clean.py tests/test_smart_tables_provider.py tests/test_refresh_command.py --no-cov` | 32 passed, 4 warnings. |
| `uv run ruff check sports_forecast/data/clean.py tests/test_data_clean.py` | All checks passed. |
| `uv run ruff format --check sports_forecast/data/clean.py tests/test_data_clean.py` | 2 files already formatted. |
| `git diff --check` | Успешно, замечаний нет. |
| `make lint`, `make test-unit` | Passed; 1 259 unit passed, 13 deselected, 40 warnings для совмещённого кандидата TASK-025-33/34. |
| Read-only локальный аудит `data/raw/nhl/matches.parquet` из основного checkout | 22 215 строк; 19 151 regular, 1 440 playoffs, 1 500 preseason, 124 других типа. Остаются 20 591; исключаются 1 624. Пустых меток нет. |
| Подсчёт истории исключаемых матчей по сезонам и участникам | У 18 833 из 20 591 regular/playoffs строк ранее в том же сезоне хотя бы один участник имел матч исключаемого типа; максимум 18 таких матчей до одной строки. Это оценка потенциального влияния, не пересчёт фичей. |

## Документация, review и follow-up

- Документация: TASK дополнен результатом этого среза.
- Review / security: независимый Reviewer не нашёл блокирующих замечаний
  к фильтру типов, архивированию и границе модельного входа; замечание P2
  по календарю в TASK-025-34 исправлено и повторно проверено.
- Commit/push и terminal CI выполняются после этой документации.
- Follow-up: точное изменение признаков и retraining выпущенной модели
  требуют отдельного исследования и решения владельца.

## Остаточные риски

- Воспроизводимые тесты подтверждают фильтрацию на clean boundary, но не
  измеряют изменение значений признаков будущих матчей на полном historical
  наборе.
- Точный состав обучения ранее выпущенной модели остаётся непроверяемым из-за
  отсутствия lineage/hash исходного training snapshot; см. аудит в TASK.
- Production release и перезапуск ежедневного цикла не выполнялись.
