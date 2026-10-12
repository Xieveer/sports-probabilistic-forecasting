# EPIC-040 — Сквозная проверка платформы на клубном футболе

> **Статус:** in_progress
> **Владелец:** Product Owner
> **Требование:** [REQ-040](../product/requirements/REQ-040-club-football-platform-e2e.md)

## Память Product Owner

- Инициатива: `EPIC-040`.
- Ветка: `initiative/epic-040-club-football-e2e`.
- Этап: Engineering. TASK-040-1 завершена; два candidate smoke-run и локальный
  materialize/API/bot fixture проверены, реальный upcoming остаётся открытым.
- Цель: проверить весь клубный пул одним локальным циклом до тестовой выдачи в боте
  и устранить замечания архитектурного разбора в рамках этого пути.
- Подтверждено: девять клубных соревнований как единый пул; локальный E2E без
  production-публикации; две модели одного рынка winner с независимыми П1/П2,
  остатком для ничьей и прямым 1X2;
  реальные upcoming Smart Tables для тестового календаря.
- Решение о рынке: [ADR-040](../architecture/adr/ADR-040-club-football-1x2-e2e.md);
  обе стратегии используют один `winner_1x2`.
- Evidence: локальный `source.csv` содержит только завершённые события;
  [REQ-021](../product/requirements/REQ-021-top-football-winner-baseline.md),
  [ADR-003](../architecture/adr/ADR-003-configured-multisport-portfolio.md),
  [production handoff](../operations/production-handoff.md).
- Предыдущая роль: Reviewer — устранил findings по DB-изоляции,
  `predict_single`, свежести upcoming и горизонту бот-запроса. До последней
  правки горизонта целевые `91 passed`; после неё `42 passed` в затронутой области.
- Следующая роль: Developer — реальный upcoming snapshot и локальный test bot,
  затем Reviewer по полному E2E.
- Блокер: Smart Tables API на текущей сети не завершает TLS handshake; нужен
  доступный маршрут или свежий экспорт. Fixture не подменяет реальный upcoming.
- Release intent: выпуск и deployment не запрошены.
- Обновлено: 2026-10-12.

## Проверяемый результат и задачи

| Задача | Результат | Проверка | Статус |
| --- | --- | --- | --- |
| [TASK-040-1](tasks/TASK-040-1-club-pool-catalog.md) | Закреплённый состав и coverage всего пула | Fixture и локальный data smoke | done |
| [TASK-040-2](tasks/TASK-040-2-winner-model-strategies.md) | Два winner-кандидата: независимые П1/П2 и 1X2 | Target, temporal и model contract tests | in_progress |
| [TASK-040-3](tasks/TASK-040-3-club-upcoming-test-delivery.md) | Локальная материализация, API и тестовый бот на реальном upcoming | Сквозной integration smoke | in_progress |
| [TASK-040-4](tasks/TASK-040-4-config-and-tool-boundaries.md) | Проверенные границы инструментов и долги состава запусков | Config contract tests, docs review | in_progress |

## Риски

Файл источника содержит исторические завершённые матчи, поэтому он не служит
доказательством доступности будущего календаря. Исторические котировки не имеют
подтверждённого времени получения. Production NHL остаётся эталонным регрессионным
контуром; его конфигурация и текущий выпуск не переключаются в этой инициативе.
