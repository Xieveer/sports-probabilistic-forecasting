# TASK-025-35 — Отчёт Developer: first-rollout NHL fixture

> **Статус:** локальное исправление и независимое review; CI и новый tag pipeline ожидаются.
> **Дата:** 2026-10-01
> **Задача:** [TASK-025-35](../../backlog/tasks/TASK-025-35-first-rollout-nhl-game-type-fixture.md)

## Результат и доказательство

В `build_first_rollout_fixtures.py` `game_type` заменён с `R` на `regular`,
который выдаёт NHL assembler. Новый тест использует те же 12 строк fixture
и проверяет, что NHL clean сохраняет их все в модельном входе.

- Red: `uv run pytest -q tests/test_production_first_rollout_contract.py -k fixture_reaches_nhl_model_input --no-cov` — 0 вместо 12 строк.
- Green: после исправления тот же тест прошёл.
- Production v1.2.12, active profile/model и оба NHL timer не менялись.

## Проверки и остаточный gate

| Проверка | Результат |
|---|---|
| `uv run pytest -q tests/test_production_first_rollout_contract.py -k fixture_reaches_nhl_model_input --no-cov` | 1 passed после исходного red |
| `make lint` | passed |
| `make test-unit` | 1 260 passed, 13 deselected, 40 warnings |
| `make production-check`, `git diff --check` | passed |
| Ruff check/format затронутых fixture и теста | passed |
| Независимый Reviewer | P0–P2 не найдены; commit gate ожидается |

Tag v1.2.13 остаётся неизменным и не может стать основанием deployment.
Следующий выпуск имеет версию v1.2.14 и требует нового exact model wrapper.
