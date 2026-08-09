# TASK-002-1 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-07
> **Задача:** [TASK-002-1](../../backlog/tasks/TASK-002-1-nhl-quality-gate.md)

## Реализованный результат

Добавлен tournament-neutral quality gate для нормализованных строк локального
`source.csv` и сохранённого снимка расписания. Он подтверждает наличие ровно
одной строки каждого матча из окна профиля, а также наличие финального статуса
и обязательных полей у завершённых матчей после переданного watermark. Ошибки
содержат только счётчики и имена полей, не значения строк.

NHL-профиль задаёт окно 48 часов, завершённое состояние `OFF`, признак
`match_is_end` и фактические поля `source.csv`: `home_score_ft`,
`away_score_ft`, `match_end`.
Source-конфиг включает этот профиль, а provider атомарно сохраняет рядом с
`source.csv` профильный snapshot расписания. В нём остаются только `id`,
`datetime` и `game_state`, без исходных HTTP-ответов. Подключение gate к heavy
DAG/factory остаётся TASK-002-3.

Critical follow-up закрывает границу watermark включительно, поэтому completed
матч с тем же timestamp также проверяется. Provider расширяет source-запрос до
`refresh + schedule_window_hours` из профиля и сохраняет отдельный минимальный
metadata-маркер `covered_until`; gate отклоняет snapshot без такого покрытия.
Каждое обязательное итоговое поле имеет профильное правило типа и домена;
NHL-профиль допускает неотрицательные целые scores до 99 и `REG`/`OT`/`SO` для
`match_end`.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/validation/tournament_quality.py` | Чистый контракт и проверка полноты source-данных |
| `sports_forecast/config/loaders.py` | Загрузчик profile-driven правил типов/доменов и coverage |
| `sports_forecast/data/providers/nhl/assembler.py`, `sports_forecast/data/providers/nhl/provider.py` | Нормализация, запрос future window и сохранение snapshot после source refresh |
| `conf/source/nhl.yaml`, `conf/quality_gate/nhl.yaml` | Связь source с NHL-профилем и правила/имя snapshot |
| `tests/test_tournament_quality_gate.py`, `tests/test_tournament_quality_snapshot.py`, `tests/test_nhl_provider.py` | Unit-тесты gate, roundtrip snapshot и сохранения provider |
| `docs/backlog/tasks/TASK-002-1-nhl-quality-gate.md` | Статус и handoff к DAG-интеграции |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_tournament_quality_gate.py -q` — `ModuleNotFoundError` для
  отсутствующего `sports_forecast.validation.tournament_quality`.
- **Red (профиль):** `uv run pytest tests/test_tournament_quality_gate.py -q` — `ImportError` для
  отсутствующего `load_tournament_quality_gate_config`.
- **Red (дубль snapshot):** `uv run pytest tests/test_tournament_quality_gate.py::test_quality_gate_rejects_duplicate_match_in_schedule_snapshot -q` — gate ошибочно принимал дублированное расписание.
- **Green:** `uv run pytest tests/test_tournament_quality_gate.py tests/test_config_validation.py -q` —
  31 passed.
- **Регрессия профиля:** `uv run pytest tests/test_tournament_quality_gate.py::test_loads_nhl_quality_gate_profile -q` —
  ожидание фактических полей `source.csv` сначала упало на прежних `home_points`/`away_points`,
  после исправления профиля прошло в общем целевом наборе.
- **Red (runtime snapshot):** `uv run pytest tests/test_tournament_quality_snapshot.py -q` —
  отсутствовал API сохранения/загрузки snapshot; отдельный provider-тест также подтвердил
  отсутствие файла до подключения.
- **Green (runtime snapshot):** `uv run pytest tests/test_tournament_quality_snapshot.py tests/test_tournament_quality_gate.py::test_loads_nhl_quality_gate_profile tests/test_nhl_provider.py::test_nhl_provider_saves_configured_quality_schedule_snapshot -q` — 3 passed.
- **Red (critical):** `uv run pytest tests/test_tournament_quality_gate.py::test_quality_gate_checks_completed_match_at_watermark_timestamp tests/test_tournament_quality_gate.py::test_quality_gate_rejects_non_integer_completed_score -q` — 2 failed: запись на границе watermark и текстовый score ошибочно принимались.
- **Green (critical):** `uv run pytest tests/test_tournament_quality_gate.py tests/test_tournament_quality_snapshot.py tests/test_tournament_quality_gate_runtime.py tests/test_nhl_provider.py -q` — 34 passed.
- **Refactor:** загрузчик использует отложенный импорт модели gate; это устранило подтверждённый
  циклический импорт `config.loaders → validation → providers → config.loaders`.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_tournament_quality_gate.py tests/test_config_validation.py -q` | 31 passed, 1 warning |
| `uv run ruff check sports_forecast/validation/tournament_quality.py sports_forecast/config/loaders.py tests/test_tournament_quality_gate.py` | Успешно |
| `make test-unit` | 737 passed, 8 deselected, 29 warnings |
| `make lint` | Успешно |
| `uv run mypy sports_forecast/validation/tournament_quality.py sports_forecast/config/loaders.py` | Не выполнено: `mypy` не установлен в окружении |
| `uv run pytest tests/test_tournament_quality_snapshot.py tests/test_tournament_quality_gate.py tests/test_nhl_provider.py tests/test_nhl_incremental.py tests/test_source_providers.py -q` | 41 passed, 1 warning |
| `make test-unit` (после runtime snapshot) | 746 passed, 8 deselected, 29 warnings |
| `make lint` (после runtime snapshot) | Успешно |
| `uv run pytest tests/test_tournament_quality_gate.py tests/test_tournament_quality_snapshot.py tests/test_tournament_quality_gate_runtime.py tests/test_nhl_provider.py -q` | 34 passed, 1 warning |
| `make test-unit` (после critical follow-up) | 760 passed, 8 deselected, 29 warnings |
| `make lint` (после critical follow-up) | Успешно |

## Документация, review и follow-up

- Документация: добавлены профиль и этот отчёт; публичный пользовательский контракт не менялся.
- Review / security: не выполнялось.
- Follow-up: TASK-002-3 загружает snapshot/coverage и подключает gate перед initial digest в DAG factory.

## Остаточные риски

- Gate требует, чтобы TASK-002-3 передал сохранённые snapshot/coverage и watermark предыдущего
  завершённого матча; DAG wiring ещё не реализован в этом срезе.
- Статическая проверка mypy не выполнена, так как бинарник отсутствует в текущем окружении.
