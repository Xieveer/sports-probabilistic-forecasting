# TASK-040-1 — Каталог и входные данные клубного пула

> **Статус:** реализация, локальные проверки и независимое review завершены
> **Задача:** [TASK-040-1](../../backlog/tasks/TASK-040-1-club-pool-catalog.md)
> **Требование:** [REQ-040](../../product/requirements/REQ-040-club-football-platform-e2e.md)

## Изменено

- `conf/portfolio/default.yaml` задаёт один `football_top_leagues` pool с одним
  `winner_1x2` для девяти соревнований из одного source-конфига. Deployment
  profile не добавлен: текущий Airflow создаёт heavy-refresh target из каждого
  такого профиля, что запустило бы незавершённый локальный сценарий по расписанию.
  В source и tournament defaults явно
  указан `_self_` без изменения порядка композиции.
- `sports_forecast/validation/club_pool_coverage.py` проверяет точное совпадение
  состава CSV с whitelist, непустые ключи и уникальность `match_id`; выводит
  количество строк, завершённых матчей, покрытие тройки historical odds и границы
  дат по каждому коду, а также SHA-256 входного файла.
- Тесты проверяют единый pool без scheduled target, пробел в odds,
  отсутствующий/лишний код и повторный ID.

## Фактическая проверка

- Red: `pytest -q tests/test_club_pool_catalog.py` завершился `KeyError:
  football_top_leagues`; `pytest -q tests/test_club_pool_coverage.py` не смог
  импортировать отсутствующий модуль.
- Green: 31 тест каталога, coverage, model pool, оркестрации и Smart Tables provider
  прошёл; `ruff check` затронутых Python-файлов и `git diff --check` прошли.
- Reviewer отдельно проверил updated diff и не нашёл P0/P1/P2; его целевой
  запуск `uv run pytest -q tests/test_club_pool_catalog.py
  tests/test_club_pool_coverage.py tests/test_portfolio_orchestration.py
  tests/integration/test_portfolio_refresh_dag.py` завершился `9 passed`.
- Реальный локальный CSV: SHA-256
  `799cd61405e8d9ffb7aee8ac078fcbce9abefda3c2c3450c26a2c22b21407975`,
  31 625 строк, все завершены. Coverage по соревнованиям:

| Код | Матчи | Полная тройка odds |
| --- | ---: | ---: |
| ENG1 | 4 138 | 4 138 |
| SPA1 | 4 185 | 4 185 |
| GER1 | 3 392 | 3 391 |
| ITA1 | 4 212 | 4 208 |
| FRA1 | 3 811 | 3 810 |
| RUS1 | 2 694 | 2 690 |
| RUS2 | 3 144 | 3 064 |
| UCL | 2 409 | 2 312 |
| UEL | 3 640 | 3 355 |

## Не изменено и остаточные риски

Модели, materialize, API, бот, production pointer и расписание не изменялись.
Historical odds по-прежнему не имеют доказанного as-of времени. Наличие всех
девяти кодов в истории не подтверждает текущий upcoming coverage. Read-only
запрос Smart Tables `nearest-matches` превысил 60 секунд; отдельный короткий
TLS probe также истёк по таймауту. Source CSV остался неизменным.
