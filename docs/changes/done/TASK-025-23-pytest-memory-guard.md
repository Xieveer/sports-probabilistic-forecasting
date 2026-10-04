# TASK-025-23 — Исправление потребления памяти тестом

## Изменено

В `test_canonical_refresh_gate.py` и `test_canonical_full_refresh.py` задано
предматчевое `prediction_ts`. В тесте full refresh пустой mock bundle теперь
выбрасывает `AssertionError`, если выполнение неожиданно доходит до его загрузки.
Production-код и реальные данные не менялись.

## Проверки

- Red: один тест full refresh под `ulimit -v 4194304` и `timeout 20s` упал на
  `AssertionError: Загрузка bundle до freshness gate` после установки защитного
  mock и до исправления timestamp.
- Green: четыре адресных теста под `ulimit -v 4194304` и `timeout 30s` —
  `4 passed`.
- `ruff check` и `ruff format --check` для двух изменённых тестовых файлов —
  успешно; `git diff --check` — успешно.

Первый пробный лимит 1 GiB не позволил импортировать CatBoost и не считается
проверкой теста. Полный набор pytest не запускался из-за инцидента с 14.3 GB RSS.

## Остаточный риск

Независимый Reviewer статически проверил diff и `git diff --check`, не нашёл
P0–P2 замечаний к коду и тестам. Более широкий прогон не выполнен. Незавершённый
[TASK-025-22](../../backlog/tasks/TASK-025-22-local-quality-parity.md) по
локальному production-like контуру остаётся отдельным gate.
