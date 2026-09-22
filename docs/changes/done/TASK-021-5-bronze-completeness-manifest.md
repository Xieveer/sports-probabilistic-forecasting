# TASK-021-5 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-09-12
> **Задача:** [TASK-021-5](../../backlog/tasks/TASK-021-5-bronze-completeness-manifest.md)

## Результат

Добавлены typed manifest и read-only scanner bronze Smart Tables. Профиль
`winner_baseline/v1` считает required `card.json` и `stat_all.json`; остальные шесть
компонентов optional. Manifest хранит только metadata файлов и безопасный тип ошибки,
без API payload.

Добавлен CLI `scripts/smart_tables_bronze_coverage.py`: он печатает coverage и
списки `train_ready`, missing required и optional-only матчей, а `--write-manifest`
сохраняет отдельный JSON-снимок. `fetch_match_bronze(..., profile=..., include_optional=False)`
даёт opt-in targeted resume: валидные cached required-файлы не запрашиваются повторно,
а повреждённые/отсутствующие допускают загрузку. `SmartTablesDataAssembler` подключает
его для массового запуска через `SF_SMART_TABLES_BRONZE_PROFILE=winner_baseline_required`:
новые матчи получают только `card.json` и `stat_all.json`. Default `full` не менялся.

## Фактический coverage

После остановки backfill выполнен read-only scan
`data/source/football_top_leagues/raw`: 663 матча, `train_ready_coverage=1.0`,
`card.json=1.0`, `stat_all.json=1.0`, `stat_first.json=1.0`.
`stat_second.json`, `chart_first.json`, `chart_second.json` и `similar.json` имеют
coverage `0.9984917043740573`; единственный optional-only матч — `432714`.
`missing_required_match_ids` пуст. Измерение «до» отсутствует, так как manifest —
результат этой задачи.

## Проверки

- Red: `uv run pytest tests/test_smart_tables_bronze_manifest.py -q` — ожидаемый
  `ModuleNotFoundError` до реализации scanner.
- `uv run pytest tests/test_smart_tables_bronze_manifest.py tests/test_smart_tables_provider.py -q` — 24 passed.
- `uv run ruff check sports_forecast/data/providers/smart_tables/fetch.py sports_forecast/data/providers/smart_tables/bronze_manifest.py scripts/smart_tables_bronze_coverage.py tests/test_smart_tables_bronze_manifest.py` — успешно.
- `uv run pre-commit run mypy --files sports_forecast/data/providers/smart_tables/fetch.py sports_forecast/data/providers/smart_tables/bronze_manifest.py scripts/smart_tables_bronze_coverage.py tests/test_smart_tables_bronze_manifest.py` — успешно.
- `uv run pre-commit run mypy --all-files` — успешно.
- `make lint` — успешно.
- `make docs` — успешно, 1 существующее предупреждение Sphinx; новое руководство собрано.
- `uv run python scripts/smart_tables_bronze_coverage.py --raw-root data/source/football_top_leagues/raw --write-manifest data/source/football_top_leagues/bronze-manifest.json` — успешно, сеть не вызывалась.

## Документация и остаточные риски

Добавлено руководство [Smart Tables bronze](../../source/smart_tables_bronze.rst).
Сгенерированный manifest остаётся локальным data-artifact (1.3 MiB, игнорируется Git).
Optional-части матча `432714` намеренно не докачивались: это потребует отдельного
явного запуска opt-in resume и сетевого доступа.

## Review

### P1 — исправлено: неуспешная сетевая попытка

В opt-in profile исключение `SmartTablesApiClient.get_json()` теперь атомарно записывает
рядом с match-каталогом `.bronze_attempts.json` без payload. Scanner объединяет metadata
с файловым состоянием: timeout/HTTP failure отображается как
`last_attempt_status="failed"`, `error_kind="request_failed"`, а не `missing`.
Добавлен red/green тест этого сценария.

Независимый review 2026-09-12: `uv run pytest tests/test_smart_tables_bronze_manifest.py tests/test_smart_tables_provider.py -q` — 24 passed;
`uv run pre-commit run mypy --files sports_forecast/data/providers/smart_tables/assembler.py sports_forecast/data/providers/smart_tables/fetch.py sports_forecast/data/providers/smart_tables/bronze_manifest.py scripts/smart_tables_bronze_coverage.py tests/test_smart_tables_bronze_manifest.py` — успешно.

После исправления: тот же pytest suite — 25 passed; ruff и mypy по изменённым файлам — успешно.

## Зафиксированная докачка

Основной ingest был остановлен с checkpoint: в нём 650 уникальных `match_id`, тогда
как manifest содержит 663 bronze-каталога. Полный pool составляет 31 950 матчей; он
запускается только с `SF_SMART_TABLES_BRONZE_PROFILE=winner_baseline_required`, чтобы
скачивать лишь required-набор. После его финализации остаётся отдельная optional-докачка
`match_id=432714`: `stat_second.json`, `chart_first.json`, `chart_second.json`,
`similar.json`. Она не влияет на train-ready coverage и не запускается автоматически,
чтобы не менять default backfill.
