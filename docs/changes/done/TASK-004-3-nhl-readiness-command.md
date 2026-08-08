# TASK-004-3 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-004-3](../../backlog/tasks/TASK-004-3-nhl-readiness-command.md)

## Реализованный результат

Добавлена NHL readiness CLI с безопасным dry-run и явным execute-режимом.
Последний сначала обновляет NHL source, проверяет наличие будущего расписания,
затем запускает quality gate и ограниченный historical odds refresh. При
межсезоннем отсутствии будущих матчей возвращается ``no_upcoming_schedule`` без
quality gate, Odds API и materialization.

## Доказательство TDD

- **Red:** `uv run pytest tests/test_nhl_readiness_cli.py -q` — readiness module
  отсутствовал, затем сценарий межсезонья завершался ошибкой.
- **Green:** та же команда — 2 passed.

## Фактически выполненные проверки

| Команда | Результат |
|---|---|
| `uv run pytest tests/test_nhl_readiness_cli.py -q` | 2 passed, 1 warning |
| `make lint` | Успешно |
| `uv run python -m sports_forecast.orchestration.nhl_readiness --dry-run` | Без сети вывел безопасный план |
| Локальная проверка `has_upcoming_schedule(data/source/nhl/source.csv)` | `False` |

## Фактический NHL run и риски

- Один refresh NHL API дозагрузил 8 матчей конца сезона; будущих матчей после
  2026-06-16 источник не вернул.
- Quality gate в исходном виде не проходит из-за непокрытого будущего окна;
  readiness-контур корректно преобразует этот межсезонний случай в штатный статус.
- Odds API после этого не вызывался, бесплатная квота не расходована.
