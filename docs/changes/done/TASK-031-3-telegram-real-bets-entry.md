# TASK-031-3 — Отчёт: ввод ставок через Telegram

> **Статус задачи:** done
> **Дата:** 2026-10-11
> **Задача:** [TASK-031-3](../../backlog/tasks/TASK-031-3-telegram-real-bets-entry.md)

## Реализованный результат

В отдельной карточке прогноза у владельца появилась кнопка записи ставки.
`/bet_add ID_матча` позволяет начать из NHL календаря без прогноза. Диалог
собирает исход, свои деньги/фрибет, сумму, фактический коэффициент Winline,
время размещения и подтверждение. `/bets` показывает открытые ставки и ручной
расчёт с фактической выплатой и временем. `/bet_history`, `/bet_correct`,
`/bet_audit` и `/bet_cancel` дают просмотр, исправление, audit и отмену диалога.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/bot/handlers/real_bets.py` | Диалоги и команды владельца |
| `sports_forecast/bot/handlers/predict.py`, `dispatcher.py` | Кнопка и меню |
| `conf/bot.yaml`, `.env.example`, `docker-compose.prod.yml` | Отдельный ID владельца |
| `tests/test_bot_real_bets.py`, `tests/test_bot_predict_format.py` | Сценарии записи и owner/private gate |

## Доказательство TDD

- **Red:** тест кнопки в карточке падал до сохранения контекста и wiring.
- **Green:** адресные bot tests прошли после реализации.
- **Refactor:** правило ROUND_HALF_UP переиспользовано из финансового модуля; owner ID отделён от общего admin allowlist.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest -q tests/test_bot_real_bets.py tests/test_bot_commands.py tests/test_production_topology.py tests/test_production_first_rollout_contract.py` | 61 passed вместе с topology/rollout проверками до последнего теста rounding |
| `make test-unit` | 1615 passed, 16 deselected после последних правок |
| `uv run pre-commit run mypy --files ...` | passed после owner изменений |

## Документация, review и follow-up

- README, [REQ-031](../../product/requirements/REQ-031-real-bets-ledger.md), [ADR-031](../../architecture/adr/ADR-031-real-bets-ledger.md) обновлены.
- Независимый Reviewer проверил денежный диалог и owner access; P0–P2 после исправлений нет.
- Commit/push: после финального gate инициативы.

## Остаточные риски

- Незавершённый FSM диалог теряется при рестарте бота; подтверждённые ставки и audit сохраняются в БД. Повтор ввода незавершённого диалога безопасен как новая операция.
