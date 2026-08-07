# TASK-002-4 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-07
> **Задача:** [TASK-002-4](../../backlog/tasks/TASK-002-4-nhl-odds-poll.md)

## Реализованный результат

Добавлен лёгкий profile-driven Airflow DAG poll коэффициентов. Он читает только
materialized прогнозы в окне профиля, при их наличии делает ровно один прямой
batch-вызов Pinnacle h2h и сравнивает снимки с persisted notification state.
Новые и изменившиеся валидные линии формируют один aggregate digest на logical
cycle и fan-out всем allowlist-получателям. Пустое окно, отсутствие изменения и
начавшиеся матчи завершаются без пользовательского сообщения.

NHL-параметры находятся только в `conf/notification/nhl.yaml`: окно 48 часов,
h2h adapter, параметры букмекера/спорта и cron `*/15 * * * *`. Лёгкий DAG имеет отдельные pool, retry,
timeout и `max_active_runs=1`; он не запускает source refresh, ingest, feature
generation либо materialization. Его failure branch отправляет краткий текст
только administrator list.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/orchestration/odds_poll_notification.py` | Tournament-neutral poll, aggregate delta и delivery ledger |
| `sports_forecast/orchestration/live_odds_adapter.py`, `odds_poll_cli.py` | Один прямой batch Pinnacle adapter и CLI Airflow без FastAPI |
| `sports_forecast/orchestration/notification_profiles.py`, `notification_dag.py` | Poll-поля YAML-профиля и проверяемый poll DAG spec |
| `airflow/dags/notification_dag_factory.py` | Лёгкий DAG `poll_odds → notify_failure` с admin-only failure branch |
| `conf/notification/nhl.yaml`, `sports_forecast/config/loaders.py` | NHL poll schedule/provider/limits и загрузка профиля |
| `tests/test_odds_poll_notification.py`, `tests/test_notification_*`, `tests/integration/test_orchestration_contour.py` | Contract-, adapter-, config- и source-level DAG-проверки |
| `README.md`, `docs/source/nhl_local_operations.rst` | Операционный контракт отдельного poll DAG |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_odds_poll_notification.py -q` — 5 failed с
  ожидаемым `ModuleNotFoundError` для отсутствующего
  `sports_forecast.orchestration.odds_poll_notification`.
- **Green (pure orchestration):** `uv run pytest tests/test_odds_poll_notification.py tests/test_notification_state.py -q` — 9 passed.
- **Green (adapter):** после добавления direct batch adapter целевой набор стал
  `10 passed`; тест фиксирует единственный вызов provider-а со всеми матчами.
- **Red (profile/DAG):** `uv run pytest tests/test_notification_dag_factory.py tests/test_notification_profiles.py -q` — import error отсутствующего `build_poll_dag_spec`.
- **Green (wiring):** `uv run pytest tests/test_notification_dag_factory.py tests/test_notification_profiles.py tests/test_odds_poll_notification.py tests/test_initial_notification.py tests/test_notification_failure.py tests/test_notification_state.py tests/integration/test_orchestration_contour.py -q` — 26 passed, 1 warning.
- **Refactor:** poll-значения вынесены в типизированный profile/spec; direct adapter не использует HTTP API и не включает тяжёлый pipeline.

## Фактически выполненные проверки

| Команда | Результат |
|---|---|
| Целевой pytest из раздела TDD | 26 passed, 1 warning |
| `uv run ruff check …` и `uv run ruff format --check …` для затронутых файлов | Успешно |
| `make test-unit` | 755 passed, 8 deselected, 29 warnings |
| `make lint` | Успешно |
| `make docs` | Успешно, 38 существующих предупреждений Sphinx |
| `git diff --check` | Успешно |

## Закрытие reviewer P1 (2026-08-08)

Poll и initial-digest CLI выбирают adapter через registry по
``live_odds_adapter`` notification-профиля. YAML также передаёт имя bookmaker
config, sport key, bookmaker key и опциональный team registry; CLI больше не
содержит runtime-проверки NHL/Pinnacle. Нейтральный runtime-contract test
регистрирует ``demo_adapter`` и подтверждает передачу этих параметров без
зависимости от tournament slug.

| Команда | Результат |
|---|---|
| `uv run pytest tests/test_notification_dag_factory.py tests/test_notification_profiles.py tests/test_initial_notification.py tests/test_odds_poll_notification.py tests/test_live_nhl_pinnacle.py tests/integration/test_orchestration_contour.py::test_notification_dag_factory_source_contract -q` | 27 passed, 1 warning |
| `make test-unit` | 771 passed, 8 deselected, 29 warnings |
| `make lint` | успешно |

## Неизменённое и остаточные риски

- Не изменялись source snapshot/provider/gate, initial heavy path и публичный FastAPI.
- Airflow scheduler, реальный Telegram HTTP и The Odds API не запускались: внешние границы заменены test doubles.
- Delivery ledger снижает дубли при retry, но сохраняется зафиксированный в ADR-002 риск дубликата при аварии после принятия Telegram и до commit БД.
- Реальный production PostgreSQL требует согласованной миграции additive notification-таблиц перед rollout; deployment не выполнялся.
