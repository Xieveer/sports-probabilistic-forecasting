# TASK-036-4 — Runtime strict switch: отчёт Developer

## Результат

`registry_event_reader_enabled()` читает явный
`SF_REGISTRY_EVENT_READER_ENABLED=true|false` и отклоняет другие значения.
При отсутствии переменной прежний YAML определяет значение. Production
Compose передаёт один флаг в API, Telegram bot, source-acquirer и Worker;
значение по умолчанию `false`. На VPS API/бот и systemd Data Cycle используют
один актуальный `nhl.env`; его значение проверяется перед switch. Release
Compose verifier требует допустимое
значение и равенство между четырьмя процессами. `.env.example` и runbook
описывают staged switch и rollback. Версия приложения и lock — 1.3.4.

## Red → green

- До правки `uv run pytest tests/test_event_identity.py -q -k 'event_reader_switch'`
  дал `6 failed, 2 passed`: значение `true` возвращало `False`, а пять
  неверных значений не вызывали `ValueError`.
- После правки
  `uv run --no-sync pytest tests/test_event_identity.py tests/test_production_topology.py tests/test_production_first_rollout_contract.py -q`
  дал `83 passed, 1 warning`. `--no-sync` потребовался после временного
  DNS-сбоя при обращении uv к PyPI.

## Проверки объединённого v1.3.4 среза

- `UV_OFFLINE=1 make test-unit`: 1715 passed, 18 deselected.
- `UV_OFFLINE=1 make lint`: passed.
- `UV_OFFLINE=1 make type-check`: passed.
- `UV_OFFLINE=1 make pre-commit`: passed, включая Ruff, mypy и AI layer.
- `UV_OFFLINE=1 make docs`: passed; Sphinx сообщил 155 предупреждений,
  большинство от существующих docstrings и отсутствующего `_static`.
- `UV_OFFLINE=1 make ai-validate`: passed.
- `UV_OFFLINE=1 make production-check`: passed.
- `uv lock --check --offline` и `git diff --check`: passed.
- `UV_OFFLINE=1 make security`: не выполнен до audit; pip-audit пытался
  обновить pip через недоступный PyPI. Terminal Security workflow остаётся gate.

## Границы и остаток

Источник `v1.3.3`, его tag и production не менялись. Новый bundle, образы,
release evidence и реальный strict/candidate/odds/bot цикл проверяются после
merge под новым immutable tag. Локальная правка не меняет словари, веса
модели или содержание существующих snapshots.

## Независимый review и повторный цикл

Первое review выявило P1: systemd Data Cycle читает `nhl.env`, шаблон
которого не содержал switch. Read-only VPS preflight затем подтвердил,
что этот же профиль используют API/бот, а прежний путь `production.env`
отсутствует. В повторном цикле флаг добавлен в
`refresh-profile.env.example`, тест проверяет его наличие, runbook требует
проверки актуального rendered Compose. Red тест
`test_scheduler_profile_provides_every_production_compose_input` падал из-за
отсутствующего ключа; после правки три targeted теста прошли. Независимый
re-review текущего diff: P1 закрыт, новых P0–P2 нет; reviewer повторил 97
целевых тестов, Ruff и `git diff --check`.

Проверенный source+docs commit:
`98d9cf3e0d0f248b9c6b217827d6cb5b18b9a0b7`.
Перед commit gate pre-commit hooks, включая Ruff и mypy, прошли. Остаточные
риски остаются в server release gates; локальный `make security` не завершил
аудит зависимостей из-за DNS/PyPI, terminal Security CI обязателен.
