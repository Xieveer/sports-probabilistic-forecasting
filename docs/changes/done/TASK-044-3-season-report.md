# TASK-044-3 — Итог

> **Статус:** done, ожидает итогового EPIC review
> **Задача:** [TASK-044-3](../../backlog/tasks/TASK-044-3-season-report.md)

Сезонная сводка использует дату `betting_report.season_start` из конфига
турнира; для NHL — 1 сентября. API возвращает те же денежные показатели и
точки накопленного общего PnL по дням МСК; бот отправляет PNG. Месячная
команда и денежные правила остались прежними. Для ненастроенного турнира
возвращается понятная ошибка без выдуманной даты.

Red: `season_summary` и модуль графика сначала отсутствовали. Green:
`tests/test_real_bets_finance.py`, `tests/test_real_bets_api.py`,
`tests/test_bot_real_bets.py`, `tests/test_bet_season_chart.py` прошли.
Пустой сезон создаёт нулевой график.
