# TASK-004-2 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-08
> **Задача:** [TASK-004-2](../../backlog/tasks/TASK-004-2-odds-api-key-ring.md)

## Реализованный результат

The Odds API client выбирает ключи `ODDS_API_KEY_FREE`, `ODDS_API_KEY_20K` и
`ODDS_API_KEY_100K` в заданном порядке. `429` повторяет запрос на следующем
tier, а успешный ответ с `x-requests-remaining: 0` сохраняется и переключает
следующий запрос. Технические и авторизационные ошибки не расходуют платный
ключ. Старый `ODDS_API_KEY` работает, если новые переменные не заданы.

API, post-refresh digest и Airflow распознают любую поддерживаемую переменную;
`.env.example` содержит все три пустых ключа и порядок их использования.

## Доказательство TDD

- **Red:** `uv run pytest tests/test_odds_client.py -q` — 3 failed: клиент
  требовал только legacy `ODDS_API_KEY`.
- **Green:** `uv run pytest tests/test_odds_client.py -q` — 7 passed.
- **Refactor:** HTTP-параметры передаются отдельным snapshot; лимит реальных
  запросов проверяется также при повторе после failover.

## Фактически выполненные проверки

| Команда | Результат |
|---|---|
| `uv run pytest tests/test_odds_client.py tests/test_live_odds_enrichment.py tests/test_post_refresh_digest_cli.py -q` | 18 passed, 1 warning |
| `make lint` | Успешно |
| `uv run pre-commit run mypy --files ...` | Успешно |
| `git diff --check` | Успешно |

## Остаточные риски

- Реальные ключи и внешний API не запускались; их проверит TASK-004-4 в secret environment.
- `401/403` намеренно не вызывают failover: право тарифа не считается доказательством исчерпания квоты.
