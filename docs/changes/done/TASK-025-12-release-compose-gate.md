# TASK-025-12 — Исправление release Compose gate

## Результат

Исправлен validator rendered production Compose после failure tag pipeline
`v1.2.0`. Он проверяет отдельные secret file paths API/control, общий
service key для API и Telegram bot, notification aliases API/Worker и
dispatcher profile. Негативный тест отвергает прямой DB URL в environment.
Ресурсный gate учитывает одновременный dispatcher и Worker; лимит dispatcher
уменьшен до 192 МиБ. Immutable `v1.2.0` не менялся; согласованный выпуск —
`v1.2.1`.

После создания `v1.2.1` обнаружено, что tagged evidence validator ожидает
Compose без scheduler profile. Manual evidence workflow теперь сначала
проверяет полный Compose с dispatcher tagged production validator, затем
передаёт legacy subset tagged evidence validator. Application tag и runtime
образы при этом не меняются.

## Проверки

- Red: актуальный rendered Compose отвергался старым валидатором.
- Green: 37 целевых тестов, включая позитивный rendered Compose и два
  негативных случая; `make test-unit` — 1196 passed, 13 deselected.
- `make lint`, `make production-check`, `make ai-validate` — passed;
  `make docs` — exit 0 с существующими предупреждениями.
- Commit hooks: Ruff, mypy, YAML/TOML и AI validation — passed.
- Независимый Reviewer подтвердил отсутствие P0–P2 findings после
  исправления расчёта памяти; повторно выполнил 37 целевых тестов.
- Evidence workflow correction: 19 целевых тестов passed; независимый
  Reviewer не нашёл P0–P2 findings. Terminal workflow run остаётся release gate.

## Передача

Production не менялся. Terminal PR CI, tag pipeline, backup/restore,
server secrets, smoke и первый scheduled NHL run остаются в
[TASK-025-9](../../backlog/tasks/TASK-025-9-release-readiness.md).
