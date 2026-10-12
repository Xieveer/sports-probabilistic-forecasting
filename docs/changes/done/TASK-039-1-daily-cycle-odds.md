# TASK-039-1 — Ежедневный Data Cycle без Odds API

> **Статус:** локальная реализация и независимый review пройдены; release gates ожидаются
> **Задача:** [TASK-039-1](../../backlog/tasks/TASK-039-1-daily-cycle-odds.md)

## Изменение

Ежедневный systemd runner явно передаёт Worker `data_odds_enabled=false`. Source snapshot уже использует `--odds-enabled false`. Ручной refresh и `/predict` продолжают использовать прежние пути по запросу.

## Доказательства и остаточные риски

Контрактный тест сначала упал на старом runner без override и прошёл после изменения: `tests/test_data_cycle_runner_contract.py` (10 passed). Тест реального `FeaturePipeline` без моков переводит матч из upcoming в finished: новые результативные данные меняют у следующей игры EWM diff, win-rate и losing streak, а признаки прошлого и завершившегося матча остаются прежними (1 passed). `UV_OFFLINE=1 make test-unit`: 1719 passed, 18 deselected; `UV_OFFLINE=1 make lint`, `UV_OFFLINE=1 make production-check`, `bash -n` и `git diff --check` прошли. `UV_OFFLINE=1 make docs` завершился успешно с 155 предупреждениями из существующей Sphinx-документации. Непустой owner candidate оставлен до подключения нового турнира по решению владельца от 2026-10-12.

Независимый Reviewer проверил код, Hydra override, оба пути сбора коэффициентов,
генерацию признаков, совместимость `/predict`, release handoff и security/regression.
Первичный P2 по устаревшим указаниям v1.3.6 в handoff исправлен автором;
повторная проверка не выявила P0–P2. Проверенный commit:
`a12668883fcb6c552052b0c3dea507f5b22337ae`.
Reviewer повторно выполнил targeted tests (25 passed), `make production-check`,
`bash -n deploy/systemd/run-canonical-refresh.sh` и `git diff --check`;
commit hooks `ruff`, `ruff format`, mypy и AI validation прошли.
CI, Docker/release evidence и production run ещё ожидаются.
