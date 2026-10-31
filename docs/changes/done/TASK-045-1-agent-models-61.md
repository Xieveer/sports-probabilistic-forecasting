# TASK-045-1 — отчёт о карте моделей агентов

> **Статус задачи:** done
> **Дата:** 2026-10-31
> **Задача:** [TASK-045-1](../../backlog/tasks/TASK-045-1-agent-models-61.md)

## Реализованный результат

Sol-профили обновлены до `gpt-6.1-sol`. Business Analyst и Developer сохранили
`gpt-6-luna`, Architect сохранил `gpt-6-astra`; уровни reasoning не менялись.

## Изменённые границы

`.codex/`, валидатор AI-слоя, его тест и текущая карта моделей в документации.

## Доказательство TDD

- **Red:** `uv run pytest tests/test_ai_layer_validation.py::test_agent_model_contract_assigns_fixed_gpt_6_1_models tests/test_ai_layer_validation.py::test_agent_model_contract_rejects_legacy_and_astra_outside_architect -q` — два ожидаемых отказа до обновления валидатора.
- **Green:** `uv run pytest tests/test_ai_layer_validation.py -q` — 12 passed после уточнения владельца и правки карты.
- **Refactor:** корневой профиль сверяется с общей константой `DEFAULT_AGENT_MODEL`.

## Фактически выполненные проверки

- `uv run pytest tests/test_ai_layer_validation.py -q` — 12 passed.
- `make ai-validate` — успешно.
- `uv run ruff check scripts/validate_ai_layer.py tests/test_ai_layer_validation.py` — успешно.
- `uv run ruff format --check scripts/validate_ai_layer.py tests/test_ai_layer_validation.py` — успешно после устранения замечания review.
- `git diff --check` — успешно.

## Документация, review и follow-up

- Документация: [REQ-045](../../product/requirements/REQ-045-agent-models-61.md), [карта моделей](../../development/ai-agents-and-skills.md).
- Review / security: независимое TASK и полное EPIC review без блокирующих findings;
  проверены карта моделей, validator, тесты и документация. Sandbox и права не менялись,
  достижимых новых security-рисков в этом diff не обнаружено.
- Commit/push: ожидает Reviewer.
- Follow-up: нет.

## Остаточные риски

Фактическая доступность модели в пользовательском аккаунте и применение обновлённой
конфигурации в уже открытых сессиях не подтверждаются локальным тестом.
