# TASK-025-7 — Итог и query DTO Data Cycle

> **Статус:** done после закрытия зависимых TASK-025-4/6/8/10.
> Этот отчёт сохраняет evidence исходного terminal/query среза `9dd511a`;
> последующие реализации и их проверки описаны в отдельных отчётах задач.

## Результат

- Репозиторий отдаёт текущий незавершённый run и ограниченную историю для любого
  `tournament`; последние запуски отсортированы по `requested_at`.
- Generic DTO сериализует safe run/stage fields и только allowlisted
  nonnegative counters. Внешний provider payload и неизвестные поля не попадают
  в DTO.
- Terminal policy блокирует запуск publication, пока quality не завершилась
  успешно или частично. Pipeline profile из tournament Hydra config задаёт
  required stages; `success` требует success у всех фиксированных стадий,
  `partial_success` требует завершённых mandatory стадий и зафиксированную
  неполноту. Failed mandatory stage допускает только terminal `failed`.
- Repository не содержит NHL-specific required-stage set: тестовый
  `football_fixture` передаёт другую policy и завершает cycle по общему контракту.
- NHL policy хранится в `conf/tournament/nhl.yaml`; Data Cycle CLI загружает его
  через `load_required_stages` и отвергает отсутствующую или некорректную policy.
- Summary/query schema поддерживает поля events, eligible, forecasts,
  independent odds observations, readiness, errors, duration и явные
  числитель/знаменатель coverage. На момент исходного среза producers части
  полей ещё не были подключены; не записанное значение остаётся `null`;
  знаменатель 0 не превращается в 100%.
- NHL odds readiness не выводится из legacy forecast data. Summary показывает
  только записанное значение `independently_observed_events`; stage wiring
  подключён в TASK-025-6.
- Обычный terminal outcome `finish_run` и executor failure `fail_run` оба
  сохраняют агрегированное summary; проверка ошибок подтверждает terminal
  summary даже при прерванной стадии.
- Дополнительные счётчики из CLI сохраняют только allowlisted независимые
  значения; вычисленные по стадиям события, готовность, ошибки, длительность и
  покрытие нельзя переопределить. Regression test подтверждает, что CLI
  `events_found=1` не заменяет наблюдённое значение `5`, а coverage остаётся `3/4`.

## Проверки

| Команда | Результат |
|---|---|
| Red: изолированные correction tests до реализации | failed по ожидаемым причинам: policy parameter отсутствовал, failed mandatory мог быть partial, terminal success позволял пустой run; отдельный red воспроизвёл supplemental override derived coverage |
| `uv run pytest tests/test_data_cycle_lifecycle.py tests/test_canonical_full_refresh.py tests/test_canonical_full_refresh_cli.py tests/test_data_cycle_runner_contract.py tests/test_readiness_and_migrations.py -q` | 35 passed |
| `uv run ruff check sports_forecast/service/db/repository.py sports_forecast/service/data_cycle_history.py tests/test_data_cycle_lifecycle.py` | passed |
| `uv run ruff format --check sports_forecast/service/db/repository.py sports_forecast/service/data_cycle_history.py tests/test_data_cycle_lifecycle.py` | passed |
| `uv run pre-commit run mypy --files sports_forecast/service/db/repository.py sports_forecast/service/data_cycle_history.py tests/test_data_cycle_lifecycle.py` | passed |
| `make docs` | build succeeded; 24 warnings (existing missing `_static`, duplicate autodoc descriptions and upstream warnings) |
| `git diff --check` | passed |

Второй regression запуск выявил, что прямой тестовый старт publication теперь
обязан пройти quality; fixture исправлен на корректный переход. Повторный набор
прошёл полностью. Тесты запускались с локальным SQLite; PostgreSQL race/runtime
не проверялись.

## Границы исходного среза и закрытие зависимостей

- HTTP endpoints исходного среза намеренно не добавлялись. TASK-025-4 позднее
  добавил service credential, допустимого admin principal и отдельный control
  DB session; история не выставляется unauthenticated.
- Crash/timeout recovery и executor fencing реализованы в
  [TASK-025-8](../../backlog/tasks/TASK-025-8-executor-fencing.md). Истечение
  heartbeat не запускает второго владельца; production проверка — TASK-025-9.
- Stage producers для found/new/changed, eligible/ready forecasts и
  full/partial readiness подключены в
  [TASK-025-10](../../backlog/tasks/TASK-025-10-run-summary-producers.md),
  ready odds — в TASK-025-6. Их отдельные отчёты содержат итоговые проверки.

## Изменённые файлы

- `sports_forecast/service/db/repository.py`
- `sports_forecast/orchestration/data_cycle.py`
- `conf/tournament/nhl.yaml`
- `sports_forecast/service/data_cycle_history.py`
- `tests/test_data_cycle_lifecycle.py`
- TASK-025-7 и этот отчёт.

Независимый Reviewer нашёл ложный `success` при пропущенных стадиях, ложный
`partial_success` после отказа обязательной стадии и рассогласование
persisted/query summary. Correction cycle исправил эти случаи. Повторное
review выявило возможность подменить вычисленные счётчики через supplemental;
она закрыта регрессионным тестом. Итоговое review: блокирующих findings нет,
22 целевых теста и `git diff --check` прошли у Reviewer.
