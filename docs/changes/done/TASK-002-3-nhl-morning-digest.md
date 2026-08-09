# TASK-002-3 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-07
> **Задача:** [TASK-002-3](../../backlog/tasks/TASK-002-3-nhl-morning-digest.md)

## Реализованный результат

Добавлен конфигурационный notification-профиль и tournament-neutral factory heavy
Airflow DAG. NHL теперь задаётся только YAML: heavy path запускается по cron
``0 10 * * *`` в ``Europe/Moscow``, с окном 48 часов, lock, pool и ограничением
параллелизма из профиля. Factory строит цепочку
``capture_quality_watermark → refresh → validate → quality_gate → initial_digest``; отдельная ветка с
``TriggerRule.ONE_FAILED`` отправляет краткий текст только administrator list.

Перед refresh сохраняется run-scoped watermark последнего локально завершённого
матча; gate после refresh загружает профильный нормализованный schedule snapshot
и использует именно этот watermark, а не более новое состояние `source.csv`.
Initial digest рассылает одинаковый текст каждому allowlist chat ID, не ждёт
коэффициентов, и записывает baseline валидных переданных линий через контракт
TASK-002-2. Legacy hardcoded DAG-ветка заменена discovery-модулем, который
создаёт DAG только через factory и включённые профили. TASK-002-4 poll не
реализовывался.

## Закрытие reviewer P1 (2026-08-08)

В generic heavy DAG восстановлен общий шаг ``run_validation`` через shared
``bash_run_validation``. Он находится строго между ``refresh`` и tournament
quality gate, поэтому initial digest по-прежнему возможен только после общего и
профильного контроля качества.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `conf/notification/nhl.yaml` | NHL-профиль heavy path |
| `sports_forecast/config/loaders.py` | Загрузка включённых notification-профилей |
| `sports_forecast/orchestration/notification_profiles.py`, `notification_dag.py` | Типизированный профиль и нейтральный DAG contract |
| `airflow/dags/notification_dag_factory.py` | Runtime factory heavy DAG и failure branch |
| `sports_forecast/orchestration/initial_notification.py` | Initial fan-out, baseline и admin-only адаптер |
| `sports_forecast/orchestration/tournament_quality_watermark.py`, `*_cli.py` | Run-scoped watermark, загрузка snapshot и узкие CLI-границы задач Airflow |
| `airflow/docker-compose.airflow.yml`, `.env.example` | Проброс admin list без секрета в коде |
| `README.md`, `docs/source/nhl_local_operations.rst` | Актуальный operational contract |
| `tests/test_notification_*.py`, `tests/test_initial_notification.py` | Config, factory, fan-out, baseline и failure isolation |
| `tests/test_tournament_quality_gate_runtime.py`, `tests/test_tournament_quality_watermark.py` | Snapshot/watermark runtime contract |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_initial_notification.py::test_initial_digest_fans_out_to_all_allowlist_recipients_without_odds -q` — `ModuleNotFoundError` для отсутствующего `initial_notification`.
- **Green:** та же команда — `1 passed` после минимального initial fan-out.
- **Red:** `uv run pytest tests/test_notification_profiles.py -q` — `ImportError` для отсутствующего `load_notification_profiles`.
- **Green:** та же команда — `2 passed` после YAML-профиля и loader-а.
- **Red:** `uv run pytest tests/test_notification_dag_factory.py -q` — `ModuleNotFoundError` для отсутствующего `notification_dag`.
- **Green:** та же команда — `1 passed` после нейтрального DAG spec.
- **Refactor:** legacy DAG заменён profile-driven discovery; source-level integration test проверяет factory, порядок gate и admin failure branch.
- **Follow-up TDD Red:** `uv run pytest tests/test_tournament_quality_gate_runtime.py -q` — отсутствовал callable runtime gate для загрузки profile snapshot.
- **Follow-up TDD Green:** `uv run pytest tests/test_tournament_quality_watermark.py tests/test_tournament_quality_gate_runtime.py tests/integration/test_orchestration_contour.py -q` — 10 passed; фиксирует pre-refresh watermark и его передачу после refresh.

## Фактически выполненные проверки

| Команда | Результат |
|---|---|
| `uv run pytest tests/test_notification_profiles.py tests/test_notification_dag_factory.py tests/test_initial_notification.py tests/test_notification_failure.py tests/test_notification_state.py tests/test_tournament_quality_gate.py tests/integration/test_orchestration_contour.py -q` | 27 passed, 1 warning |
| `make test-unit` | 744 passed, 8 deselected, 29 warnings |
| `make lint` | успешно |
| `git diff --check` | успешно |
| `uv run pytest tests/test_tournament_quality_watermark.py tests/test_tournament_quality_gate_runtime.py tests/test_tournament_quality_snapshot.py tests/test_tournament_quality_gate.py tests/test_nhl_provider.py tests/test_notification_dag_factory.py tests/integration/test_orchestration_contour.py -q` | 40 passed, 1 warning |
| `uv run pytest tests/test_notification_dag_factory.py tests/test_notification_profiles.py tests/test_initial_notification.py tests/test_odds_poll_notification.py tests/test_live_nhl_pinnacle.py tests/integration/test_orchestration_contour.py::test_notification_dag_factory_source_contract -q` | 27 passed, 1 warning |
| `make test-unit` | 771 passed, 8 deselected, 29 warnings |
| `make lint` | успешно |

## Неизменённое и риски

- TASK-002-4: 15-минутный poll, delta fan-out и poll errors не добавлялись.
- Не запускались Airflow scheduler, Telegram HTTP и production deployment; тесты изолируют HTTP adapter mock-ом.
- Полный `make test-unit` после follow-up запускался, но был красным только из-за параллельного TASK-002-4: его новые тесты импортируют ещё не созданный `odds_poll_notification` (5 `ModuleNotFoundError`). Этот срез poll не изменял.
- Initial CLI пока не запрашивает live odds: digest корректно отправляется без них, а baseline непустых live линий будет наполнен poll/integration следующим срезом.
