# TASK-025-17 — Признаки цикла должны соответствовать promoted-модели

> **Статус:** in_progress — код и review прошли; release/runtime gate открыт
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Наблюдаемый дефект

Изолированный повтор run v1.2.4 `dcd54406-7b88-4061-85b0-c60d76aef127`
на копиях БД, source snapshot и model bundle воспроизвёл
`materialization_failed`. Pipeline построил 3 668 inference-строк с 139
колонками признаков по `SF_FEATURES=basic`, тогда как promoted CatBoost
bundle ожидает 489 `advanced` признаков. `predict_proba` завершился
`CatBoostError` о несовпадении имени признака в позиции 18. Изолированная
сеть была internal-only, без production mounts и внешних записей; timer на
production выключены.

## Критерии исправления

- [x] Data Cycle получает конфигурацию сборки признаков из проверенного
  promoted model contract до feature processing и материализации.
- [x] Отсутствующий или несовместимый контракт завершает цикл явной
  безопасной ошибкой до публикации; несовпадение не маскируется.
- [x] Red→green тест воспроизводит `basic` runtime override при promoted
  `advanced`, а соседние feature/materialization тесты проходят.
- [ ] Operations проверяет production `SF_FEATURES=advanced` как защитную
  настройку и совместимый model bundle; секреты и пути приватных копий
  не попадают в Git.
- [ ] Независимый review, CI и production manual run подтверждают
  публикацию прогнозов; timer включается только после полного успеха.

## Handoff

Результат red→green, review и runtime gate фиксируется в
[отчёте выполнения](../../changes/done/TASK-025-17-promoted-feature-contract.md).
