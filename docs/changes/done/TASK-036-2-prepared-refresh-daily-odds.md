# TASK-036-2 — Сбор текущих коэффициентов после проверки архива

> **Задача:** [TASK-036-2](../../backlog/tasks/TASK-036-2-prepared-refresh-daily-odds.md)

## Результат

Подготовленный source-first refresh проверяет архив через `load_prepared_input`
до выполнения odds stage. При включённом `data_odds_enabled` запускается
существующий ограниченный NHL future odds batch один раз; результат отражается
в `data_odds`, а acquisition attempt сохраняет сама реализация batch. При
выключенном флаге сохраняется прежний пропуск и запрос к провайдеру не
выполняется.

## Проверки

- Red: новый тест `test_prepared_worker_fetches_daily_odds_after_archive_validation`
  упал до исправления, потому что после валидации архива provider не вызывался.
- Green: тот же тест прошёл и подтвердил порядок `archive_verified` перед
  `odds_requested`, один вызов и сохранённые stage counts.
- `../../.venv/bin/pytest -q tests/test_canonical_run_input.py tests/test_canonical_full_refresh.py` — 20 passed.

## Остаточные gates

Независимый review, CI и реальный production цикл с ненулевым числом
`odds_observations` остаются release gates EPIC-036. Этот локальный тест не
доказывает доступность текущей линии у внешнего провайдера или её выдачу в API
и Telegram.
