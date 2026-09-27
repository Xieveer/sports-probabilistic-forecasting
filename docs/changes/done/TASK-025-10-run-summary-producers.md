# TASK-025-10 — Отчёт: producers итоговой сводки Data Cycle

> **Статус:** завершено; повторное независимое review пройдено
> **Дата:** 2026-09-26
> **Задача:** [TASK-025-10](../../backlog/tasks/TASK-025-10-run-summary-producers.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат

Подключены producers canonical full refresh к сохранённому summary Data Cycle.
Календарная стадия сохраняет число найденных, новых и изменённых событий именно
для текущей попытки импорта. Повтор той же snapshot не считает события новыми.

Eligibility прогнозов и odds рассчитывается по явному горизонту readiness policy.
Счётчики компонентов вычисляются после materialization/publication на одном
зафиксированном `as-of`; timestamp и provenance сохраняются в результате стадии.
Для coverage сохраняются числитель, знаменатель, отношение и статус: пустой
набор даёт `n/a`, отсутствующие counters — `unknown`, без подстановки нулей.

Завершение run сохраняет last-success timestamps из фактических persisted
данных календаря, odds и прогнозов, ограниченных временем завершения run.
Неизвестный timestamp остаётся `unknown`; время завершения failed run не
выдаётся за обновление данных. Сохранённый terminal summary содержит snapshot
значений, поэтому будущие успешные циклы не меняют историю старого run.

Статус `auto` выводится из результатов и обязательности стадий. Failed
обязательная стадия не может завершиться общим `success`; частичная выдача odds
отражается как `partial_success`. Ошибки стадий и событий представлены раздельно,
а общий счётчик складывает эти категории без повторного учёта ошибки стадии.
Runner принимает уже созданный run через интерфейс
`run-canonical-refresh.sh <pipeline_id> <run_id>` и завершает его рассчитанным
terminal outcome.

Контракт проверен на NHL и football fixture. Football fixture использует общий
readiness producer с отдельной 14-дневной policy и рынком `winner/1x2`: свежие
prediction и odds `examplebook` дают положительную готовность, а событие за
пределами окна не входит в eligible denominator. Production football pipeline
или меню не добавлялись.

## Исправления после review

- Перенесена оценка readiness на post-publication clock; один `as-of` используется
  для eligibility и readiness, а его provenance хранится в summary.
- Разведены `stage_errors` и `event_errors`; odds acquisition failure не
  дублируется как событие.
- Валидный пустой ответ odds с пропущенными eligible событиями даёт
  `partial_success`, не объявляя источник недоступным. Last-success odds
  определяется только сохранёнными observation timestamps.
- Last-success запросы ограничены временем фиксации run и соответствующим
  компонентом/турниром; неподтверждённые timestamps остаются неизвестными.
- Football fixture получил позитивный prediction+odds кейс и событие вне
  policy window, чтобы тест проверял принятие совместимых 1X2 данных.

## Проверки

| Проверка | Результат |
|---|---|
| `uv run pytest -q tests/test_canonical_bootstrap.py tests/test_canonical_full_refresh.py tests/test_data_cycle_lifecycle.py tests/test_data_cycle_runner_contract.py` | 51 passed, 3 предупреждения Pandera о deprecation |
| `uv run ruff check sports_forecast/deploy/canonical_bootstrap.py sports_forecast/orchestration/canonical_full_refresh.py sports_forecast/service/data_cycle_history.py sports_forecast/service/db/repository.py sports_forecast/orchestration/data_cycle_cli.py tests/test_canonical_bootstrap.py tests/test_canonical_full_refresh.py tests/test_data_cycle_lifecycle.py tests/test_data_cycle_runner_contract.py` | All checks passed |
| `uv run pre-commit run mypy --files sports_forecast/deploy/canonical_bootstrap.py sports_forecast/orchestration/canonical_full_refresh.py sports_forecast/service/data_cycle_history.py sports_forecast/service/db/repository.py sports_forecast/orchestration/data_cycle_cli.py` | Passed |
| `bash -n deploy/systemd/run-canonical-refresh.sh` | Passed |
| `git diff --check` | Passed |
| Независимое review TASK10, включая повторную проверку позитивного football fixture | Пройдено; findings закрыты |
| Совмещённый прогон TASK-025-4/10 и затронутых topology/migration тестов | 85 passed, 2 PostgreSQL integration tests skipped без переменных подключения |
| `uv run pre-commit run --all-files` на совмещённом diff | все hooks прошли после исправления типизации control API |
| `make lint`, `make docs` на совмещённом diff | прошли; Sphinx завершился с 24 предупреждениями |

## Остаточные gates

- Здесь не зафиксирован полный CI; `make lint`, полный `make test` и release CI
  должны быть проверены на совмещённом diff перед production выпуском.
- Production backup/restore и rollback evidence, migration/bootstrap и
  привилегированный read-only preflight остаются Operations gates.
- Фактический runtime cycle, timer/dispatcher heartbeat и ежедневная работа NHL
  должны быть подтверждены на production после подготовки релиза.
- Football проверен как контрактный fixture; фактическое подключение футбольных
  турниров в production остаётся будущим scope.
