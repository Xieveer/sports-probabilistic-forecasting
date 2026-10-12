# EPIC-040 — Сквозная проверка платформы на клубном футболе

> **Статус:** in_progress
> **Владелец:** Product Owner
> **Требование:** [REQ-040](../product/requirements/REQ-040-club-football-platform-e2e.md)

## Память Product Owner

- Инициатива: `EPIC-040`.
- Ветка: `initiative/epic-040-club-football-e2e`.
- Этап: Engineering, TASK-040-1 реализована и прошла независимое review;
  рынок и локальная тестовая граница подтверждены.
- Цель: проверить весь клубный пул одним локальным циклом до тестовой выдачи в боте
  и устранить замечания архитектурного разбора в рамках этого пути.
- Подтверждено: девять клубных соревнований как единый пул; локальный E2E без
  production-публикации; две модели одного рынка winner с независимыми П1/П2,
  остатком для ничьей и прямым 1X2;
  реальные upcoming Smart Tables для тестового календаря.
- Решение о рынке: [ADR-040](../architecture/adr/ADR-040-club-football-1x2-e2e.md)
  предложен, ожидает проверки контракта реализации.
- Evidence: локальный `source.csv` содержит только завершённые события;
  [REQ-021](../product/requirements/REQ-021-top-football-winner-baseline.md),
  [ADR-003](../architecture/adr/ADR-003-configured-multisport-portfolio.md),
  [production handoff](../operations/production-handoff.md).
- Предыдущая роль: Product Owner — принял направление пользователя.
- Предыдущая роль: Reviewer — проверил [TASK-040-1](tasks/TASK-040-1-club-pool-catalog.md)
  и [отчёт](../changes/done/TASK-040-1-club-pool-catalog.md) без P0/P1/P2,
  целевые `9 passed`.
- Следующая роль: Developer — два модельных подхода для одного 1X2.
- Блокер: доступность live upcoming Smart Tables на текущей сети пока не подтверждена;
  первый GET превысил 60 секунд, повтор остановлен без изменения source.
- Release intent: выпуск и deployment не запрошены.
- Обновлено: 2026-10-12.

## Проверяемый результат и задачи

| Задача | Результат | Проверка | Статус |
| --- | --- | --- | --- |
| [TASK-040-1](tasks/TASK-040-1-club-pool-catalog.md) | Закреплённый состав и coverage всего пула | Fixture и локальный data smoke | done |
| TASK-040-2 | Два winner-кандидата: независимые П1/П2 и 1X2 | Target, temporal и model contract tests | backlog |
| TASK-040-3 | Локальная материализация, API и тестовый бот на реальном upcoming | Сквозной integration smoke | backlog |
| TASK-040-4 | Один источник состава запусков и актуальные инструкции | Config contract tests, docs review | backlog |

## Риски

Файл источника содержит исторические завершённые матчи, поэтому он не служит
доказательством доступности будущего календаря. Исторические котировки не имеют
подтверждённого времени получения. Production NHL остаётся эталонным регрессионным
контуром; его конфигурация и текущий выпуск не переключаются в этой инициативе.
