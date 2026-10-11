# TASK-038-1 — Ограниченная очередь кандидатов: отчёт Developer

## Результат

Строгий импорт NHL календаря сохраняет неизвестные tournament/team обозначения только для матчей UTC `observed_at−1d … observed_at+30d`, включая границы. 30 дней совпадают с проверяемым calendar coverage NHL API и горизонтом future odds batch. Отсутствие постоянной owner event-связи больше не создаёт `kind=event` candidate. Если ранее подтверждённая project event связь противоречит текущей canonical revision, отдельный conflict candidate сохраняется, в том числе вне оперативного окна.

Это исправляет NO-GO v1.3.5: один исторический проход 22 581 NHL событий создал 22 656 pending rows, главным образом 21 963 event ID и 693 старые команды. Исправление не меняет derived matcher, рынок, registry snapshot, grants, схему БД или модельные веса.

## Red → green

- Новый тест на известные tournament/team без owner event link падал до правки: вместо нуля возникал один event candidate.
- Интеграционный тест с историческими PHX/ATL и текущим матчем проверяет, что в outbox попадают только актуальные неизвестные обозначения. Повторный проход сохраняет тот же idempotency key для отдельного наблюдения, согласно текущему контракту очереди.
- Тест границ проверяет оба включённых края окна и по минуте снаружи; существующий тест конфликта подтверждённой event-связи остаётся зелёным.
- Developer: 19 целевых тестов в `test_registry_candidate_capture.py` и `test_canonical_bootstrap.py` прошли, Ruff check/format и `git diff --check` прошли. Отдельный вызов mypy по ORM модулям сообщил 343 прежние ошибки типизации `Column`; добавленные строки в диагностике не фигурируют. Проверка проекта через штатный `make type-check` будет выполнена на финальном срезе.

## Граница release gate

Полный `UV_OFFLINE=1 make test-unit` дал 1717 passed, 18 deselected; `UV_OFFLINE=1 make pre-commit` прошёл, включая Ruff и штатный mypy. `UV_OFFLINE=1 make lint`, `UV_OFFLINE=1 make type-check`, `UV_OFFLINE=1 make docs` (155 предупреждений), `UV_OFFLINE=1 make ai-validate`, `UV_OFFLINE=1 make production-check` и `uv lock --check --offline` прошли. Независимый review, terminal CI/Security, immutable source/image/model/evidence и серверный bounded feedback/forecast cycle остаются обязательными. Локальный pip-audit в предыдущем релизе не запустился из-за bootstrap; terminal Security workflow обязателен. Накопленные v1.3.5 outbox rows не опубликованы; после свежего backup/readback/restore они удалены адресно с exact predicate/count/range gate. Фактическое решение GO/NO-GO — в [production handoff](../../operations/production-handoff.md).

## Независимое review и commit gate

Reviewer проверил diff к `main e630a7c`, включая capture, UTC границы, инварианты сохранённой event-связи, idempotency, другие турниры, EPIC/TASK, handoff и runbook. P0–P2 findings нет. Самостоятельно выполнено `UV_OFFLINE=1 uv run pytest -q tests/test_registry_candidate_capture.py tests/test_canonical_bootstrap.py`: 19 passed; commit hook прошёл. Проверенный source commit: `54e8f3324e77ea7b3fa21f420276406faaea87c5`. Серверные release gates, реальная очередь feedback и 20 ticks остаются открытыми.
