# TASK-025-6 — Отчёт: будущие котировки NHL

> **Статус:** Developer handoff; независимый review ожидается
> **Дата:** 2026-09-26
> **Задача:** [TASK-025-6](../../backlog/tasks/TASK-025-6-future-odds.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат

Добавлен календарный future-odds batch adapter для NHL на The Odds API v4:
один bounded запрос `icehockey_nhl/odds` на запуск, Pinnacle, `h2h`, decimal,
UTC kickoff window. Transport retries и redirects отключены, чтобы cap одного
запроса соответствовал одному HTTP GET; для одиночного события `To` расширяется
на одну секунду для валидного API range. Provider timestamp отклоняется, если
опережает retrieval более чем на 5 минут, и readiness считает будущий timestamp
stale до его наступления. Линия принимается только при точном
соответствии home/away исходов и однозначном событии по нормализованным командам
и точному UTC kickoff. Повторные provider events для одной identity и дубли
Pinnacle/h2h записей отклоняются как ambiguous.
Локальное время получения сохраняется отдельно от provider timestamp; для него
сохраняется provenance `market.last_update` либо допустимый fallback
`bookmaker.last_update` единственного запрошенного рынка.

Observation хранится отдельно от результата acquisition attempt. Ошибки и quota
snapshot сохраняются безопасным кодом и не включают сырой ответ источника. Отсутствие
линии после успешного ответа остаётся `missing`. Calendar readiness выдаёт
`odds.failed` только для eligible события в окне неуспешной попытки после deadline,
если более свежий применимый success не очистил failure. Старое observation не
удаляется. Batch подключён к Data Cycle как отдельная odds stage. При смене
kickoff/event identity upsert использует время retrieval для выбора версии;
внутри прежней identity порядок остаётся по provider timestamp.

Миграция `0013_future_odds_acquisition` добавляет таблицу попыток и provider
provenance для observations; выданы минимальные runtime grants. Футбольный
production adapter не добавлялся.

## Изменённые границы

- Odds API client и orchestration adapter `sports_forecast.orchestration.future_odds`;
- Data Cycle wiring и calendar odds readiness projection/API;
- SQLAlchemy модели, migration и database grants;
- unit/integration tests, source documentation и architecture docs.

Production migration, внешние запросы к Odds API, секреты и deployment не
использовались.

## Red → Green → Refactor

- **Red:** первый запуск нового adapter test завершился ожидаемым отсутствием
  `sports_forecast.orchestration.future_odds`.
- **Green:** добавлены parser, source client, batch persistence, readiness semantics
  и stage wiring с фиксированными fake responses.
- **Refactor:** legacy OddsStore bridge сохраняет retrieval отдельно от provider
  timestamp; данные попытки идемпотентны по `(run_id, provider)` и без raw payload.

## Проверки

- `uv run pytest -q tests/test_future_odds_batch.py tests/test_odds_client.py tests/test_event_readiness.py tests/test_calendar_api.py tests/test_canonical_full_refresh.py tests/test_data_cycle_lifecycle.py tests/test_data_cycle_runner_contract.py tests/test_source_refresh_odds.py tests/test_readiness_and_migrations.py tests/test_bot_calendar_integration.py` — 81 passed, 3 warnings после устранения findings.
- `make lint` — passed.
- `make docs` — completed; emitted 24 existing warnings (including missing `_static` directory and duplicate Sphinx descriptions).
- `uv run alembic heads` — единственная голова `0013_future_odds_acquisition`.
- `git diff --check` — passed.

## Остаточные риски

- Фактический NHL odds coverage, production key/quota и поведение привилегированной
  runtime DB роли ещё требуют Operations preflight; в этом срезе использовались
  только fake provider responses.
- Запрошенный поставщиком Pinnacle `h2h` для `winner_withOT` подтверждается структурой
  исходов, но полнота/доступность линии зависит от provider coverage.
- Независимый Reviewer выявил и проверил исправления трёх finding: положительное
  окно для одного события, identity-aware upsert после переноса и защита от
  будущего provider timestamp. Повторное review: новых P0–P2 нет, 51 целевой
  тест, настроенный mypy hook и `git diff --check` прошли у Reviewer.
