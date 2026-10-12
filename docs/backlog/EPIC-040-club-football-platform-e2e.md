# EPIC-040 — Сквозная проверка платформы на клубном футболе

> **Статус:** done
> **Владелец:** Product Owner
> **Требование:** [REQ-040](../product/requirements/REQ-040-club-football-platform-e2e.md)

## Память Product Owner

- Инициатива: `EPIC-040`.
- Ветка: `initiative/epic-040-club-football-e2e`.
- Этап: локальный результат подтверждён; TASK-040-1…4 завершены. Два candidate
  smoke-run и локальный E2E на реальном Smart Tables upcoming проверены.
- Цель: проверить весь клубный пул одним локальным циклом до тестовой выдачи в боте
  и устранить замечания архитектурного разбора в рамках этого пути.
- Подтверждено: девять клубных соревнований как единый пул; локальный E2E без
  production-публикации; две модели одного рынка winner с независимыми П1/П2,
  остатком для ничьей и прямым 1X2;
  реальные upcoming Smart Tables для тестового календаря.
- Решение о рынке: [ADR-040](../architecture/adr/ADR-040-club-football-1x2-e2e.md);
  обе стратегии используют один `winner_1x2`. Локальный data stage и legacy DAG:
  [ADR-041](../architecture/adr/ADR-041-local-data-stage-tournament-selection.md).
- Evidence: локальный `source.csv` содержит только завершённые события;
  [REQ-021](../product/requirements/REQ-021-top-football-winner-baseline.md),
  [ADR-003](../architecture/adr/ADR-003-configured-multisport-portfolio.md),
  [production handoff](../operations/production-handoff.md).
- Evidence: 89 реальных upcoming, 178 прогнозов двух стратегий, 168 через API
  в окне 168 ч; локальный бот показал П1/Х/П2, тестовое Telegram-сообщение
  доставлено (`message_id=172`). Исторический source не изменён.
- Предыдущая роль: Reviewer — подтвердил исправление P2 по ID и командам
  Smart Tables и отсутствие блокирующих findings по DVC/legacy Airflow.
- Архитектурный вердикт: конфигурационная композиция годится для новых
  совместимых турниров в локальном цикле; DVC features больше не имеет ручного
  списка. Работа нового спорта, другого рынка и своевременность нового
  production расписания этим E2E не подтверждены.
- Следующая роль: Product Owner — передать результаты владельцу; отдельное
  решение о research GO/ITERATE/STOP и production-модели не принято.
- Release intent: выпуск и deployment не запрошены.
- Обновлено: 2026-10-12.

## Проверяемый результат и задачи

| Задача | Результат | Проверка | Статус |
| --- | --- | --- | --- |
| [TASK-040-1](tasks/TASK-040-1-club-pool-catalog.md) | Закреплённый состав и coverage всего пула | Fixture и локальный data smoke | done |
| [TASK-040-2](tasks/TASK-040-2-winner-model-strategies.md) | Два winner-кандидата: независимые П1/П2 и 1X2 | Target, temporal и model contract tests | done |
| [TASK-040-3](tasks/TASK-040-3-club-upcoming-test-delivery.md) | Локальная материализация, API и тестовый бот на реальном upcoming | Сквозной integration smoke | done |
| [TASK-040-4](tasks/TASK-040-4-config-and-tool-boundaries.md) | Проверенные границы инструментов и долги состава запусков | Config contract tests, docs review | done |

## Риски

Файл источника содержит исторические завершённые матчи, поэтому он не служит
доказательством доступности будущего календаря. Исторические котировки не имеют
подтверждённого времени получения. Production NHL остаётся эталонным регрессионным
контуром; его конфигурация и текущий выпуск не переключаются в этой инициативе.
