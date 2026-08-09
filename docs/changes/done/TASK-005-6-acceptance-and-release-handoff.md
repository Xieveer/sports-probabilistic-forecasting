# TASK-005-6 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-005-6](../../backlog/tasks/TASK-005-6-acceptance-and-release-handoff.md)

## Реализованный результат

Добавлена команда `make acceptance-check` для уже запущенного release candidate.
Она выполняет только HTTP GET, параметризованный SQL `SELECT` и bot heartbeat
healthcheck; не запускает Worker/training, не отправляет Telegram-сообщения,
не выполняет DML и не печатает payloads. Проверяются liveness, readiness/DB,
API version, заранее выбранное prediction/model version, последний успешный
Worker state и доступность bot по свежему heartbeat.

`make production-check` теперь требует сам runner и exact acceptance-команду
для handoff со статусом `candidate`. Handoff заполнен runtime/migration/recovery,
artifact/rollback, env, budgets, retention, signals и ссылками на evidence.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `scripts/acceptance_check.py` | Non-mutating acceptance runner и безопасные сообщения ошибок. |
| `Makefile`, `.env.example` | Операторская команда и имена входных переменных. |
| `scripts/validate_production_readiness.py` | Строгий candidate gate handoff. |
| `docs/operations/production-handoff.md` | Candidate contract и release evidence package. |
| `tests/test_acceptance_check.py`, `tests/test_production_readiness_validation.py` | Контракт read-only поведения и обязательного handoff. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_acceptance_check.py tests/test_production_readiness_validation.py -q` — 3 failed: прежний runner не принимал release inputs, не читал Worker state, а candidate gate не требовал acceptance-команду.
- **Green:** тот же набор после реализации — 5 passed.
- **Review fix:** отдельный тест подтвердил, что пустая `SF_ACCEPTANCE_BOT_HEALTH_COMMAND` возвращает контролируемую ошибку, а не traceback.

## Фактически выполненные проверки

| Команда | Результат |
|---|---|
| `make lint` | Успешно. |
| `make test-unit` | Успешно: 842 passed, 8 deselected. |
| `make test` | Успешно: 851 passed, 30 warnings. |
| `make test-cov` | Успешно. |
| `make docs` | HTML собран успешно; 26 существующих warnings, включая docutils error в legacy docstring `StackingEnsemble.fit`. |
| `make ai-validate` | Успешно. |
| `make security` | Выполнено, **не пройдено**: `pip-audit` нашёл 154 известных уязвимости в 24 locked runtime-зависимостях; remediation требует отдельной задачи обновления зависимостей. |
| `make production-check` | Успешно. |
| `make pre-commit` | Успешно после автоматического форматирования первого прогона. |
| `git diff --check` | Успешно. |

## Review и release решение

Рассмотрены correctness, simplicity, architecture, security и operations
изменённого acceptance/release-контура. Один defect с пустой bot-командой
исправлен и покрыт тестом; блокирующих локальных findings не осталось.

Ручной security review подтвердил: runner не использует shell, SQL запрос
параметризован, stdout/stderr bot healthcheck подавлены, а DB URL выделен для
read-only роли. Остаточный риск — право `SELECT` должно быть реально выдано
Operations Agent; локальный тест не подтверждает его на VPS.

**Release verdict: NO-GO для production deployment.** Локальный candidate
готов, но security gate не пройден и отсутствуют обязательные remote evidence:
GitHub CI/security/image scans, GHCR digest/provenance, production DB role,
external Telegram/API connectivity, VPS backup/restore и фактический acceptance
run. Tag, image publish и rollout не выполнялись.

## Handoff и остаточные риски

Канонический вход следующего этапа —
[production-handoff.md](../../operations/production-handoff.md). Operations
Agent должен закрыть отдельную remediation-задачу зависимостей, заполнить
immutable image digests и remote evidence, затем повторно выполнить
`make acceptance-check` на выбранном candidate перед отдельным одобрением
deployment.
