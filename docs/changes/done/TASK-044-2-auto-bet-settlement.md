# TASK-044-2 — Итог

> **Статус:** done, ожидает итогового EPIC review
> **Задача:** [TASK-044-2](../../backlog/tasks/TASK-044-2-auto-bet-settlement.md)
> **Решение:** [ADR-044](../../architecture/adr/ADR-044-automatic-bet-settlement.md)

Worker после canonical import расчётно обновляет только открытые ставки
владельца по подтверждённому полному счёту NHL. Результат, payout и компактная
ссылка на canonical revision сохраняются в audit. Повторный вызов того же
run идемпотентен. Отдельный outbox item выпускается после terminal состояния;
claim API ограничивает содержимое владельцем. Ошибка или неполный результат
оставляет ставку открытой с причиной, void не угадывается.

Red: unit-тест сначала не находил модуль `auto_settlement`. Green:
`tests/test_bet_auto_settlement.py`, outbox, API и bot notification tests
прошли; миграция 0026 на пустой SQLite прошла. На отдельном локальном
PostgreSQL 16 создана схема 0025 и terminal строка outbox, затем применена
0026: старая строка, SELECT grant и sequence сохранились, новая отдельная
bet-summary строка вставилась. Production smoke остаётся gate выпуска.
