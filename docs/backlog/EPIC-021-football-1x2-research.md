# EPIC-021 — Исследование 1X2 для топовых футбольных лиг

> **Статус:** cancelled — исходный план заменён последующими исследованиями
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-021](../product/requirements/REQ-021-top-football-winner-baseline.md)
> **ADR:** [ADR-021](../architecture/adr/ADR-021-football-1x2-research-pool.md)

## Цель и границы

Провести Research Mode цикл CatBoost для pooled футбольного 1X2: Big Five, РПЛ, ФНЛ, ЛЧ и
ЛЕ. Criteria locked holdout 2025/26: ROI ≥5%, coverage >20%, temporal validation и
probabilistic metrics. Historical `odd_*` — разрешённый пользователем, но непроверенный
last-prematch proxy; результат не означает подтверждённый production edge.

## Состояние инициативы

Исходный worktree `initiative/epic-021-football-1x2-research` не содержит
уникальных коммитов относительно `main`. Похожие работы и результаты находятся
в цепочке отдельных инициатив: [EPIC-040](EPIC-040-club-football-platform-e2e.md)
проверил локальный цикл, [EPIC-041](EPIC-041-advanced-club-1x2-search.md)
оценил модели на holdout, а [EPIC-043](EPIC-043-football-feature-research.md)
проверил новые гипотезы на более ранних периодах. Это не подтверждает
автоматического выполнения всех исходных критериев и задач EPIC-021.

ROI ≥5% на раскрытом holdout не достигнут; результат EPIC-041 — ITERATE.
По решению владельца исходный незавершённый план закрыт, его оставшиеся
задачи отменены, а не объявлены выполненными. Улучшение футбольного прогноза
рассматривается отдельно в новой инициативе; повторно использовать раскрытый
holdout для выбора гипотез нельзя.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-021-1](tasks/TASK-021-1-club-pool-data-contract.md) | Изолированный club-pool contract, fixture и ingest/clean smoke | REQ-021, ADR-021 | red/green tests, schema gate | cancelled |
| TASK-021-2 | Advanced features и leakage audit | TASK-021-1 | feature tests, processed validation | cancelled |
| TASK-021-3 | 1X2 target, CatBoost temporal baseline и Research Harness coverage gate | TASK-021-2 | temporal tests, experiment report | cancelled |
| TASK-021-4 | Полный backfill, research iterations и итоговый report | TASK-021-3 | locked-holdout evidence | cancelled |
| [TASK-021-5](tasks/TASK-021-5-bronze-completeness-manifest.md) | Manifest полноты bronze и поэтапный required/optional ingest | TASK-021-1 | unit/integration tests, coverage report | done |

## Риски и rollout

Promotion, deployment и публикация модели не выполнялись. ROI ограничен
допущением historical odds; повторное раскрытие locked holdout запрещено.

## Завершение

Исходный план закрыт без утверждения выполнения всех критериев. Существующее
evidence и независимые проверки последующих исследований находятся в EPIC-040,
EPIC-041 и EPIC-043; решение о новой инициативе принимается отдельно.
