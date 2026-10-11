# TASK-031-2 — Отчёт: хранилище и закрытый API ставок

> **Статус задачи:** done
> **Дата:** 2026-10-11
> **Задача:** [TASK-031-2](../../backlog/tasks/TASK-031-2-real-bets-store-and-api.md)

## Реализованный результат

Созданы таблицы immutable контекстов карточек, отдельных фактических ставок
Winline в RUB и append-only audit. Публичный ответ прогноза содержит nullable
revision ID. Закрытый API сохраняет точный payload карточки до показа, проверяет
связь с immutable revision и допускает контекст календарного NHL матча без
прогноза. Каждое размещение имеет request ID; повтор возвращает прежнюю запись,
добор создаёт новую. Расчёт, исправление и отмена оставляют audit.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `migrations/versions/0025_real_bets_ledger.py`, `sports_forecast/service/db/models.py` | Additive schema |
| `sports_forecast/service/routers/real_bets.py` | Закрытый API и owner gate |
| `sports_forecast/deploy/database_roles.py` | Минимальные grants control роли |
| `sports_forecast/service/routers/predictions.py`, `sports_forecast/service/schemas.py` | Revision ID публичной карточки |
| `tests/test_real_bets_api.py`, `tests/test_readiness_and_migrations.py` | API, authorization, migration |

## Доказательство TDD

- **Red:** API-сценарии подготовлены до реализации; отдельный запуск красной фазы для этого модуля не зафиксирован.
- **Green:** адресный API тест проходит; повтор create, добор, owner isolation, revision, correction и manual context проверены.
- **Refactor:** обработаны уникальный конфликт конкурентного повтора, ограничен snapshot payload, выделен owner ID.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `make test-unit` | 1615 passed, 16 deselected |
| `uv run alembic upgrade head` на временной SQLite | head `0025_real_bets_ledger` |
| `make docs` | build succeeded, 155 warnings |
| `make pre-commit` | все hooks прошли после исправления типизации теста |
| `uv run pytest -q tests/test_real_bets_api.py tests/test_real_bets_finance.py tests/test_bot_real_bets.py tests/test_bot_commands.py tests/test_readiness_and_migrations.py` | 27 passed после форматирования и исправления типизации |

## Документация, review и follow-up

- [REQ-031](../../product/requirements/REQ-031-real-bets-ledger.md), [ADR-031](../../architecture/adr/ADR-031-real-bets-ledger.md), README и [runbook миграций](../../operations/database-migrations.md) обновлены.
- Независимый Reviewer нашёл race повторного create, отсутствие ручного матча и неверную owner границу; исправления повторно проверены, P0–P2 не найдены.
- Проверенный commit инициативы: `db0e4cb`.

## Остаточные риски

- PostgreSQL runtime grants ещё не применялись на реальном сервере; локальная проверка миграции выполнена на SQLite. Production-развёртывание не запрошено.
