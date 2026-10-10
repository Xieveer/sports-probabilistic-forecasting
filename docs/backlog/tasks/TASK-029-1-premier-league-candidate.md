# TASK-029-1 — Конфигурационный кандидат Premier League

> **Статус:** done — реализация, независимый review и первоначальный CI PR #67 завершены
> **EPIC:** [EPIC-029](../EPIC-029-configured-tournament-onboarding.md)
> **Требование:** [REQ-029](../../product/requirements/REQ-029-premier-league-candidate.md)
> **Архитектура:** [ADR-030](../../architecture/adr/ADR-030-local-candidate-cycle.md),
> [ADR-003](../../architecture/adr/ADR-003-configured-multisport-portfolio.md)
> **Отчёт:** [done](../../changes/done/TASK-029-1-premier-league-candidate.md)

## Результат

Повторяемый кандидат `ENG1` на локальном CSV, с отчётом и проверяемым отказом
при неподготовленных данных. Каталог задаёт состав запуска и название.

## Проверка

- Интеграционные тесты изолируют `ENG1`, проверяют построение запуска из
  каталога, отказ при пропущенных данных/метриках и сохранение `candidate`.
- Реальный прогон на локальном CSV создаёт отчёт с provenance данных и run ID.
- Релевантные тесты NHL, lint и review проходят.

## Границы

Нет регулярного сбора будущих матчей, включения бота или production promotion.
